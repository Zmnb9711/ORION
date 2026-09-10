"""Actual installed host seam, real warm owner, fake wire/audio only."""
import asyncio
from datetime import UTC, datetime

import pytest

from orion.aircraft_interpretation import AircraftIntent, AircraftProposal
from orion.hybrid_aircraft_contracts import HybridRoute
from orion.interaction_router import InteractionRouter
from orion.planner import PlannerCancellationToken
from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter
from test_hybrid_aircraft import Gateway, setup, utterance
from test_hybrid_host import test_gate10_normal_host_coexistence_and_single_owner as replay_host
from test_interaction_router import gateway
from test_yandex_warm_aircraft_interpreter import A, Wire


def forbidden_planner():
    raise AssertionError("Interpreter must not invoke Planner")


@pytest.mark.parametrize("source, expected, count", [
    (A, True, 1), ("Где мы сейчас?", False, 1),
    ("Какой у меня самолёт?", True, 0),
    ("Добрый день! В каком самолёте я нахожусь?", True, 0),
    ("какой мой текущий курс и координаты", True, 0),
    ("Какой это самолёт?", False, 0), ("Можно взлетать?", False, 0),
])
def test_normal_host_reuses_authoritative_tail_without_stealing_routes(monkeypatch, tmp_path, source, expected, count):
    import orion.full_voice_service as host
    owners = []

    class Configured:
        @classmethod
        def configured(cls, *args, **kwargs):
            owner = WarmYandexAircraftInterpreter(lambda: Wire(), **kwargs)
            owners.append(owner)
            return owner

    monkeypatch.setattr(host, "WarmYandexAircraftInterpreter", Configured)
    monkeypatch.setattr(Gateway, "definitions", lambda self: gateway().definitions(), raising=False)
    replay_host(monkeypatch, tmp_path, source, expected, 0, "inactive")
    assert len(owners) == 1 and owners[0].operation_count == count
    assert owners[0].state == "stopped" and not owners[0].owned


@pytest.mark.parametrize("mutation", ["none", "provider", "source", "operation", "cancel", "extra", "late"])
def test_async_core_admission_rejects_untrusted_proposal_without_facts(mutation):
    async def run():
        token = PlannerCancellationToken()
        now = [datetime.now(UTC)]
        router = InteractionRouter(provider_factory=forbidden_planner, bounded_ownship_gateway=gateway(), clock=lambda: now[0])

        class Owner:
            async def interpret(self, request, cancellation):
                result = AircraftProposal(request=request, provider_id=request.expected_provider,
                    response_id="fixture", intent=AircraftIntent(capability="aircraft.identity"))
                if mutation == "none": return result.model_copy(update={"intent": AircraftIntent(capability="not_applicable")})
                if mutation == "provider": return result.model_copy(update={"provider_id": "evil"})
                if mutation == "source": return result.model_copy(update={"request": request.model_copy(update={"source_text": "другой текст"})})
                if mutation == "operation":
                    from uuid import uuid4
                    return result.model_copy(update={"request": request.model_copy(update={"operation_id": uuid4()})})
                if mutation == "cancel": cancellation.cancel()
                if mutation == "extra":
                    return result.model_copy(update={"intent": AircraftIntent.model_construct(capability="fuel")})
                if mutation == "late": now[0] = request.deadline
                return result

        assert await router.interpret_aircraft_warm(utterance(A), Owner(), token) is None
        assert not router._aircraft_grants
    asyncio.run(run())


def test_extra_telemetry_cannot_enter_interpreted_semantics_or_presentation():
    async def run():
        def extras(data):
            data["data"]["snapshot"]["received_telemetry_set"] = {"speech": "SECRET_EXTRA_TELEMETRY", "fuel": 9876}
        core, g, _, _, u = setup(A, mutate=extras)
        assert core.run(u, PlannerCancellationToken()).route is HybridRoute.UNSUPPORTED
        router = InteractionRouter(provider_factory=forbidden_planner, bounded_ownship_gateway=gateway())
        owner = WarmYandexAircraftInterpreter(lambda: Wire())
        assert await owner.prepare()
        token = PlannerCancellationToken()
        grant = await router.interpret_aircraft_warm(u, owner, token)
        assert grant is not None and owner.state == "isolating"
        result = core.run_interpreted(u, token, grant, router)
        assert result.finalized is not None and core.authorize(result.finalized)
        assert result.finalized.text == "Вы находитесь в F/A-18C Hornet."
        assert "SECRET_EXTRA_TELEMETRY" not in result.finalized.model_dump_json()
        assert core.run_interpreted(u, token, grant, router).failure == "interpretation_admission"
        assert len(g.calls) == 1
        await owner.shutdown()
    asyncio.run(run())
