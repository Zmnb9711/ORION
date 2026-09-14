"""Step 5 production host with controlled external I/O, NOT blind field proof."""
import ast
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
import json
from pathlib import Path
import queue
import subprocess
import threading
from types import SimpleNamespace as NS

import pytest

import orion.full_voice_service as host
from orion.general_semantic_contracts import Mixed, SemanticProposal, parse_semantic
from orion.general_semantic_core import MixedPlan, FactPlan, render_general
from orion.general_semantic_voice import GeneralSemanticVoice
from orion.full_voice_core import FullVoiceCore
from orion.hybrid_aircraft_core import HybridAircraftCore
from orion.informational_presentation import InformationalPresentation
from orion.interaction_router import InteractionRouter
from orion.planner import PlannerCancellationToken
from orion.radio_router import RadioRouter
from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter
from orion.yandex_srs_live_core import YandexSrsStartRequest
from test_general_fact_registry import fixture
from test_general_semantic import SemanticWire
from test_full_voice import StreamingFakeRadio
from test_hybrid_aircraft import NOW, PURE, utterance

ROOT = Path(__file__).resolve().parents[1]
PARENT = '31546f9f191b060571cba32998c8cf232b345506'


def mixed(ids=('ownship.heading',), text='A developer conversational contribution.'):
    return {'kind':'MIXED', 'dialogue':{'kind':'DIALOGUE', 'text':text},
            'facts':{'kind':'FACT_REQUEST', 'capabilities':list(ids)}}


@pytest.mark.parametrize('language', ['ru-RU', 'en-US'])
@pytest.mark.parametrize('fast_tts_failure', [False, True])
@pytest.mark.parametrize('fast_source', [PURE, 'Какой мой текущий курс и координаты?'])
def test_real_host_unified_matrix_context_and_recovery(monkeypatch, tmp_path, language, fast_tts_failure, fast_source):
    """A–O: actual routing, provider protocol, Core/Gateway, presentation/Router."""
    bodies = [
        {'kind':'DIALOGUE','text':'A developer conversation about pottery.'},
        {'kind':'DIALOGUE','text':'Clay hardens when fired.'},
        {'kind':'FACT_REQUEST','capabilities':['ownship.heading']},
        {'kind':'FACT_REQUEST','capabilities':['ownship.true_airspeed']},
        {'kind':'FACT_REQUEST','capabilities':['ownship.position','ownship.altitude_msl']},
        mixed(('ownship.heading','ownship.pitch')),
        {'kind':'DIALOGUE','text':'The conversational topic can continue.'},
        {'kind':'FACT_REQUEST','capabilities':['ownship.heading']},
        {'kind':'META_REQUEST','topic':'capabilities'},
        {'kind':'CAPABILITY_GAP','need':'unproven fuel quantity'},
        {'kind':'CLARIFICATION','slot':'reference'},
        {'kind':'FACT_REQUEST','capabilities':['ownship.altitude_agl']},
        None,  # Controlled transport failure, no same-turn retry.
        {'kind':'DIALOGUE','text':'The semantic owner recovered.'},
        mixed(text='Controlled TTS failure.'),
        mixed(text='A later response is delivered.'),
    ]
    # Fast path -> General follow-up; exact recognizer belongs to old fixture,
    # never prescribed to a physical user. General test sources remain opaque.
    inputs = [utterance(fast_source)] + [replace(utterance(f'Developer integration input {i}.'), input_language=language)
                                  for i in range(len(bodies))]
    by_source = dict(zip([u.text for u in inputs[1:]], bodies))
    bundle = fixture()
    gateway, store = bundle[4:]
    stop = threading.Event()
    adapter = StreamingFakeRadio(threading.Event())
    radio = RadioRouter(default_transport_id='srs'); radio.register_adapter(adapter); radio.start()
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(provider='yandex', transport='srs', build_sha='f'*40)
    requests, plans, projections, texts, released, owners = [], [], [], [], [], []

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return NOW

    class Native:
        owner = future = None
        def __init__(self, *a, **k): pass
        async def open(self, key): pass
        def start(self, identity, at):
            self.owner = identity; self.future = asyncio.get_running_loop().create_future()
        async def end(self, identity, at): self.future.set_result(next(u for u in inputs if u.interaction_id == identity))
        async def result(self): return await self.future
        def release(self, identity): self.owner = self.future = None
        async def close(self): pass

    class Endpoint:
        tx_frames = packet_id = 0
        tx_marks = {}
        def __init__(self, *a):
            self.radio_router = radio; self.turn_events = queue.Queue(); self.enqueue(inputs[0])
        def enqueue(self, u):
            envelope = store.snapshot().telemetry
            envelope.state.heading_deg = 101.25 + len(released)
            store.set(envelope, received_at=NOW)
            for kind in (host.RadioTurnEventKind.START, host.RadioTurnEventKind.END):
                self.turn_events.put(NS(kind=kind, identity=u.interaction_id, timestamp=1.))
        def connect_radio(self): pass
        def start(self): pass
        def arm_physical_capture(self): pass
        def srs_adapter_runtime(self): return NS(bot_name='ORION', coalition=2)
        def failure(self): return None
        def release_turn(self, identity):
            released.append(identity)
            if len(released) == len(inputs): stop.set()
            else: self.enqueue(inputs[len(released)])
        def stop(self): radio.shutdown()

    class Configured:
        @classmethod
        def configured(cls, *a, **kw):
            class Wire(SemanticWire):
                async def send(self, value):
                    if value['type'] == 'response.create':
                        body = by_source[self.source]
                        if body is None: raise OSError('controlled_offline_transport')
                        self.body = json.dumps(body)
                    await super().send(value)
            owner = WarmYandexAircraftInterpreter(lambda:Wire(''), **kw)
            original = owner.interpret_general
            async def observed(request, cancellation):
                requests.append(request)
                return await original(request, cancellation)
            owner.interpret_general = observed; owners.append(owner); return owner

    class General(GeneralSemanticVoice):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            original = self.presentation.present
            async def present(final, context):
                plans.append(final)
                projection = self.core.context.project(self.core.context.epoch)
                assert projection.exchanges[-1].delivery == 'pending'
                assert not projection.exchanges[-1].user_heard
                projections.append(projection)
                return await original(final, context)
            self.presentation.present = present

    async def tts(self, text):
        self._requests(text); texts.append(text)
        if fast_tts_failure and len(texts) == 1: raise RuntimeError('fixture_fast_tts')
        if text.startswith('Controlled TTS failure.'): raise RuntimeError('fixture_tts')
        yield bytes(4800)

    class Hybrid(HybridAircraftCore):
        def __init__(self, g, provider, **kw): super().__init__(g, lambda:pytest.fail('Planner'), clock=lambda:NOW, **kw)
    class Info(InformationalPresentation):
        def __init__(self, *a, **kw): super().__init__(*a, clock=lambda:NOW, **kw)
    import orion.yandex_warm_aircraft_interpreter as warm
    monkeypatch.setattr(host, 'datetime', Clock); monkeypatch.setattr(warm, 'datetime', Clock)
    monkeypatch.setattr(host, 'InteractionRouter', lambda **kw:InteractionRouter(clock=lambda:NOW, **kw))
    monkeypatch.setattr(host, 'FullVoiceCore', lambda g:FullVoiceCore(g, clock=lambda:NOW))
    monkeypatch.setattr(host, 'HybridAircraftCore', Hybrid); monkeypatch.setattr(host, 'InformationalPresentation', Info)
    monkeypatch.setattr(host, 'GeneralSemanticVoice', General)
    monkeypatch.setattr(host, 'NativeSpeechKitTurns', Native); monkeypatch.setattr(host, 'GrpcSpeechKitStreamingPort', lambda:None)
    monkeypatch.setattr(host, 'SrsTransportDiagnostics', lambda *a, **kw:None)
    monkeypatch.setattr(host, 'build_tool_gateway', lambda **kw:gateway)
    monkeypatch.setattr(host, 'WarmYandexAircraftInterpreter', Configured)
    monkeypatch.setattr(host, 'realtime_test_evidence', recorder)
    monkeypatch.setattr(host.ProtectedStreamingTts, 'stream', tts)
    service = host.FullVoiceService(endpoint_factory=Endpoint)
    try:
        asyncio.run(asyncio.wait_for(service._voice(YandexSrsStartRequest(api_key='fixture', folder_id='fixture', eam_password='fixture'),
                                                   'step5-host', stop), 15))
        assert service.status().state != 'error'
        assert released == [u.interaction_id for u in inputs]
        assert len(requests) == len(bodies) == owners[0].operation_count
        assert len(texts) == len(adapter.transmit_calls) == len(inputs)
        assert len(owners) == 1 and owners[0].connect_count == 2 and not owners[0].owned
        assert requests[0].context.exchanges[-1].requested_capabilities == (('aircraft.identity',) if fast_source == PURE else ('ownship.heading','ownship.position'))
        assert requests[0].context.exchanges[-1].delivery == ('failed' if fast_tts_failure else 'completed')
        assert requests[6].context.exchanges[-1].outcome == 'MIXED'
        assert requests[11].context.exchanges[-1].clarification_slot == 'reference'
        assert requests[13].context.exchanges[-1].unavailable_reason == 'PROVIDER_UNAVAILABLE'
        assert requests[15].context.exchanges[-1].delivery == 'failed'
        assert not any(e.user_heard for p in projections for e in p.exchanges)
        assert len(gateway.calls) == 9  # first fast path + eight generic fact reads
        heading_values = [f.value for p in plans for f in
                          (p.plan.factual.facts if isinstance(p.plan, MixedPlan) and isinstance(p.plan.factual, FactPlan)
                           else p.plan.facts if isinstance(p.plan, FactPlan) else ()) if f.key == 'ownship.heading_deg']
        assert len(set(heading_values)) == len(heading_values)  # reread, not context values
        for request in requests:
            wire_context = request.context.model_dump_json()
            assert '101.25' not in wire_context and 'INJECTED_EXTRA_TELEMETRY' not in wire_context
        assert all('INJECTED_EXTRA' not in p.model_dump_json() and 'NEVER_SPEAK' not in p.text for p in plans)
        assert plans[-1].text.startswith('A later response is delivered.')
        assert plans[9].plan.reason == 'CAPABILITY_NOT_EXPOSED'
        assert any('context_projection' in e for e in recorder._events)
    finally:
        stop.set(); radio.shutdown()


@pytest.mark.parametrize('ids', [('aircraft.identity',), ('ownship.heading','ownship.position'), ('ownship.altitude_agl',)])
def test_mixed_binding_selected_only_and_tamper(ids):
    core, hybrid, u, request, gateway, store = fixture()
    result = parse_semantic(json.dumps(mixed(ids)))
    assert isinstance(result, Mixed)
    final = core.execute(u, SemanticProposal(request=request,response_id='fixture',result=result), PlannerCancellationToken(), hybrid)
    assert isinstance(final.plan, MixedPlan) and len(gateway.calls) == 1
    assert final.text == result.dialogue.text+' '+render_general(final.plan.factual, core.clock())
    assert core.authorize(final)
    assert not core.authorize(final.model_copy(update={'text':final.text+' forged'}))
    assert 'INJECTED_EXTRA' not in final.model_dump_json()
    core.context.accept(final, delivery='pending')
    entry = core.context.project().exchanges[-1]
    assert entry.reply == result.dialogue.text and entry.requested_capabilities
    assert '103.74' not in entry.model_dump_json()


def test_mixed_uses_dialogue_budget_but_rereads_fresh_facts():
    core, hybrid, u, request, gateway, store = fixture()
    later = request.created_at+timedelta(seconds=2)
    core.clock = lambda:later; core.router._now = lambda:later
    envelope = store.snapshot().telemetry; store.set(envelope, received_at=request.created_at)
    # Gateway fixture clock remains request time, so receipt binding stays valid.
    final = core.execute(u, SemanticProposal(request=request,response_id='fixture',result=parse_semantic(json.dumps(mixed()))),
                         PlannerCancellationToken(), hybrid)
    assert isinstance(final.plan, MixedPlan) and final.plan.deadline <= request.created_at+timedelta(seconds=5)


def test_step5_scope_and_frozen_host_lifecycle():
    expected = {'orion/full_voice_service.py','orion/general_semantic_core.py','orion/general_semantic_contracts.py',
                'orion/general_semantic_voice.py','orion/general_fact_presentation.py','orion/interaction_router.py',
                'orion/yandex_warm_aircraft_interpreter.py','orion/realtime_test_evidence.py'}
    paths = set(subprocess.check_output(['git','diff',PARENT,'--name-only','--','orion','dcs-export','packaging'],cwd=ROOT).decode().splitlines())
    assert paths == expected
    assert not subprocess.check_output(['git','diff',PARENT,'--','docs/architecture','orion/general_fact_registry.py'],cwd=ROOT)
    class OutsideAnswer(ast.NodeTransformer):
        def visit_AsyncFunctionDef(self,node):
            if node.name == 'answer': return None
            return self.generic_visit(node)
        def visit_ImportFrom(self,node):
            return None if node.module == 'orion.aircraft_interpretation' else node
    before = ast.parse(subprocess.check_output(['git','show',PARENT+':orion/full_voice_service.py'],cwd=ROOT).decode())
    after = ast.parse((ROOT/'orion/full_voice_service.py').read_text(encoding='utf-8'))
    assert ast.dump(OutsideAnswer().visit(before)) == ast.dump(OutsideAnswer().visit(after))
    for path in expected:
        old = ast.parse(subprocess.check_output(['git','show',PARENT+':'+path],cwd=ROOT).decode())
        new = ast.parse((ROOT/path).read_text(encoding='utf-8'))
        calls = lambda tree:{ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)}
        assert not any(c.startswith('re.') for c in calls(new)-calls(old))


def test_test_mode_only_context_evidence_and_unknown_fields(tmp_path):
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.record_conversation_slice('context_delivery', realtime_session_id='s',route_source='GENERAL_SEMANTIC', context_projection='{}')
    assert not recorder._events
    recorder.start(provider='yandex',transport='srs',build_sha='f'*40)
    recorder.record_conversation_slice('context_delivery',realtime_session_id='s',route_source='GENERAL_SEMANTIC',
                                       context_projection='{}',secret='EXCLUDED',audio='EXCLUDED')
    assert recorder._events[-1]['context_projection']=='{}'
    assert 'EXCLUDED' not in json.dumps(list(recorder._events))


def test_step5_provider_gate_offline_one_owner_four_operations(monkeypatch):
    from scripts import foundation_fact_gate as gate
    from scripts.foundation_integration_gate import CASES
    monkeypatch.setattr(gate, 'CASES', CASES)
    bodies = {c[1]: mixed(c[3]) if c[2]=='MIXED' else {'kind':'FACT_REQUEST','capabilities':list(c[3])} for c in CASES}
    class Wire(SemanticWire):
        async def send(self, value):
            if value['type']=='response.create': self.body=json.dumps(bodies[self.source])
            await super().send(value)
    report = asyncio.run(gate.evaluate(lambda observe:WarmYandexAircraftInterpreter(lambda:Wire(''), general=True,observe=observe), lambda r:None))
    assert report['pass'] and report['operation_count']==4 and report['connect_count']==1
    assert [t['request']['language'] for t in report['turns']]==['ru-RU','ru-RU','en-US','en-US']
    assert report['turns'][1]['request']['context']['exchanges'][-1]['outcome']=='MIXED'
    assert all(t['core_fact_reads']==1 for t in report['turns'])


@pytest.mark.parametrize('corruption',['value','wildcard','authority','stale','unknown','cancel'])
def test_mixed_negative_authority_and_availability(corruption):
    body=mixed()
    if corruption in {'value','wildcard'}:
        if corruption=='value': body['facts']['value']=999
        else: body['facts']['capabilities']=['ownship.*']
        with pytest.raises(ValueError): parse_semantic(json.dumps(body))
        return
    def transform(result):
        if corruption!='authority': return result
        raw=result.model_dump(mode='json')
        raw['data']['snapshot']['heading_deg']['authority']='observed'
        return type(result).model_validate(raw)
    core,hybrid,u,request,gateway,store=fixture(age=6 if corruption=='stale' else 0,transform=transform)
    if corruption=='unknown':
        packet=store.snapshot().telemetry; packet.state.heading_valid=False; store.set(packet,received_at=NOW)
    token=PlannerCancellationToken()
    if corruption=='cancel': token.cancel()
    proposal=SemanticProposal(request=request,response_id='fixture',result=parse_semantic(json.dumps(body)))
    if corruption in {'authority','cancel'}:
        with pytest.raises(ValueError): core.execute(u,proposal,token,hybrid)
        assert not core.completed
    else:
        final=core.execute(u,proposal,token,hybrid)
        assert final.plan.factual.kind=='TRUTHFUL_UNAVAILABLE'
        assert '103.74' not in final.text
        assert final.text.startswith(body['dialogue']['text'])
        core.context.accept(final)
        assert core.context.project().exchanges[-1].requested_capabilities==('ownship.heading',)


@pytest.mark.parametrize('language',['ru-RU','en-US'])
def test_output_language_all_common_facts_and_no_truncation(language):
    from orion.general_fact_registry import CATALOG
    from test_general_fact_registry import execute
    for definition in CATALOG:
        bundle=list(fixture())
        core,hybrid,u,request,*_=bundle
        request=request.model_copy(update={'language':language})
        core.pending[u.interaction_id]=request; bundle[3]=request
        final=execute(bundle,(definition.capability,))
        assert final.text
        if language=='en-US': assert not any('а' <= char.lower() <= 'я' for char in final.text)
    core,hybrid,u,request,*_=fixture()
    long=mixed(text='x'*401)
    with pytest.raises(ValueError): parse_semantic(json.dumps(long))
    assert not core.completed


def test_mixed_wire_schema_explicit_without_relaxing_strict_admission():
    from orion.general_semantic_contracts import provider_instructions
    instructions=provider_instructions()
    assert '"facts":{"kind":"FACT_REQUEST","capabilities":' in instructions
    assert '"dialogue":{"kind":"DIALOGUE","text":' in instructions
    # The observed structural failure class still fails closed; no silent repair,
    # guessed kind, partial execution, second model or provider retry.
    malformed={'kind':'MIXED','facts':{'capabilities':['ownship.pitch']},'dialogue':'Developer explanation.'}
    with pytest.raises(ValueError): parse_semantic(json.dumps(malformed))
    assert isinstance(parse_semantic(json.dumps(mixed(('ownship.pitch',)))),Mixed)
