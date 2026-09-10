"""Developer fixtures only. Future physical user utterances are UNKNOWN."""
import asyncio
from datetime import timedelta
import json

import pytest

from orion.general_semantic_contracts import *
from orion.general_semantic_core import *
from orion.hybrid_aircraft_contracts import HybridRoute
from orion.hybrid_aircraft_core import HybridAircraftCore
from orion.interaction_router import InteractionRouter
from orion.planner import PlannerCancellationToken
from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter
from test_hybrid_aircraft import utterance, Gateway
from test_interaction_router import gateway, NOW
from test_yandex_warm_aircraft_interpreter import Wire
from test_conversation_prerequisites import events


def make(text="Could you describe our present coordinates?", mutate=None):
    g = Gateway(mutate)
    g.definitions = lambda: gateway().definitions()
    clock = lambda: NOW
    router = InteractionRouter(provider_factory=lambda: pytest.fail("Planner"), clock=clock)
    core = GeneralSemanticCore(g, router, "fixture-session", clock=clock)
    hybrid = HybridAircraftCore(g, lambda: pytest.fail("decomposition"), clock=clock)
    u = utterance(text)
    assert hybrid.run(u, PlannerCancellationToken()).route == HybridRoute.UNSUPPORTED
    r = core.request(u)
    return core, hybrid, u, r, g


@pytest.mark.parametrize("body", [
    '{"kind":"DIALOGUE","text":"A short original reply."}',
    '{"kind":"FACT_REQUEST","capabilities":["ownship.position","ownship.heading"]}',
    '{"kind":"CLARIFICATION","slot":"object"}',
    '{"kind":"CAPABILITY_GAP","need":"fuel"}',
    '{"kind":"REASONING_REQUEST"}', '{"kind":"DOMAIN_REQUEST"}',
])
def test_strict_union(body):
    assert parse_semantic(body) == parse_semantic("```json\n"+body+"\n```")


@pytest.mark.parametrize("body", [
    '{"kind":"DIALOGUE","kind":"DIALOGUE","text":"x"}',
    '{"kind":"FACT_REQUEST","capabilities":["ownship.heading"],"heading":271}',
    '{"kind":"FACT_REQUEST","capabilities":["fuel"]}',
    '{"kind":"FACT_REQUEST","capabilities":["ownship.position","ownship.position"]}',
    '{"kind":"DIALOGUE","text":"hi","aircraft":"Hornet"}',
    '{"kind":"DIALOGUE","text":"hi","tool_calls":[{}]}',
    '{"kind":"DIALOGUE","text":"hi"} {}', 'prefix {"kind":"DOMAIN_REQUEST"}',
    '{"kind":"UNKNOWN"}', '{"kind":"FACT_REQUEST","capabilities":[]}',
])
def test_malformed_and_value_injection_rejected(body):
    with pytest.raises(ValueError): parse_semantic(body)


@pytest.mark.parametrize("caps,count", [(('ownship.position',),2), (('ownship.heading',),1),
    (('ownship.position','ownship.heading'),3), (('aircraft.identity',),0)])
def test_selected_facts_and_single_read(caps, count):
    core, hybrid, u, request, g = make()
    proposal = SemanticProposal(request=request, response_id="fixture", result=FactRequest(kind="FACT_REQUEST", capabilities=caps))
    out = core.execute(u, proposal, PlannerCancellationToken(), hybrid)
    assert isinstance(out.plan, FactPlan) and len(out.plan.facts) == count
    assert len(g.calls) == 1 and core.authorize(out)
    assert "fuel" not in out.model_dump_json() and "altitude" not in out.model_dump_json()
    if caps == ('aircraft.identity',): assert out.text == "Вы находитесь в F/A-18C Hornet."


@pytest.mark.parametrize("kind", [Dialogue(kind="DIALOGUE", text="A natural opinion without flight measurements."),
    Clarification(kind="CLARIFICATION", slot="reference"), CapabilityGap(kind="CAPABILITY_GAP", need="weather"),
    Reasoning(kind="REASONING_REQUEST"), DomainRequest(kind="DOMAIN_REQUEST")])
def test_nonfact_roles_never_read(kind):
    core, hybrid, u, r, g = make()
    out = core.execute(u, SemanticProposal(request=r, response_id="x", result=kind), PlannerCancellationToken(), hybrid)
    assert out.text and core.authorize(out) and not g.calls
    core.context.accept(out)
    with pytest.raises(ValueError): core.context.accept(out)


@pytest.mark.parametrize("mutation", ["hash", "turn", "context", "catalog", "cancel", "late", "replay"])
def test_admission_binding(mutation):
    from uuid import uuid4
    core, hybrid, u, r, g = make()
    token = PlannerCancellationToken()
    p = SemanticProposal(request=r, response_id="x", result=FactRequest(kind="FACT_REQUEST", capabilities=("ownship.heading",)))
    if mutation == "hash": p = p.model_copy(update={"request":r.model_copy(update={"source_sha256":"f"*64})})
    if mutation == "turn": p = p.model_copy(update={"request":r.model_copy(update={"interaction_id":uuid4()})})
    if mutation == "catalog": p = p.model_copy(update={"request":r.model_copy(update={"catalog_version":"wrong"})})
    if mutation == "context": core.context.reset()
    if mutation == "cancel": token.cancel()
    if mutation == "late": core.router._clock = lambda: NOW+timedelta(seconds=2)
    if mutation == "replay":
        core.execute(u,p,token,hybrid)
        g.calls.clear()
    with pytest.raises(ValueError): core.execute(u,p,token,hybrid)
    assert not g.calls


def test_extra_source_fields_do_not_enter_plan_or_context():
    def extra(value):
        value["data"]["snapshot"]["telemetry_dump"] = {"secret":"UNSELECTED_SENTINEL"}
    core, hybrid, u, r, g = make(mutate=extra)
    out = core.execute(u, SemanticProposal(request=r,response_id="x",result=FactRequest(kind="FACT_REQUEST",capabilities=("ownship.position",))), PlannerCancellationToken(),hybrid)
    core.context.accept(out)
    assert "UNSELECTED_SENTINEL" not in out.model_dump_json()+core.context.project().model_dump_json()
    assert out.text not in provider_instructions(core.context.project())


def test_context_bounds_expiry_epoch_reset():
    now=[NOW]
    c=InteractionContext("s",lambda:now[0])
    first=c.project("epoch-a")
    assert c.project("epoch-a")==first
    assert c.project("epoch-b").revision > first.revision
    rev=c.revision
    now[0]+=timedelta(seconds=301)
    assert c.project("epoch-b").revision>rev


class SemanticWire(Wire):
    def __init__(self, body):
        super().__init__()
        self.body=body
    async def send(self,value):
        if value['type']!='response.create':
            return await super().send(value)
        self.sent.append(value)
        data=events("placeholder",source=self.source)[2:]
        for e in data:
            if e['type']=='response.output_text.delta': e['delta']=''
            if e['type']=='response.output_text.done': e['text']=self.body
            if e['type']=='response.done': e['response']['output'][0]['content'][0]['text']=self.body
        data[3]['delta']=self.body
        self.items.update(('user-one','item-one'))
        for e in data: self.queue.put_nowait(e)


def test_one_operation_general_wire_and_isolation():
    async def run():
        wire=SemanticWire('{"kind":"DIALOGUE","text":"Рад продолжить разговор."}')
        owner=WarmYandexAircraftInterpreter(lambda:wire)
        assert await owner.prepare()
        for _ in range(2):
            core,_,u,_,_=make()
            core.clock=lambda:datetime.now(UTC)
            core.pending.clear()
            req=core.request(u)
            out=await owner.interpret_general(req,PlannerCancellationToken())
            assert isinstance(out.result,Dialogue)
            await owner.wait_isolation()
            assert not wire.items
        assert owner.operation_count==2 and wire.connected==1
        await owner.shutdown()
    asyncio.run(run())
