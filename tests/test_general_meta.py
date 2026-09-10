"""Developer semantic fixtures prove execution boundaries, not model accuracy."""
import asyncio
from dataclasses import replace
import json
from types import MappingProxyType
from uuid import uuid4

import pytest

from orion.general_semantic_contracts import MetaRequest, SemanticProposal, parse_semantic, provider_instructions
from orion.general_semantic_core import FactPlan, MetaPlan, SUMMARY_CAPABILITIES
from orion.general_fact_registry import CATALOG
from orion.general_fact_presentation import LABELS
from orion.planner import PlannerCancellationToken
from test_general_fact_registry import fixture, execute
from test_general_semantic import make, SemanticWire


MATRIX = [
    ("Share a thought about patience.", {"kind":"DIALOGUE","text":"Patience leaves room to reconsider."}, 0),
    ("What can early gliders teach an engineer?", {"kind":"DIALOGUE","text":"They illustrate the balance between lift and drag."}, 0),
    ("Представься как помощник.", {"kind":"META_REQUEST","topic":"identity"}, 0),
    ("Какие сведения об авиамашине входят в твой нынешний набор функций?", {"kind":"META_REQUEST","topic":"capabilities"}, 0),
    ("Объясни, чем ты способен помочь мне в этой программе.", {"kind":"META_REQUEST","topic":"help"}, 0),
    ("Determine the heading of the aircraft I control.", {"kind":"FACT_REQUEST","capabilities":["ownship.heading"]}, 1),
    ("State our current pitch and altitude above sea level.", {"kind":"FACT_REQUEST","capabilities":["ownship.pitch","ownship.altitude_msl"]}, 1),
    ("Дай краткую картину текущего состояния машины.", {"kind":"STATE_SUMMARY"}, 1),
    ("Сообщи остаток горючего в моём самолёте.", {"kind":"CAPABILITY_GAP","need":"fuel"}, 0),
    ("Tell me about that one.", {"kind":"CLARIFICATION","slot":"reference"}, 0),
]


@pytest.mark.parametrize("source,body,reads", MATRIX)
def test_typed_semantic_matrix_executes_only_selected_role(source, body, reads):
    core, hybrid, u, _, gateway, _ = fixture()
    u = replace(u, interaction_id=uuid4(), text=source)
    request = core.request(u)
    out = core.execute(u, SemanticProposal(request=request, response_id="fixture", result=parse_semantic(json.dumps(body))),
                       PlannerCancellationToken(), hybrid)
    assert len(gateway.calls) == reads and core.read_count == reads and core.authorize(out)
    if body["kind"] == "META_REQUEST":
        assert isinstance(out.plan, MetaPlan)
        assert not any(value in out.text for value in ("103.74", "1234.56", "42.123456", "fuel"))
    core.context.accept(out)


@pytest.mark.parametrize("topic", ["capabilities", "identity", "help"])
def test_meta_has_no_dependency_on_gateway_or_telemetry(topic):
    core, hybrid, u, request, gateway = make()
    gateway.definitions = gateway.execute = lambda *args: pytest.fail("META must not touch Gateway")
    out = core.execute(u, SemanticProposal(request=request, response_id="fixture",
        result=MetaRequest(kind="META_REQUEST", topic=topic)), PlannerCancellationToken(), hybrid)
    assert isinstance(out.plan, MetaPlan) and core.read_count == 0 and len(out.text) <= 400
    if topic != "identity":
        assert out.plan.capabilities == tuple(item.capability for item in CATALOG)
        for item in CATALOG:
            assert LABELS[item.presentation].lower() in out.text
    core.context.accept(out)
    context = core.context.project()
    assert context.exchanges[-1].topic == "meta."+topic
    assert context.exchanges[-1].described_capabilities == out.plan.capabilities
    assert context.exchanges[-1].reply is None and not context.exchanges[-1].core_fact_produced
    assert "103.74" not in provider_instructions(context)


@pytest.mark.parametrize("extra", [{"text":"invented abilities"}, {"capabilities":["ownship.heading"]},
                                 {"tool":"anything"}, {"values":{"heading":5}}])
def test_meta_cannot_carry_provider_capability_truth_or_execution(extra):
    with pytest.raises(ValueError):
        parse_semantic(json.dumps({"kind":"META_REQUEST","topic":"capabilities",**extra}))


def test_summary_does_not_grow_with_registry_and_explicit_multi_still_works(monkeypatch):
    import orion.general_semantic_core as module
    import orion.general_fact_registry as registry
    added = registry.CATALOG[2].model_copy(update={"capability":"ownship.test_extension"})
    monkeypatch.setattr(module, "CATALOG", (*CATALOG, added))
    monkeypatch.setattr(registry, "REGISTRY", MappingProxyType({**registry.REGISTRY, added.capability:added}))
    out = execute(fixture(), summary=True)
    assert isinstance(out.plan, FactPlan) and set(out.plan.capabilities) == set(SUMMARY_CAPABILITIES)
    assert added.capability not in out.plan.capabilities
    multi = execute(fixture(), [item.capability for item in CATALOG])
    assert len(multi.plan.capabilities) == 7 and not multi.plan.summary


def test_meta_description_tracks_registry_without_independent_list(monkeypatch):
    import orion.general_semantic_core as module
    monkeypatch.setattr(module, "CATALOG", CATALOG[:2])
    core, hybrid, u, req, _ = make()
    out = core.execute(u, SemanticProposal(request=req, response_id="fixture",
        result=MetaRequest(kind="META_REQUEST", topic="capabilities")), PlannerCancellationToken(), hybrid)
    assert out.plan.capabilities == tuple(item.capability for item in CATALOG[:2])
    assert "координаты" in out.text and "высота" not in out.text and "тангажа" not in out.text
    assert not core.authorize(out.model_copy(update={"text":out.text+" invented"}))


def test_meta_growth_is_bounded_and_declared(monkeypatch):
    import orion.general_semantic_core as module
    import orion.general_fact_registry as registry
    extra = tuple(CATALOG[2].model_copy(update={"capability":f"ownship.extension{i}"}) for i in range(4))
    monkeypatch.setattr(module, "CATALOG", (*CATALOG, *extra))
    monkeypatch.setattr(registry, "REGISTRY", MappingProxyType({**registry.REGISTRY, **{d.capability:d for d in extra}}))
    core, hybrid, u, req, _ = make()
    out = core.execute(u, SemanticProposal(request=req, response_id="fixture",
        result=MetaRequest(kind="META_REQUEST", topic="capabilities")), PlannerCancellationToken(), hybrid)
    assert len(out.plan.capabilities) == 8 and out.plan.additional_categories
    assert "часть категорий" in out.text


def test_meta_context_reaches_same_semantic_owner_for_followup(monkeypatch):
    from datetime import datetime
    import orion.yandex_warm_aircraft_interpreter as module
    from test_interaction_router import NOW
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return NOW
    monkeypatch.setattr(module, "datetime", Clock)
    from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter
    async def run():
        core, hybrid, u, req, g = make()
        wire = SemanticWire('{"kind":"META_REQUEST","topic":"capabilities"}')
        owner = WarmYandexAircraftInterpreter(lambda:wire, general=True)
        assert await owner.prepare()
        try:
            proposal = await owner.interpret_general(req, PlannerCancellationToken())
            out = core.execute(u, proposal, PlannerCancellationToken(), hybrid)
            core.context.accept(out)
            await owner.wait_isolation()
            follow = replace(u, interaction_id=uuid4(), text="Тогда сообщи текущее значение курса.")
            next_req = core.request(follow)
            wire.body = '{"kind":"FACT_REQUEST","capabilities":["ownship.heading"]}'
            next_proposal = await owner.interpret_general(next_req, PlannerCancellationToken())
            result = core.execute(follow, next_proposal, PlannerCancellationToken(), hybrid)
            assert isinstance(result.plan, FactPlan) and len(g.calls) == 1
            assert next_req.context.exchanges[-1].outcome == "CORE_CAPABILITY_METADATA"
            sent = json.dumps(wire.sent, ensure_ascii=False)
            assert "described_capabilities" in sent and "meta.capabilities" in sent
            assert owner.operation_count == 2 and owner.connect_count == 1
        finally:
            await owner.shutdown()
        assert not owner.owned
    asyncio.run(run())


def test_instructions_describe_boundaries_without_fixture_sentences():
    prompt = provider_instructions()
    assert "META_REQUEST" in prompt and "NOT permission to execute reads" in prompt
    assert "Never enumerate the catalog for an overview" in prompt
    assert all(text not in prompt for text, _, _ in MATRIX)
    assert "Что тебе сейчас доступно из возможностей чтения данных?" not in prompt


@pytest.mark.parametrize("topic", ["capabilities", "identity", "help"])
def test_normal_host_meta_exact_presentation_and_zero_reads(monkeypatch, tmp_path, topic):
    import orion.full_voice_service as host
    from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter
    from test_hybrid_host import test_gate10_normal_host_coexistence_and_single_owner as replay
    from test_hybrid_aircraft import Gateway
    from test_interaction_router import gateway
    owners = []
    class Configured:
        @classmethod
        def configured(cls, *args, **kwargs):
            owner = WarmYandexAircraftInterpreter(lambda:SemanticWire(json.dumps({"kind":"META_REQUEST","topic":topic})), **kwargs)
            owners.append(owner)
            return owner
    monkeypatch.setattr(host, "WarmYandexAircraftInterpreter", Configured)
    monkeypatch.setattr(Gateway, "definitions", lambda self:gateway().definitions(), raising=False)
    captured = []
    replay(monkeypatch, tmp_path, "Describe the scope of your assistance.", True, 0, "active",
           general_kind="CORE_CAPABILITY_METADATA", expected_reads=0, capture=captured)
    assert owners[0].operation_count == 1 and not owners[0].owned
    assert captured[0]["tx_count"] == 1 and not captured[0]["calls"]
