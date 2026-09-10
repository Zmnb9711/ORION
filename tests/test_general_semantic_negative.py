"""Selected-fact quality, explicit context and general-role deadline replay."""
import asyncio
from datetime import UTC, datetime, timedelta
import json

import pytest

from orion.conversational_contracts import ConversationFailure
from orion.general_semantic_contracts import Dialogue, FactRequest, SemanticProposal
from orion.general_semantic_core import FactPlan, UnavailablePlan
from orion.planner import PlannerCancellationToken
from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter
from test_general_semantic import make, SemanticWire
from test_hybrid_aircraft import utterance
from test_interaction_router import NOW


@pytest.mark.parametrize("cap,leaf", [("ownship.position","position"),("ownship.heading","heading_deg")])
@pytest.mark.parametrize("mode", ["missing","source","authority","generation","age","future","unit",
    "receipt_actor","receipt_session","receipt_turn","receipt_tool","receipt_status","provenance","range"])
def test_fact_quality_rejects_before_presentation(cap, leaf, mode):
    def mutate(value):
        snapshot=value['data']['snapshot']; fact=snapshot[leaf]
        if mode=='missing': del snapshot[leaf]
        if mode=='source': fact['source']='mission_store'
        if mode=='authority': fact['authority']='derived'
        if mode=='generation': fact['generation']='other-generation'
        if mode=='age': fact['age_seconds']=10
        if mode=='future': fact['observed_at']=(NOW+timedelta(seconds=1)).isoformat()
        if mode=='unit': fact['unit']='rad'
        if mode=='receipt_actor': value['receipt']['actor_id']='other'
        if mode=='receipt_session': value['receipt']['session_id']='other'
        if mode=='receipt_turn': value['receipt']['turn_id']='other'
        if mode=='receipt_tool': value['receipt']['tool_name']='orion.other'
        if mode=='receipt_status': value['receipt']['handler_started']=False
        if mode=='provenance': value['provenance']['generations']=[]
        if mode=='range':
            if leaf=='position': fact['value']['latitude']=91
            else: fact['value']=360
    core,hybrid,u,r,g=make(mutate=mutate)
    with pytest.raises(ValueError):
        core.execute(u,SemanticProposal(request=r,response_id='x',result=FactRequest(kind='FACT_REQUEST',capabilities=(cap,))),PlannerCancellationToken(),hybrid)
    assert not core.completed and not core.context.exchanges


@pytest.mark.parametrize("cap,leaf", [("ownship.position","position"),("ownship.heading","heading_deg")])
@pytest.mark.parametrize("status,reason", [('unknown','FACT_UNKNOWN'),('stale','FACT_STALE'),
    ('unavailable','SOURCE_UNAVAILABLE'),('restricted','RESTRICTED')])
def test_nonknown_never_speaks_value(cap,leaf,status,reason):
    def mutate(value):
        fact=value['data']['snapshot'][leaf]
        fact['status']=status; fact['reason']='source_stale' if status=='stale' else 'value_not_exported'
        if status!='stale': fact['value']=None
        value['provenance']['fact_statuses'].append(status)
    core,hybrid,u,r,g=make(mutate=mutate)
    out=core.execute(u,SemanticProposal(request=r,response_id='x',result=FactRequest(kind='FACT_REQUEST',capabilities=(cap,))),PlannerCancellationToken(),hybrid)
    assert isinstance(out.plan,UnavailablePlan) and out.plan.reason==reason
    assert 'fact_value' not in out.model_dump_json() and len(g.calls)==1


def test_cancel_during_read_and_catalog_mismatch_do_not_finalize():
    for mismatch in (False,True):
        core,hybrid,u,r,g=make(); token=PlannerCancellationToken()
        if mismatch: g.definitions=lambda:[]
        else: g.action=token.cancel
        with pytest.raises(ValueError):
            core.execute(u,SemanticProposal(request=r,response_id='x',result=FactRequest(kind='FACT_REQUEST',capabilities=('ownship.heading',))),token,hybrid)
        assert not core.completed
        assert len(g.calls)==int(not mismatch)


def test_context_is_explicit_bounded_and_facts_are_reread():
    core,hybrid,u,r,g=make()
    for index in range(4):
        if index:
            u=utterance('And what about it now?')
            hybrid.run(u,PlannerCancellationToken()); r=core.request(u)
        out=core.execute(u,SemanticProposal(request=r,response_id='x',result=FactRequest(kind='FACT_REQUEST',capabilities=('ownship.heading',))),PlannerCancellationToken(),hybrid)
        assert isinstance(out.plan,FactPlan)
        core.context.accept(out)
        projection=core.context.project()
        assert len(projection.exchanges)==min(index+1,2)
        assert all(e.reply is None and e.topic=='ownship.heading' for e in projection.exchanges)
        assert len(projection.model_dump_json().encode())<=4096
    assert len(g.calls)==4
    core.context.reset('new-mission')
    assert not core.context.exchanges


@pytest.mark.parametrize('body,delay,ok', [
    ('{"kind":"DIALOGUE","text":"A complete response longer than the selector budget."}',1.1,True),
    ('{"kind":"FACT_REQUEST","capabilities":["ownship.heading"]}',1.1,False),
    ('{"kind":"DIALOGUE","kind":"FACT_REQUEST","capabilities":["ownship.heading"]}',1.1,False),
])
def test_dialogue_terminal_budget_is_distinct_and_cannot_relax_fact_admission(body,delay,ok):
    class Delayed(SemanticWire):
        async def receive(self):
            event=await super().receive()
            if event['type']=='response.done': await asyncio.sleep(delay)
            return event
    async def run():
        core,_,u,_,_=make(); core.clock=lambda:datetime.now(UTC); core.pending.clear()
        wire=Delayed(body); owner=WarmYandexAircraftInterpreter(lambda:wire,general=True)
        assert await owner.prepare()
        if ok:
            result=await owner.interpret_general(core.request(u),PlannerCancellationToken())
            assert isinstance(result.result,Dialogue)
            await owner.wait_isolation()
        else:
            with pytest.raises((ValueError,ConversationFailure)):
                await owner.interpret_general(core.request(u),PlannerCancellationToken())
        await owner.shutdown()
        assert not owner.owned and wire.closed==1
    asyncio.run(run())


def test_explicit_context_sent_not_retained_provider_items():
    async def run():
        body=json.dumps({'kind':'DIALOGUE','text':'NON_AUTHORITATIVE_CONTEXT_SENTINEL'})
        wire=SemanticWire(body); owner=WarmYandexAircraftInterpreter(lambda:wire,general=True)
        assert await owner.prepare()
        core,hybrid,u,_,_=make(); core.clock=core.router._clock=lambda:datetime.now(UTC)
        core.context.clock=core.clock; core.pending.clear()
        for i in range(2):
            if i: u=utterance('Continue that thought, please.')
            request=core.request(u)
            proposal=await owner.interpret_general(request,PlannerCancellationToken())
            result=core.execute(u,proposal,PlannerCancellationToken(),hybrid)
            core.context.accept(result)
            await owner.wait_isolation()
            assert not wire.items
        sent=[e['response']['instructions'] for e in wire.sent if e['type']=='response.create']
        assert 'NON_AUTHORITATIVE_CONTEXT_SENTINEL' not in sent[0]
        assert 'NON_AUTHORITATIVE_CONTEXT_SENTINEL' in sent[1]
        await owner.shutdown()
    asyncio.run(run())
