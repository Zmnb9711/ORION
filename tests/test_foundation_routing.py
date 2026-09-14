"""Step 1 actual-host routing proof. All phrases below are fixtures, not grammar.

Real FullVoiceService, General/Core, protocol parsing, presentation and RadioRouter;
fake STT FINAL, provider wire, authoritative Gateway fixture and radio/audio I/O.
No network, credentials, physical DCS/SRS or product acceptance claim.
"""
import ast
from dataclasses import replace
import json
from typing import cast

import pytest

import orion.full_voice_service as host
import orion.hybrid_aircraft_core as local
import orion.conversational_presentation as legacy
from orion.general_semantic_voice import GeneralSemanticVoice
from orion.hybrid_aircraft_contracts import HybridRoute
from orion.planner import PlannerCancellationToken
from orion.tool_gateway import ToolGateway
from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter
from test_general_semantic import SemanticWire
from test_hybrid_aircraft import Gateway, PURE, MIXED, FREE, utterance, NOW
from test_hybrid_host import test_gate10_normal_host_coexistence_and_single_owner as replay
from test_interaction_router import gateway


@pytest.mark.parametrize('source,kind,capability', [
    ('  A curious unresolved request.\n', 'DIALOGUE', None),
    ('Сегодня как-то непросто летится.', 'DIALOGUE', None),
    ('как дела', 'DIALOGUE', None),
    (FREE, 'DIALOGUE', None),
    (MIXED, 'MIXED', 'aircraft.identity'),
    ('Какой у меня самолёт? И объясни принцип подъёмной силы.', 'MIXED', 'aircraft.identity'),
    ('Hello. Tell me my heading, and let us discuss something else.', 'MIXED', 'ownship.heading'),
    ('Добрый день! В каком самолёте', 'CLARIFICATION', None),
    ('Какой это самолёт?', 'CLARIFICATION', None),
    ('Tell me the aircraft identity in different words.', 'FACT_REQUEST', 'aircraft.identity'),
    ('Что у нас за машина?', 'FACT_REQUEST', 'aircraft.identity'),
    ('Какой мой текущий курс и координаты? И ещё поговорим.', 'MIXED', 'ownship.heading'),
])
def test_complete_final_reaches_one_general_owner(monkeypatch, tmp_path, source, kind, capability):
    def forbidden(*args, **kwargs):
        pytest.fail('legacy language admission / separate Conversation entered')
    monkeypatch.setattr(local, 'eligible_decomposition', forbidden)
    monkeypatch.setattr(local, 'recognize_local_decomposition', forbidden)
    monkeypatch.setattr(legacy, 'ConversationVoice', forbidden)
    monkeypatch.setattr(Gateway, 'definitions', lambda self: gateway().definitions(), raising=False)
    body = {'kind': kind}
    if kind == 'DIALOGUE': body['text'] = 'An original fixture reply.'
    if kind == 'FACT_REQUEST': body['capabilities'] = [capability]
    if kind == 'MIXED':
        body.update(dialogue={'kind': 'DIALOGUE', 'text': 'A fixture conversational fragment.'},
                    facts={'kind': 'FACT_REQUEST', 'capabilities': [capability]})
    if kind == 'CLARIFICATION': body['slot'] = 'object'
    wire = SemanticWire(json.dumps(body))
    owners, requests, entries = [], [], []
    class Configured:
        @classmethod
        def configured(cls, *args, **kwargs):
            owner = WarmYandexAircraftInterpreter(lambda: wire, **kwargs)
            original = owner.interpret_general
            async def observe(request, cancellation):
                requests.append(request)
                return await original(request, cancellation)
            owner.interpret_general = observe
            owners.append(owner)
            return owner
    monkeypatch.setattr(host, 'WarmYandexAircraftInterpreter', Configured)
    original_run = GeneralSemanticVoice.run
    async def observe_run(self, final, hybrid, cancellation, **kwargs):
        entries.append(final)
        prior = hybrid._completed[final.interaction_id]
        assert prior[0] is final and prior[1].finalized is None
        assert prior[1].route in {HybridRoute.UNSUPPORTED, HybridRoute.AMBIGUOUS}
        assert not hybrid.gateway.calls
        await original_run(self, final, hybrid, cancellation, **kwargs)
        # Replay cannot reinterpret or present a second answer; actual Core ledger.
        with pytest.raises(ValueError, match='general_turn_replay_or_capacity'):
            await original_run(self, final, hybrid, cancellation, **kwargs)
    monkeypatch.setattr(GeneralSemanticVoice, 'run', observe_run)
    expected_kind = {'DIALOGUE': 'DIALOGUE_NON_AUTHORITATIVE', 'FACT_REQUEST': 'CORE_FACT_AUTHORITATIVE',
                     'MIXED': 'TRUTHFUL_UNAVAILABLE', 'CLARIFICATION': 'CLARIFICATION'}[kind]
    captured = []
    replay(monkeypatch, tmp_path, source, True, 0, 'active', general_kind=expected_kind,
           expected_reads=int(kind == 'FACT_REQUEST'), capture=captured)
    assert len(entries) == len(requests) == len(owners) == 1
    assert entries[0].text == requests[0].source_text == source
    assert requests[0].interaction_id == entries[0].interaction_id
    assert owners[0].operation_count == 1
    assert sum(e['type'] == 'response.create' for e in wire.sent) == 1
    assert [e['item']['content'][0]['text'] for e in wire.sent
            if e['type'] == 'conversation.item.create'] == [source]
    assert captured[0]['tx_count'] == len(captured[0]['texts']) == 1
    assert not any(e.get('route') == 'LOCAL_SOCIAL' for e in captured[0]['events'])
    if kind == 'MIXED':
        # Routing only, explicitly NOT a new Mixed implementation.
        assert not captured[0]['calls']
        assert 'A fixture conversational fragment.' not in captured[0]['texts'][0]
        assert any(e.get('semantic_kind') == 'MIXED' for e in captured[0]['events'])


@pytest.mark.parametrize('source', [PURE, 'Какой мой текущий курс и координаты?'])
def test_proven_full_turn_fast_paths_do_not_call_general(monkeypatch, tmp_path, source):
    async def forbidden(*args, **kwargs):
        pytest.fail('full proven match entered General')
    monkeypatch.setattr(GeneralSemanticVoice, 'run', forbidden)
    capture = []
    replay(monkeypatch, tmp_path, source, True, 0, 'active', capture=capture)
    assert capture[0]['tx_count'] == 1 and len(capture[0]['calls']) == 1


@pytest.mark.parametrize('source', [PURE, MIXED, FREE, 'Какой это самолёт?', 'Unresolved fixture.'])
def test_full_turn_registration_preserves_replay_and_cancellation(source):
    g = Gateway()
    core = local.HybridAircraftCore(cast(ToolGateway, g), lambda: pytest.fail('Planner'), clock=lambda: NOW)
    final = utterance(source)
    token = PlannerCancellationToken()
    first = core.run(final, token, full_turn_only=True)
    assert core.run(final, token, full_turn_only=True) is first
    with pytest.raises(ValueError, match='hybrid_conflicting_replay'):
        core.run(replace(final, text=source+' altered'), token, full_turn_only=True)
    assert len(g.calls) == int(source == PURE)
    cancelled = PlannerCancellationToken(); cancelled.cancel()
    assert core.run(utterance(source), cancelled, full_turn_only=True).failure is not None
    assert len(g.calls) == int(source == PURE)


def test_host_has_one_general_entry_and_no_separate_conversation_owner():
    import inspect
    tree = ast.parse(inspect.getsource(host))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not {'ConversationVoice', 'eligible_conversation'} & names
    calls = [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert calls.count('GeneralSemanticVoice') == calls.count('general_owners[0].run') == 1


def test_exact_step1_production_scope_and_no_new_language_templates():
    """The changed file hashes are not permission to alter other runtime owners."""
    from pathlib import Path
    import subprocess
    root = Path(__file__).resolve().parents[1]
    base = 'be413a802fe4d84ac140db248219b3e450cbb8b4'
    paths = {'orion/full_voice_service.py', 'orion/hybrid_aircraft_core.py'}
    changed = set(subprocess.check_output(['git', 'diff', base, '--name-only', '--',
        'orion', 'dcs-export', 'packaging'], cwd=root).decode().splitlines())
    assert changed == paths
    assert not subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '--',
        'orion', 'dcs-export', 'packaging'], cwd=root).strip()
    for path in paths:
        before = ast.parse(subprocess.check_output(['git', 'show', base+':'+path], cwd=root).decode('utf-8'))
        after = ast.parse((root/path).read_text(encoding='utf-8'))
        def strings(tree):
            return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        assert not strings(after) - strings(before), 'New production literal / phrase policy'
        if path.endswith('full_voice_service.py'):
            class OutsideAnswer(ast.NodeTransformer):
                def visit_AsyncFunctionDef(self, node):
                    if node.name == 'answer': return None
                    return self.generic_visit(node)
                def visit_ImportFrom(self, node):
                    if node.module in {'orion.conversational_core', 'orion.conversational_presentation'}:
                        return None
                    return node
            assert ast.dump(OutsideAnswer().visit(before)) == ast.dump(OutsideAnswer().visit(after)), 'Host lifecycle changed'
        else:
            # Reverse only the routing flag and early abstention; all factual,
            # receipt, grant, replay, cancellation and old helper code is literal.
            class RemoveRoutingFlag(ast.NodeTransformer):
                removed = 0
                def visit_arguments(self, node):
                    for index in range(len(node.kwonlyargs)-1, -1, -1):
                        if node.kwonlyargs[index].arg == 'full_turn_only':
                            del node.kwonlyargs[index]; del node.kw_defaults[index]
                    return node
                def visit_Call(self, node):
                    node.keywords = [k for k in node.keywords if k.arg != 'full_turn_only']
                    return self.generic_visit(node)
                def visit_If(self, node):
                    if isinstance(node.test, ast.Name) and node.test.id == 'full_turn_only':
                        assert len(node.body) == 1 and isinstance(node.body[0], ast.Return)
                        assert node.body[0].value is not None
                        assert ast.unparse(node.body[0].value) == 'HybridResult(route)'
                        self.removed += 1
                        return None
                    return self.generic_visit(node)
            reverse = RemoveRoutingFlag()
            assert ast.dump(before) == ast.dump(reverse.visit(after)), 'Factual executor changed'
            assert reverse.removed == 1
