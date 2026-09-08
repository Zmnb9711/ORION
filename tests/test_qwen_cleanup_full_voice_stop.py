"""Actual FullVoiceService._voice/_run/STOP, replacing only external boundaries."""
from __future__ import annotations

import asyncio
import queue
import threading
import time
from types import SimpleNamespace as NS
from typing import Any, cast
from uuid import uuid4

import pytest

import orion.full_voice_service as host
from orion.yandex_srs_live_core import YandexSrsStartRequest, YandexSrsState
import orion.yandex_qwen_planner as q
from test_qwen_cleanup_bound import make, rescue


@pytest.mark.parametrize("mode", ["clean", "delete_stall", "noncooperative", "enclosing_limits"])
def test_actual_voice_stop_owns_cleanup(monkeypatch, mode, record_property):
    transport, session, run = make()
    run._response_ids = ["response-one"]
    session.block_delete = mode in {"delete_stall", "enclosing_limits"}
    entered, callback_entered, callback_release = (threading.Event() for _ in range(3))
    identity = uuid4()
    closed = []
    services = []

    if mode == "noncooperative":
        def blocked():
            callback_entered.set()
            callback_release.wait()
        transport._loop.call_soon_threadsafe(blocked)
        assert callback_entered.wait(2)

    class Endpoint:
        tx_frames = 0

        def __init__(self, *args):
            self.turn_events = queue.Queue()
            for kind in (host.RadioTurnEventKind.START, host.RadioTurnEventKind.END):
                self.turn_events.put(NS(kind=kind, identity=identity, timestamp=1.0))
            self.radio_router = object()

        def connect_radio(self): pass
        def start(self): pass
        def arm_physical_capture(self): pass
        def failure(self): return None
        def srs_adapter_runtime(self): return NS(bot_name="offline", coalition=2)
        def release_turn(self, identity): pass

        def stop(self):
            if mode == "enclosing_limits":
                # Deliberately exercise the frozen listener(1)+router(2) envelope.
                # This is a timing fault-injection boundary, not a production sleep.
                threading.Event().wait(3.0)
            closed.append("endpoint")

    class Native:
        owner = None
        future = None

        def __init__(self, *args, **kwargs): pass
        async def open(self, key): pass

        def start(self, turn, timestamp):
            self.owner = turn
            self.future = asyncio.get_running_loop().create_future()

        async def end(self, turn, timestamp):
            assert self.future is not None
            self.future.set_result(None)

        async def result(self):
            return NS(text="какой мой текущий курс и координаты", interaction_id=identity)

        def release(self, identity): pass

        async def close(self):
            if mode == "enclosing_limits":
                try:
                    await asyncio.wait_for(asyncio.Event().wait(), 2.0)
                except TimeoutError:
                    pass
            closed.append("native")

    class Core:
        def __init__(self, gateway): pass

        def run(self, utterance, cancellation):
            entered.set()
            assert services[0]._stop.wait(2)
            run.cancel()  # Actual planner cleanup under actual to_thread ownership.
            return NS(finalized=None, status="unsupported")

    monkeypatch.setattr(host, "NativeSpeechKitTurns", Native)
    monkeypatch.setattr(host, "GrpcSpeechKitStreamingPort", lambda: None)
    monkeypatch.setattr(host, "FullVoiceCore", Core)
    monkeypatch.setattr(host, "build_tool_gateway", lambda **kwargs: None)
    monkeypatch.setattr(host, "SrsTransportDiagnostics", lambda *args, **kwargs: None)
    monkeypatch.setattr(host, "realtime_test_evidence", NS(record_stt_core_boundary=lambda **kwargs: None))
    # Protected presentation/TTS classes and host lifecycle are NOT replaced.
    service = host.FullVoiceService(endpoint_factory=cast(Any, Endpoint))
    services.append(service)
    request = YandexSrsStartRequest.model_validate({"api_key": "offline", "folder_id": "offline",
                                                   "eam_password": "offline"})
    try:
        service.start(request)
        assert entered.wait(2)
        began = time.monotonic()
        result = service.stop()
        elapsed = time.monotonic() - began
        failed = mode == "noncooperative"
        record_property("outer_stop_seconds", elapsed)
        record_property("outer_stop_state", result.state.value)
        record_property("transport_alive_at_stop", transport._thread.is_alive())
        record_property("run_closed_at_stop", run._closed)
        record_property("session_closed_at_stop", session.closed)
        record_property("loop_closed_at_stop", transport._loop.is_closed())
        assert elapsed < 5.75  # At least 250 ms measured headroom, not noise at 6 s.
        assert result.state is (YandexSrsState.ERROR if failed else YandexSrsState.STOPPED)
        assert service._thread is not None and not service._thread.is_alive()
        assert closed == ["native", "endpoint"]
        assert transport._thread.is_alive() == failed
        assert run._closed == session.closed == transport._loop.is_closed() == (not failed)
    finally:
        service._stop.set()
        if service._thread is not None:
            service._thread.join(2)
        rescue(transport, session, (callback_release,))


@pytest.mark.parametrize("text,supported", [
    ("какой мой текущий курс и координаты", True),
    ("какой мой текущий вкус или оригинал", False),
])
def test_exact_frozen_ownship_and_corrupted_stt_remain_provider_free(text, supported):
    from test_full_voice import opened, terminal
    from test_interaction_router import gateway, NOW
    from orion.full_voice_core import FullVoiceCore
    from orion.planner import PlannerCancellationToken

    def no_provider():
        raise AssertionError("Frozen ownship must not invoke a provider")

    async def exercise():
        native, _, identity, failures = await opened()
        try:
            await native.end(identity, 1.2)
            native.accept(terminal(text=text))
            native.accept(terminal("eou_update"))
            utterance = await native.result()
            assert utterance is not None and utterance.text == text
            core = FullVoiceCore(gateway(), no_provider, clock=lambda: NOW)
            result = core.run(utterance, PlannerCancellationToken())
            assert result.status == ("completed" if supported else "unsupported")
            assert not failures
            if supported:
                assert result.finalized is not None and len(result.tool_results) == 1
                values = result.finalized.protected_fragments[0].semantic_unit.protected_values
                assert [v.value for v in values] == [137, 42.1, 41.2]
            else:
                assert result.finalized is None and not result.tool_results
        finally:
            await native.close()

    asyncio.run(exercise())
