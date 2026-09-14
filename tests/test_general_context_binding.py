"""Exact effective-context ACK before generation; no hidden-history fallback."""
import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from orion.conversational_contracts import ConversationFailure
from orion.general_semantic_contracts import ContextExchange, provider_instructions
from orion.planner import PlannerCancellationToken
from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter
from test_general_semantic import SemanticWire, make


def request():
    core, _, utterance, _, _ = make('Which invented label was assigned?')
    core.clock = lambda: datetime.now(UTC)
    core.pending.clear()
    req = core.request(utterance)
    context = req.context.model_copy(update={'exchanges': (ContextExchange(
        interaction_id=uuid4(), user='Fictional label: local-test-only.', reply='Noted.', language='en-US'),)})
    return req.model_copy(update={'context': context})


def test_exact_context_echo_before_generation_and_clear_before_ready():
    async def run():
        wire = SemanticWire('{"kind":"DIALOGUE","text":"local-test-only"}')
        owner = WarmYandexAircraftInterpreter(lambda: wire, general=True)
        assert await owner.prepare()
        for _ in range(2):
            req = request()
            await owner.interpret_general(req, PlannerCancellationToken())
            await owner.wait_isolation()
            creates = [v for v in wire.sent if v['type'] == 'response.create']
            assert creates[-1]['response']['instructions'] == provider_instructions(req.context, req.personal_context)
            index = wire.sent.index(creates[-1])
            assert wire.sent[index-2]['type'] == 'session.update'
            assert wire.sent[index-2]['session']['instructions'] == creates[-1]['response']['instructions']
            assert wire.sent[index-1]['type'] == 'conversation.item.create'
            assert 'local-test-only' not in wire.sent[index-1]['item']['content'][0]['text']
            assert wire.sent[-1]['type'] == 'session.update'
            assert wire.sent[-1]['session']['instructions'] == owner.instructions
            assert not wire.items and owner.state == 'ready'
        assert owner.operation_count == 2 and owner.connect_count == 1
        await owner.shutdown()
        assert not owner.owned
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['instructions', 'session', 'event_id', 'event_type'])
@pytest.mark.parametrize('phase', ['bind', 'clear'])
def test_bad_ack_closes_dirty_session_and_never_grants_false_ready(fault, phase):
    async def run():
        class Wire(SemanticWire):
            async def receive(self):
                event = await super().receive()
                expected = 2 if phase == 'bind' else 3
                if event.get('type') == 'session.updated' and self.session_updates == expected:
                    if fault == 'instructions': event['session']['instructions'] = 'stale'
                    if fault == 'session': event['session']['id'] = 'wrong'
                    if fault == 'event_id': event['event_id'] = ''
                    if fault == 'event_type': event['type'] = 'session.created'
                return event
        wire = Wire('{"kind":"DIALOGUE","text":"valid"}')
        owner = WarmYandexAircraftInterpreter(lambda: wire, general=True)
        # Observe the failed episode without starting an irrelevant fake recovery.
        owner._schedule_recovery = lambda fields: None
        assert await owner.prepare()
        if phase == 'bind':
            with pytest.raises(ConversationFailure): await owner.interpret_general(request(), PlannerCancellationToken())
            assert not any(v['type'] == 'response.create' for v in wire.sent)
        else:
            await owner.interpret_general(request(), PlannerCancellationToken())
            with pytest.raises(ConversationFailure): await owner.wait_isolation()
        assert wire.closed == 1 and owner.state != 'ready'
        await owner.shutdown()
        assert not owner.owned
    asyncio.run(run())


def test_context_ack_replay_rejected():
    from types import SimpleNamespace
    owner = WarmYandexAircraftInterpreter(lambda: None, general=True)
    owner.session_id = 's'
    event = {'type':'session.updated','event_id':'e','session':{'id':'s','instructions':'same'}}
    operation = SimpleNamespace(seen=set())
    owner._context_ack(event, 'same', operation)
    with pytest.raises(ConversationFailure, match='CONTEXT_ACK_REPLAY'):
        owner._context_ack(event, 'same', operation)
