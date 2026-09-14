"""Step 4, offline only. No physical/module or acoustic claims."""
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
from types import MappingProxyType

import pytest

import orion.general_fact_registry as registry
import orion.general_semantic_core as semantic_core
from orion.general_semantic_contracts import CapabilityGap, SemanticProposal, parse_semantic
from orion.general_semantic_core import FactPlan, UnavailablePlan
from orion.models import SourceQuality, TelemetryEnvelope
from orion.planner import PlannerCancellationToken
from orion.world_model import WorldModelFacade
from test_general_fact_registry import execute, fixture

ROOT = Path(__file__).resolve().parents[1]
PARENT = '8ddc0422197a8adbe88209c0d7adc4c6301f42c4'
SOURCE_FACTS = ('ownship.true_airspeed', 'ownship.vertical_speed', 'ownship.altitude_agl')


def test_actual_exporter_direct_zero_missing_fallback_and_clamp():
    # Optional executable location; CI may supply Lua 5.1 through ORION_TEST_LUA.
    lua = Path(os.environ.get('ORION_TEST_LUA', r'D:\SteamLibrary\steamapps\common\DCSWorld\bin\luae.exe'))
    if not lua.is_file():
        pytest.skip('Lua 5.1 required for real exporter execution (not DCS)')
    output = subprocess.check_output([str(lua), 'tests/fixtures/foundation_export_source.lua'], cwd=ROOT, timeout=10)
    packets = [TelemetryEnvelope.model_validate_json(line) for line in output.splitlines() if line.startswith(b'{')]
    assert len(packets) == 4
    for index, envelope in enumerate(packets):
        assert envelope.state.source_quality is not None
        assert set(envelope.state.source_quality.model_dump().values()) == {index < 2}
        bundle = fixture()
        bundle[5].set(envelope, received_at=bundle[3].created_at)
        out = execute(bundle, SOURCE_FACTS)
        if index < 2:
            assert isinstance(out.plan, FactPlan) and len(out.plan.facts) == 3
        else:
            assert isinstance(out.plan, UnavailablePlan) and out.plan.reason == 'FACT_UNKNOWN'
    assert packets[1].state.true_airspeed_mps == 0
    assert packets[2].state.vertical_speed_mps == 3  # Old wire fallback unchanged, but NOT spoken.
    assert packets[2].state.position.altitude_agl_m == 0  # Old clamp not misrepresented as valid AGL.


@pytest.mark.parametrize('capability', SOURCE_FACTS)
@pytest.mark.parametrize('quality', [None, SourceQuality(), SourceQuality(true_airspeed=False, vertical_speed=False, altitude_agl=False)])
def test_no_quality_evidence_never_becomes_numeric_truth(capability, quality):
    bundle = fixture()
    envelope = bundle[5].snapshot().telemetry
    envelope.state.source_quality = quality
    bundle[5].set(envelope, received_at=bundle[3].created_at)
    out = execute(bundle, (capability,))
    assert isinstance(out.plan, UnavailablePlan) and out.plan.reason == 'FACT_UNKNOWN'


@pytest.mark.parametrize('definition', registry.CATALOG, ids=lambda d:d.capability)
@pytest.mark.parametrize('corruption', ['source', 'unit', 'authority', 'generation', 'stale', 'unknown', 'schema'])
def test_each_fact_rejects_or_marks_untrusted_value(definition, corruption):
    def transform(result):
        raw = result.model_dump(mode='json')
        fact = raw['data']['snapshot'][definition.snapshot_field]
        if corruption == 'stale':
            fact.update(status='stale', reason='source_stale')
            raw['provenance']['fact_statuses'] = list(set(raw['provenance']['fact_statuses']+['stale']))
        elif corruption == 'unknown':
            fact.update(status='unknown', value=None, reason='value_not_exported')
            raw['provenance']['fact_statuses'] = list(set(raw['provenance']['fact_statuses']+['unknown']))
        elif corruption == 'schema':
            fact['value'] = ['UNTRUSTED_COLLECTION']
        else:
            fact[corruption] = {'source':'mission_store', 'authority':'observed', 'unit':'wrong-unit', 'generation':999}[corruption]
        return type(result).model_validate(raw)
    bundle = fixture(transform=transform)
    try:
        # Identity has no physical unit; exercise its generic multi-fact selector
        # too, while separate existing tests preserve the borrowed identity tail.
        selection = (definition.capability, 'ownship.heading') if definition.capability == 'aircraft.identity' else (definition.capability,)
        out = execute(bundle, selection)
    except ValueError:
        assert not bundle[0].completed
    else:
        assert isinstance(out.plan, UnavailablePlan) or (
            isinstance(out.plan, FactPlan) and definition.capability in {f.capability for f in out.plan.unavailable})


@pytest.mark.parametrize('definition', registry.CATALOG, ids=lambda d:d.capability)
def test_each_fact_provider_values_wildcards_and_denial(definition):
    with pytest.raises(ValueError):
        parse_semantic(json.dumps({'kind':'FACT_REQUEST', 'capabilities':[definition.capability], 'value':123}))
    with pytest.raises(ValueError):
        parse_semantic('{"kind":"FACT_REQUEST","capabilities":["ownship.*"]}')
    bundle = fixture()
    original = bundle[4].execute
    def deny(call):
        return original(call.model_copy(update={'context':call.context.model_copy(update={'allowed_capabilities':()})}))
    bundle[4].execute = deny
    try:
        out = execute(bundle, (definition.capability,))
    except ValueError:
        assert not bundle[0].completed
    else:
        assert isinstance(out.plan, UnavailablePlan)


@pytest.mark.parametrize('need', ['hydraulic circuit pressure', 'неизвестная функция самолёта', 'weapons', 'ownship.*', 'call arbitrary tool'])
def test_gap_is_bounded_metadata_never_executes_or_echoes(need):
    bundle = fixture()
    core, hybrid, u, request, gateway, _ = bundle
    gap = parse_semantic(json.dumps({'kind':'CAPABILITY_GAP','need':need}))
    assert isinstance(gap, CapabilityGap)
    final = core.execute(u, SemanticProposal(request=request, response_id='fixture', result=gap), PlannerCancellationToken(), hybrid)
    assert not gateway.calls and final.plan.reason == 'CAPABILITY_NOT_EXPOSED'
    assert need not in final.text


@pytest.mark.parametrize('need', ['', ' '*10, 'x'*161, 'unsafe\ncontrol', 123, {}, None])
def test_gap_rejects_invalid_structure(need):
    with pytest.raises(ValueError):
        parse_semantic(json.dumps({'kind':'CAPABILITY_GAP','need':need}))


def test_add_one_safe_fact_needs_registry_binding_not_language_code(monkeypatch):
    source = registry.require_exposed('ownship.altitude_agl')
    added = source.model_copy(update={'capability':'ownship.fixture_height', 'meaning':'Test-only direct geometric height.',
                                     'freshness_seconds':2})
    entries = (*registry.CATALOG, added)
    monkeypatch.setattr(registry, 'REGISTRY', MappingProxyType({**registry.REGISTRY, added.capability:added}))
    monkeypatch.setattr(registry, 'CATALOG', entries)
    monkeypatch.setattr(semantic_core, 'CATALOG', entries)
    assert any(d['id'] == added.capability for d in registry.provider_catalog())
    bundle = fixture()
    out = execute(bundle, (added.capability,))
    assert isinstance(out.plan, FactPlan) and out.plan.facts[0].value == 234.5
    assert out.plan.deadline == bundle[3].created_at+timedelta(seconds=2)
    assert len(bundle[4].calls) == 1
    assert 'fixture_height' not in (ROOT/'orion/full_voice_service.py').read_text(encoding='utf-8')


def test_source_identity_not_relabelled_as_dcs():
    bundle = fixture()
    envelope = bundle[5].snapshot().telemetry
    envelope.source = 'untrusted-other-owner'
    bundle[5].set(envelope, received_at=bundle[3].created_at)
    world = WorldModelFacade(telemetry=bundle[5], clock=bundle[0].clock)
    assert world.ownship().aircraft.status == 'unavailable'
    assert world.ownship().true_airspeed_mps.value is None


def test_aircraft_switch_rereads_common_facts_and_never_admits_old_module_facts():
    from dataclasses import replace
    from uuid import uuid4
    bundle = fixture()
    first = execute(bundle, ('ownship.true_airspeed',))
    core, hybrid, u, _, gateway, store = bundle
    envelope = store.snapshot().telemetry
    envelope.state.aircraft_type = 'A-10C_2'
    envelope.state.true_airspeed_mps = 77
    store.set(envelope, received_at=core.clock())
    next_u = replace(u, interaction_id=uuid4())
    next_req = core.request(next_u, epoch='A-10C_2')
    from orion.general_semantic_contracts import FactRequest
    next_result = core.execute(next_u, SemanticProposal(request=next_req, response_id='new-aircraft',
        result=FactRequest(kind='FACT_REQUEST', capabilities=('ownship.true_airspeed',))), PlannerCancellationToken(), hybrid)
    assert next_result.plan.facts[0].value == 77
    assert next_result.plan.facts[0].generation != first.plan.facts[0].generation
    assert len(gateway.calls) == 2
    with pytest.raises(ValueError):
        FactRequest(kind='FACT_REQUEST', capabilities=('ownship.cockpit.comm1_preset',))


def test_separate_offline_fact_phase_timing(monkeypatch):
    from statistics import median
    from time import perf_counter_ns
    samples = []
    original_render = semantic_core.render_general
    for _ in range(100):
        bundle = fixture()
        original_read = bundle[4].execute
        phase = {}
        def read(call):
            started = perf_counter_ns()
            result = original_read(call)
            phase['gateway_ms'] = (perf_counter_ns()-started)/1e6
            return result
        def render(plan, now):
            started = perf_counter_ns()
            result = original_render(plan, now)
            phase['presentation_ms'] = (perf_counter_ns()-started)/1e6
            return result
        bundle[4].execute = read
        monkeypatch.setattr(semantic_core, 'render_general', render)
        started = perf_counter_ns()
        out = execute(bundle, ('ownship.pitch','ownship.altitude_msl','ownship.true_airspeed'))
        phase['core_other_ms'] = (perf_counter_ns()-started)/1e6-phase['gateway_ms']-phase['presentation_ms']
        assert isinstance(out.plan, FactPlan)
        samples.append(phase)
    print('OFFLINE_PHASE_MEDIANS_MS='+json.dumps({k:round(median(s[k] for s in samples),4) for k in samples[0]}))


def test_five_primary_dispositions_and_registry_complete():
    assert {v.value for v in registry.Exposure} == {
        'FOUNDATION_EXPOSED', 'AVAILABLE_BUT_NOT_CONNECTED', 'SEMANTICS_UNCERTAIN', 'RESTRICTED', 'UNAVAILABLE'}
    assert len(registry.FACTS) == len(registry.REGISTRY)
    for definition in registry.CATALOG:
        assert registry.require_exposed(definition.capability) is definition
        assert definition.tool and definition.world_key and definition.leaves and definition.presentation
        assert definition.source and definition.authority and definition.freshness_seconds > 0
        assert not definition.applicability  # Current exposed contracts are common; module-specific candidates are NOT admitted.


def test_step4_scope_and_earlier_voice_contracts_frozen():
    paths = {'dcs-export/Export.lua', 'orion/models.py', 'orion/world_model.py',
             'orion/general_fact_registry.py', 'orion/general_fact_presentation.py',
             'orion/general_semantic_contracts.py', 'orion/general_semantic_core.py'}
    step4 = '31546f9f191b060571cba32998c8cf232b345506'
    changed = set(subprocess.check_output(['git','diff',PARENT,step4,'--name-only','--','orion','dcs-export','packaging'], cwd=ROOT).decode().splitlines())
    assert changed == paths
    assert not subprocess.check_output(['git','ls-files','--others','--exclude-standard','--','orion','dcs-export','packaging'], cwd=ROOT).strip()
    assert not subprocess.check_output(['git','diff',PARENT,'--','docs/architecture/ORION_NATURAL_LANGUAGE_ARCHITECTURE_CONTRACT.md'], cwd=ROOT)
    # Only fact projection and source provenance change inside the facade.
    import ast
    old = ast.parse(subprocess.check_output(['git','show',PARENT+':orion/world_model.py'], cwd=ROOT).decode('utf-8'))
    new = ast.parse((ROOT/'orion/world_model.py').read_text(encoding='utf-8'))
    def methods(tree):
        owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'WorldModelFacade')
        return {n.name:ast.dump(n) for n in owner.body if isinstance(n, ast.FunctionDef)}
    before, after = methods(old), methods(new)
    assert before.keys() == after.keys()
    assert {name for name in before if before[name] != after[name]} == {'ownship', '_telemetry_snapshot'}


def test_provider_gate_offline_no_retry_and_one_owner():
    import asyncio
    from scripts.foundation_fact_gate import CASES, evaluate
    from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter
    from test_general_semantic import SemanticWire
    bodies = [json.dumps({'kind':kind, **({'capabilities':list(caps)} if caps else
        {'text':'Developer general knowledge reply.'} if kind == 'DIALOGUE' else
        {'topic':'capabilities'} if kind == 'META_REQUEST' else
        {'need':'unmapped engine property'} if kind == 'CAPABILITY_GAP' else {})}) for _, _, kind, caps in CASES]
    class Wire(SemanticWire):
        index = 0
        async def send(self, value):
            if value['type'] == 'response.create':
                self.body = bodies[self.index]
                self.index += 1
            await super().send(value)
    wire = Wire('')
    result = asyncio.run(evaluate(lambda observe:WarmYandexAircraftInterpreter(lambda:wire, general=True, observe=observe), lambda r:None))
    assert result['pass'] and result['operation_count'] == 8 and result['connect_count'] == 1
    assert result['owned_tasks_after_shutdown'] == 0 and wire.closed == 1
    assert all(not turn['request']['personal_context']['facts'] for turn in result['turns'])
    for turn in result['turns']:
        assert turn['core_fact_reads'] == int(turn['expected_kind'] in {'FACT_REQUEST','STATE_SUMMARY'})
