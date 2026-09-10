"""Offline timing replay: provider/user deadline is not the history barrier.

Only fake transport waits; no provider, host, DCS, SRS or thread executor.
"""
import asyncio
import threading
from types import SimpleNamespace

import pytest

from orion.conversational_contracts import ConversationCleanupError, ConversationFailure
from orion.planner import PlannerCancellationToken
from orion.yandex_warm_aircraft_interpreter import InterpreterState, WarmYandexAircraftInterpreter
from test_yandex_warm_aircraft_interpreter import A, B, Wire, req


class DelayedWire(Wire):
    def __init__(self, terminal_delay=0.0, ack_delay=0.0, mode="normal"):
        super().__init__(mode)
        self.terminal_delay, self.ack_delay = terminal_delay, ack_delay
        self.ack_count = 0
        self.deleting = asyncio.Event()

    async def send(self, value):
        if value["type"] == "conversation.item.delete":
            self.deleting.set()
        await super().send(value)

    async def receive(self):
        event = await super().receive()
        if event["type"] == "response.done":
            await asyncio.sleep(self.terminal_delay)
        if event["type"] == "conversation.item.deleted":
            self.ack_count += 1
            if self.mode == "one_ack" and self.ack_count == 2:
                await asyncio.Event().wait()
            if self.ack_count % 2:
                await asyncio.sleep(self.ack_delay)
        return event


def assert_drained(owner):
    assert not owner.owned and not owner.busy
    assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]


@pytest.mark.parametrize("delay", [.741, .869])
def test_old_global_deadline_shape_now_returns_before_ack_and_reuses_only_after_barrier(delay, monkeypatch):
    threads = set(threading.enumerate())
    clock = [0.0]
    # Patch only this owner's clock, never asyncio/shared time or production code.
    monkeypatch.setattr("orion.yandex_warm_aircraft_interpreter.time",
                        SimpleNamespace(monotonic=lambda: clock[0]))

    class ReplayWire(Wire):
        terminal_delay = delay
        ack_delay = .3
        ack_count = 0

        async def receive(self):
            event = await super().receive()
            if event["type"] == "response.done":
                clock[0] += self.terminal_delay
            if event["type"] == "conversation.item.deleted":
                self.ack_count += 1
                if self.ack_count % 2:
                    clock[0] += self.ack_delay
            return event

    async def run():
        observed = []
        wire = ReplayWire()
        owner = WarmYandexAircraftInterpreter(lambda: wire, observe=lambda e, **f: observed.append((e, f)))
        assert await owner.prepare()
        started = clock[0]
        result = await owner.interpret(req(), PlannerCancellationToken())
        returned = clock[0] - started
        assert result.intent.capability == "aircraft.identity" and delay <= returned < 1
        assert owner.state is InterpreterState.ISOLATING
        assert wire.ack_count == 0  # publication did not await cleanup at all
        next_request = req(B)
        with pytest.raises(ConversationFailure, match="not_warm"):
            await owner.interpret(next_request, PlannerCancellationToken())
        assert owner.operation_count == 1 and next_request.interaction_id not in owner.used
        await owner.wait_isolation()
        assert clock[0] - started > 1  # old operation would have failed
        assert owner.state is InterpreterState.READY
        user_metric = next(f for e, f in observed if e == "interpretation_complete")
        isolation = next(f for e, f in observed if e == "isolation_ready")
        assert user_metric["user_path_ms"] < 1000 and not user_metric["core_admission_included"]
        assert 290 <= isolation["isolation_ms"] < 500
        wire.terminal_delay = wire.ack_delay = 0
        assert (await owner.interpret(next_request, PlannerCancellationToken())).intent.capability == "not_applicable"
        await owner.wait_isolation()
        assert owner.connect_count == 1 and owner.result_count == 2
        await owner.shutdown()
        assert_drained(owner)
    asyncio.run(run())
    assert set(threading.enumerate()) == threads


def test_interpretation_over_one_second_still_fails_without_any_deletes():
    async def run():
        wire = DelayedWire(1.1)
        owner = WarmYandexAircraftInterpreter(lambda: wire)
        assert await owner.prepare()
        with pytest.raises(ConversationFailure, match="INTERPRETER_LATENCY_GATE_FAILED"):
            await owner.interpret(req(), PlannerCancellationToken())
        assert owner.result_count == 0 and not wire.deleting.is_set()
        assert wire.closed == 1
        await owner.shutdown()
        assert_drained(owner)
    asyncio.run(run())


@pytest.mark.parametrize("mode, category", [
    ("delete_stall", "ISOLATION_BARRIER_TIMEOUT"),
    ("one_ack", "ISOLATION_BARRIER_TIMEOUT"),
    ("wrong_delete", "ISOLATION_ACK_CORRELATION_FAILURE"),
])
def test_failed_barrier_does_not_revoke_result_but_prevents_all_future_operations(mode, category):
    async def run():
        wire = DelayedWire(mode=mode)
        owner = WarmYandexAircraftInterpreter(lambda: wire)
        assert await owner.prepare()
        assert (await owner.interpret(req(), PlannerCancellationToken())).intent.capability == "aircraft.identity"
        with pytest.raises(ConversationFailure, match=category):
            await owner.wait_isolation()
        assert owner.state is InterpreterState.DEGRADED and owner.last_failure == category
        with pytest.raises(ConversationFailure, match="not_warm"):
            await owner.interpret(req(B), PlannerCancellationToken())
        assert owner.result_count == owner.operation_count == wire.closed == 1
        await owner.shutdown()
        assert_drained(owner)
    asyncio.run(run())


@pytest.mark.parametrize("action", ["stop", "token", "cancel_waiter", "stop_before_task_starts"])
def test_isolation_has_explicit_owner_and_bounded_cancel_cleanup(action):
    async def run():
        wire = DelayedWire(mode="delete_stall")
        owner = WarmYandexAircraftInterpreter(lambda: wire)
        token = PlannerCancellationToken()
        assert await owner.prepare()
        await owner.interpret(req(), token)
        if action != "stop_before_task_starts":
            await wire.deleting.wait()
        if action == "token":
            token.cancel()
            with pytest.raises(ConversationFailure, match="cancelled"):
                await owner.wait_isolation()
        elif action == "cancel_waiter":
            waiter = asyncio.create_task(owner.wait_isolation())
            await asyncio.sleep(0)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert owner.state is InterpreterState.ISOLATING
            assert owner._isolation_task is not None and not owner._isolation_task.done()
        await owner.shutdown()
        assert owner.state is InterpreterState.STOPPED and wire.closed == 1
        assert owner.operation_count == owner.result_count == 1
        assert_drained(owner)
    asyncio.run(run())


def test_background_close_failure_is_retrieved_and_truthful_at_shutdown():
    class BrokenClose(DelayedWire):
        async def close(self):
            raise OSError("fixture")

    async def run():
        owner = WarmYandexAircraftInterpreter(lambda: BrokenClose(mode="wrong_delete"))
        assert await owner.prepare()
        await owner.interpret(req(), PlannerCancellationToken())
        with pytest.raises(ConversationCleanupError, match="interpreter_close_failed"):
            await owner.wait_isolation()
        with pytest.raises(ConversationCleanupError, match="interpreter_close_failed"):
            await owner.shutdown()
        assert owner.state is InterpreterState.DEGRADED
        assert_drained(owner)
    asyncio.run(run())


def test_real_fast_paths_and_separate_conversation_owner_run_while_barrier_pending():
    from orion.full_voice_core import FullVoiceCore
    from orion.yandex_realtime_text_conversation import TextConversationProvider
    from test_conversation_prerequisites import Fake, events, setup as social_setup
    from test_hybrid_aircraft import setup as aircraft_setup, utterance
    from test_interaction_router import NOW, OwnshipProvider, gateway

    async def run():
        wire = DelayedWire(mode="delete_stall")
        owner = WarmYandexAircraftInterpreter(lambda: wire)
        assert await owner.prepare()
        await owner.interpret(req(), PlannerCancellationToken())
        await wire.deleting.wait()
        core, g, p, _, u = aircraft_setup("Какой у меня самолёт?")
        assert core.run(u, PlannerCancellationToken()).finalized is not None
        assert len(g.calls) == 1 and not p.calls
        ownship_provider = OwnshipProvider()
        ownship = FullVoiceCore(gateway(), lambda: ownship_provider, clock=lambda: NOW)
        result = ownship.run(utterance("Какой мой текущий курс и координаты?"), PlannerCancellationToken())
        assert result.status == "completed" and not ownship_provider.requests
        social = "что то сегодня полет идет тяжело"
        conversation_core, request = social_setup(social)
        separate_wire = Fake(events(source=social))
        conversation = TextConversationProvider(lambda: separate_wire)
        candidate = await conversation.generate(request, PlannerCancellationToken())
        assert conversation_core.authorize(conversation_core.admit(candidate))
        assert not conversation.owned and separate_wire.closed == 1
        assert owner.state is InterpreterState.ISOLATING
        assert owner.operation_count == 1 and wire.closed == 0
        await owner.shutdown()
        assert_drained(owner)
    asyncio.run(run())
