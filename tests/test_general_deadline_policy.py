"""Bounded context ACK != generation budget != product latency target."""
import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import time

import pytest

from orion.conversational_contracts import ConversationFailure
from orion.general_semantic_contracts import FactRequest, SemanticProposal
from orion.planner import PlannerCancellationToken
from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter
from test_general_semantic import SemanticWire, make

BODY = '{"kind":"FACT_REQUEST","capabilities":["ownship.heading"]}'


def request():
    core, _, u, _, _ = make()
    core.clock = lambda: datetime.now(UTC); core.pending.clear()
    return core.request(u)


def test_ack_plus_original_generation_budget_and_visible_latency_debt(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr('orion.yandex_warm_aircraft_interpreter.time', SimpleNamespace(monotonic=lambda:clock[0]))
    class Wire(SemanticWire):
        async def receive(self):
            e = await super().receive()
            if e['type']=='session.updated' and self.session_updates==2: clock[0] += .3
            if e['type']=='response.done': clock[0] += .85
            return e
    async def run():
        observed=[]; owner=WarmYandexAircraftInterpreter(lambda:Wire(BODY),general=True,
            observe=lambda e,**f:observed.append((e,f)))
        assert await owner.prepare()
        result=await owner.interpret_general(request(),PlannerCancellationToken())
        assert result.result.capabilities==('ownship.heading',)
        terminal=next(f for e,f in observed if e=='text_terminal')
        assert terminal['terminal_ms']==pytest.approx(1150)
        assert terminal['generation_ms']==pytest.approx(850)
        assert next(f for e,f in observed if e=='interpretation_complete')['latency_target_exceeded']
        await owner.wait_isolation(); await owner.shutdown()
        assert not owner.owned
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['no_terminal','partial_terminal','no_ack','cancel'])
def test_bounded_failure_and_next_turn_without_retry(fault):
    class Wire(SemanticWire):
        async def receive(self):
            e=await super().receive()
            if (fault=='no_ack' and e['type']=='session.updated' and self.session_updates==2
                or fault in {'no_terminal','cancel'} and e['type']=='response.created'
                or fault=='partial_terminal' and e['type']=='response.output_text.done'):
                await asyncio.Event().wait()
            return e
    async def run():
        ports=[Wire(BODY),SemanticWire(BODY)]
        owner=WarmYandexAircraftInterpreter(lambda:ports.pop(0),general=True)
        assert await owner.prepare()
        token=PlannerCancellationToken(); req=request()
        if fault=='cancel': asyncio.get_running_loop().call_later(.05,token.cancel)
        began=time.monotonic()
        expected='cancelled' if fault=='cancel' else 'SEMANTIC_CONTEXT_BIND_TIMEOUT' if fault=='no_ack' else 'SEMANTIC_OPERATION_TIMEOUT'
        with pytest.raises(ConversationFailure,match=expected): await owner.interpret_general(req,token)
        assert time.monotonic()-began < (1.0 if fault=='no_ack' else 2.0)
        assert owner.operation_count==1 and owner.result_count==0
        if fault!='cancel':
            assert await owner.wait_recovery()
            with pytest.raises(ConversationFailure,match='binding'): await owner.interpret_general(req,PlannerCancellationToken())
            await owner.interpret_general(request(),PlannerCancellationToken())
            await owner.wait_isolation()
            assert owner.operation_count==2 and owner.result_count==1 and owner.connect_count==2
        await owner.shutdown(); assert not owner.owned
    asyncio.run(run())


@pytest.mark.parametrize('seconds,accepted', [(1.2,True),(1.49,True),(1.51,False)])
def test_core_short_admission_matches_bounded_total(seconds,accepted):
    core,_,_,req,_=make()
    core.router._clock=lambda:req.created_at+timedelta(seconds=seconds)
    proposal=SemanticProposal(request=req,response_id='offline',
        result=FactRequest(kind='FACT_REQUEST',capabilities=('ownship.heading',)))
    if accepted:
        assert core.router.admit_general(req,proposal,PlannerCancellationToken(),context_revision=req.context.revision)
    else:
        with pytest.raises(ValueError,match='semantic_admission_rejected'):
            core.router.admit_general(req,proposal,PlannerCancellationToken(),context_revision=req.context.revision)
