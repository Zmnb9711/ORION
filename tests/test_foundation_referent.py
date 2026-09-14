"""Generic referent state, not a language recognizer or model-quality mock."""
from datetime import timedelta
import json
from uuid import uuid4

import pytest

from orion.general_semantic_contracts import ContextExchange, ContextProjection, provider_instructions
from orion.general_semantic_core import InteractionContext
from test_hybrid_aircraft import NOW


@pytest.mark.parametrize('language', ['ru-RU', 'en-US'])
@pytest.mark.parametrize('first_kind', ['CORE_FACT_AUTHORITATIVE', 'MIXED'])
@pytest.mark.parametrize('ids', [('synthetic.alpha', 'synthetic.beta'), ('sensor.delta', 'sensor.gamma')])
def test_latest_referent_is_derived_from_accepted_order(language, first_kind, ids):
    context = InteractionContext('generic', lambda: NOW)
    context.project()
    entries = []
    for index, capability in enumerate(ids):
        entry = ContextExchange(interaction_id=uuid4(), user='Opaque developer input',
            language=language, outcome=first_kind if index == 0 else 'CORE_FACT_AUTHORITATIVE',
            topic=capability, requested_capabilities=(capability,), core_fact_produced=True,
            reply='Non-authoritative fragment' if index == 0 and first_kind == 'MIXED' else None)
        context._append(entry)
        entries.append(entry)
    projection = context.project()
    assert projection.exchange_order == 'oldest_to_newest'
    assert projection.latest_factual_referent.interaction_id == entries[-1].interaction_id
    assert projection.latest_factual_referent.capabilities == (ids[-1],)
    assert projection.exchanges == tuple(entries)
    wire = projection.model_dump_json()
    assert ContextProjection.model_validate_json(wire) == projection
    assert 'value' not in json.loads(wire)['latest_factual_referent']
    instructions = provider_instructions(projection)
    assert 'oldest_to_newest' in instructions and 'latest_factual_referent' in instructions
    # Test only projection/contract: actual semantic understanding needs live proof.
    assert language not in instructions[:instructions.index('Explicit ORION context')]


def test_referent_reset_eviction_delivery_and_multi_fact():
    now = [NOW]
    context = InteractionContext('generic', lambda: now[0]); context.project('epoch')
    entry = ContextExchange(interaction_id=uuid4(), user='Opaque', language='en-US',
        outcome='MIXED', requested_capabilities=('synthetic.one','synthetic.two'),
        core_fact_produced=True, delivery='pending', response_fingerprint='a'*64)
    context._append(entry)
    context.record_delivery(entry.interaction_id, 'a'*64, delivery='failed')
    projected = context.project('epoch')
    assert projected.latest_factual_referent.capabilities == ('synthetic.one','synthetic.two')
    assert not projected.exchanges[-1].user_heard
    context._append(ContextExchange(user='Other topic',language='en-US'))
    assert context.project('epoch').latest_factual_referent is not None
    context._append(ContextExchange(user='Another topic',language='en-US'))
    assert context.project('epoch').latest_factual_referent is None
    context._append(entry)
    assert context.project('changed').latest_factual_referent is None
    context._append(entry); now[0] += timedelta(seconds=301)
    assert context.project('changed').latest_factual_referent is None


def test_inconsistent_or_unaccepted_referent_not_serialized():
    entry = ContextExchange(interaction_id=uuid4(),user='Opaque',language='ru-RU',
        requested_capabilities=('synthetic.new',), response_admitted=False)
    assert ContextProjection(revision=1,session_id='s',exchanges=(entry,)).latest_factual_referent is None
    with pytest.raises(ValueError):
        ContextProjection.model_validate({'revision':1,'session_id':'s','exchanges':[],
            'latest_factual_referent':{'interaction_id':str(uuid4()),'capabilities':['synthetic.old']}})


def test_bounded_gate_uses_real_context_and_one_operation_per_followup(monkeypatch):
    import asyncio
    from scripts import foundation_fact_gate as gate
    from scripts.foundation_referent_gate import CASES, PRECEDING
    from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter
    from test_general_semantic import SemanticWire
    monkeypatch.setattr(gate, 'CASES', CASES); monkeypatch.setattr(gate, 'PRECEDING', PRECEDING)
    expected = {case[1]:case[3] for case in CASES}
    class Wire(SemanticWire):
        async def send(self, value):
            if value['type'] == 'response.create':
                self.body = json.dumps({'kind':'FACT_REQUEST','capabilities':expected[self.source]})
            await super().send(value)
    report = asyncio.run(gate.evaluate(lambda observe:WarmYandexAircraftInterpreter(
        lambda:Wire(''), general=True, observe=observe), lambda report:None))
    assert report['pass'] and report['operation_count'] == 4 and report['connect_count'] == 1
    assert report['owned_tasks_after_shutdown'] == 0
    for turn in report['turns']:
        assert len(turn['preceding_offline']) == 2
        assert turn['request']['context']['latest_factual_referent']['capabilities'] == list(expected[turn['request']['source_text']])
        assert turn['core_fact_reads'] == 1
        assert turn['provider_operations'] == 1
        assert 'latest_factual_referent' in turn['provider_instructions']
