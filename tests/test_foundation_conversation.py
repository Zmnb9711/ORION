"""Step 2 mechanism tests; generated fixtures are NOT model/physical evidence."""
import ast
import asyncio
from datetime import timedelta
from pathlib import Path
import subprocess

import pytest

from orion.general_semantic_contracts import Dialogue, SemanticProposal, provider_instructions
from orion.general_semantic_core import DialoguePlan
from orion.general_semantic_voice import GeneralSemanticVoice
from orion.planner import PlannerCancellationToken
from test_general_semantic import make


@pytest.mark.parametrize('delivery', ['completed', 'failed', 'cancelled', 'unknown'])
def test_semantics_first_delivery_correlated_and_not_replayed(delivery):
    core, hybrid, u, req, _ = make('Explain an interesting property of glass.')
    final = core.execute(u, SemanticProposal(request=req, response_id='fixture',
        result=Dialogue(kind='DIALOGUE', text='Glass is an amorphous solid.')), PlannerCancellationToken(), hybrid)
    core.context.accept(final, delivery='pending')
    semantic = core.context.project()
    entry = semantic.exchanges[-1]
    assert entry.interaction_id == u.interaction_id and entry.reply == final.text
    assert entry.semantic_understood and not entry.tts_started and not entry.user_heard
    wrong = final.model_copy(update={'text': 'A different response.'})
    core.context.update_delivery(wrong, delivery='failed')
    assert core.context.project() == semantic
    core.context.update_delivery(final, delivery=delivery, tts_started=True)
    delivered = core.context.project()
    assert delivered.revision == semantic.revision
    assert delivered.exchanges[-1].delivery == delivery
    assert delivered.exchanges[-1].reply == final.text and not delivered.exchanges[-1].user_heard
    core.context.update_delivery(final, delivery='failed')
    assert core.context.project() == delivered
    with pytest.raises(ValueError): core.context.accept(final)
    core.context.reset()
    core.context.update_delivery(final, delivery='completed')
    assert not core.context.project().exchanges


def test_late_delivery_does_not_resurrect_expired_semantics():
    core, hybrid, u, req, _ = make()
    final = core.execute(u, SemanticProposal(request=req, response_id='f',
        result=Dialogue(kind='DIALOGUE', text='Original.')), PlannerCancellationToken(), hybrid)
    core.context.accept(final, delivery='pending')
    now = core.clock()
    core.context.clock = lambda: now + timedelta(seconds=301)
    core.context.update_delivery(final, delivery='completed')
    assert not core.context.project().exchanges


@pytest.mark.parametrize('mode', ['success', 'tts_failure', 'invalid_candidate', 'stop_provider'])
@pytest.mark.parametrize('source', ['Почему лёд плавает в воде?', 'What makes a metaphor useful?'])
def test_real_host_context_before_audio_and_following_turn(monkeypatch, tmp_path, mode, source):
    import orion.full_voice_service as host
    import test_free_conversation_host as replay_module
    from dataclasses import replace
    from test_general_semantic import SemanticWire
    from test_free_conversation_host import test_normal_host_conversation_then_core_no_fallback as replay
    accepted, terminal = [], []
    sent = []
    continuation = 'Объясни подробнее именно это свойство.' if source.startswith('Почему') else 'Offer a different comparison for that.'
    monkeypatch.setattr(replay_module, 'SOCIAL', (replay_module.SOCIAL[0], continuation))
    original_utterance = replay_module.utterance
    monkeypatch.setattr(replay_module, 'utterance', lambda text: replace(original_utterance(text),
        input_language='ru-RU' if source.startswith('Почему') or text == replay_module.PURE else 'en-US'))
    original_send = SemanticWire.send
    async def send(wire, value):
        if value['type'] == 'response.create':
            sent.append(value['response']['instructions'])
        await original_send(wire, value)
    monkeypatch.setattr(SemanticWire, 'send', send)

    class Observed(GeneralSemanticVoice):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            original = self.presentation.present

            async def present(finalized, radio):
                projection = self.core.context.project(self.core.context.epoch)
                if isinstance(finalized.plan, DialoguePlan):
                    entry = projection.exchanges[-1]
                    assert entry.delivery == 'pending' and not entry.tts_started
                    assert entry.reply == finalized.text and entry.interaction_id == finalized.plan.request.interaction_id
                    assert not entry.user_heard
                    accepted.append(projection)
                else:
                    assert finalized.plan.reason == 'ADMISSION_REJECTED'
                return await original(finalized, radio)
            self.presentation.present = present

        async def run(self, *a, **kw):
            await super().run(*a, **kw)
            if self.core.context.exchanges:
                terminal.append(self.core.context.exchanges[-1])

    monkeypatch.setattr(host, 'GeneralSemanticVoice', Observed)
    replay(monkeypatch, tmp_path, mode, source)
    if mode in {'success', 'tts_failure'}:
        assert len(accepted) == 2 and len(terminal) == 2
        assert accepted[1].exchanges[0].reply == terminal[0].reply
        assert accepted[1].exchanges[-1].user == continuation
        assert terminal[0].reply in sent[1]
        assert source in sent[1]
        assert accepted[1].exchanges[0].delivery == ('failed' if mode == 'tts_failure' else 'completed')
        assert all(not entry.user_heard for entry in terminal)
    else:
        assert not accepted


def test_step2_runtime_scope_and_no_input_grammar():
    root = Path(__file__).resolve().parents[1]
    base = '4b5a46959c241eec6ef8391ee52de4da93f3dc0f'
    allowed = {f'orion/general_semantic_{part}.py' for part in ('contracts', 'core', 'voice')}
    allowed.add('orion/yandex_warm_aircraft_interpreter.py')
    step2 = '152a2f22c281fc31ab00daf99f4e171af88c05f9'
    changed = set(subprocess.check_output(['git', 'diff', base, step2, '--name-only', '--',
        'orion', 'dcs-export', 'packaging'], cwd=root).decode().splitlines())
    assert changed == allowed
    # Step 4 changes only fact admission/metadata and CapabilityGap; Step 2's
    # wire owner, voice/context lifecycle remain byte-for-byte frozen.
    frozen = {'orion/general_semantic_voice.py', 'orion/yandex_warm_aircraft_interpreter.py'}
    step4 = '31546f9f191b060571cba32998c8cf232b345506'
    assert not subprocess.check_output(['git', 'diff', step2, step4, '--', *sorted(frozen)], cwd=root)
    before_core = ast.parse(subprocess.check_output(['git', 'show', step2+':orion/general_semantic_core.py'], cwd=root).decode('utf-8'))
    after_core = ast.parse(subprocess.check_output(['git', 'show', step4+':orion/general_semantic_core.py'], cwd=root).decode('utf-8'))
    for name in ('InteractionContext', 'DialoguePlan'):
        assert ast.dump(next(n for n in before_core.body if isinstance(n, ast.ClassDef) and n.name == name)) == ast.dump(
            next(n for n in after_core.body if isinstance(n, ast.ClassDef) and n.name == name))
    for path in allowed:
        before = ast.parse(subprocess.check_output(['git', 'show', base+':'+path], cwd=root).decode('utf-8'))
        after = ast.parse((root/path).read_text(encoding='utf-8'))
        def calls(tree):
            return {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        assert not any('regex' in s or s.startswith('re.') for s in calls(after)-calls(before))
    prompt = provider_instructions()
    assert 'open conversational' in prompt and 'not predefined social classes' in prompt
    assert 'Intentional quotation' in prompt and 'CURRENT simulator state' in prompt
    assert 'usually <= 200' in prompt and 'ceiling is 400' in prompt
    for phrase in ('Почему лёд', 'metaphor', 'joke', 'social_support', 'как дела'):
        assert phrase not in prompt


def test_provider_gate_offline_exact_operations_context_and_controlled_recovery():
    from scripts.foundation_conversation_gate import CASES, evaluate
    from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter
    from test_general_semantic import SemanticWire
    import json
    wires = []
    def factory(observe):
        def transport():
            wire = SemanticWire(json.dumps({'kind': 'DIALOGUE', 'text': 'Developer generated fixture.'}))
            wires.append(wire)
            return wire
        return WarmYandexAircraftInterpreter(transport, general=True, observe=observe)
    report = asyncio.run(evaluate(factory, lambda report: None))
    assert 'failure' not in report
    assert len(report['turns']) == len(CASES) == report['operation_count'] == 10
    assert report['connect_count'] == 2 and report['owned_tasks_after_shutdown'] == 0
    assert report['turns'][8]['status'] == 'controlled_validation_failure'
    assert report['turns'][8]['recovered']
    assert report['turns'][9]['status'] == 'admitted_isolated'
    for index, turn in enumerate(report['turns']):
        assert turn['provider_operations'] == 1
        context = turn['request']['context']
        assert len(context['exchanges']) <= 2
        assert len(json.dumps(context, ensure_ascii=False, separators=(',', ':')).encode()) <= 4096
        assert bool(context['exchanges']) == (index > 0)
        assert not turn['request']['personal_context']['facts']
    assert all(wire.closed == 1 for wire in wires)
    assert not wires[-1].items  # Actual ACK-backed item deletion, not a forget prompt.
