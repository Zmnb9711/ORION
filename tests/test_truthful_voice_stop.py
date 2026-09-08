"""Regression: STOP preserves a terminated owner's cleanup error.

Qwen cleanup itself is deliberately unchanged. A real
transport loop is blocked; only timeout expiration is injected. All blocked
resources are released by the test harness after recording STOP's result.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
import socket
import sys
import threading
import time
from types import SimpleNamespace
from typing import Any, cast

import pytest

from orion.full_voice_service import FullVoiceService
from orion.yandex_srs_live_core import YandexSrsStartRequest, YandexSrsState
import orion.yandex_qwen_planner as q
import test_yandex_qwen_planner as fixtures


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original = socket.socket.connect
    pair_code = getattr(socket.socketpair, "__code__", None)

    def denied(*args, **kwargs):
        raise AssertionError("Network forbidden in cleanup boundary test")

    def connect(sock, address):
        if pair_code is not None and sys._getframe(1).f_code is pair_code:
            return original(sock, address)
        return denied()

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket.socket, "sendto", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.mark.parametrize("stop_during_cleanup", [True, False])
@pytest.mark.parametrize("failure", ["actual_cleanup", "normalized_failure"])
def test_stop_preserves_cleanup_error_with_live_transport(
    monkeypatch, record_property, stop_during_cleanup, failure,
):
    transport: Any = q.AiohttpYandexResponsesTransport(fixtures.config())
    run = q.YandexQwenPlannerRun(
        request=fixtures.provider_request(), config=fixtures.config(),
        transport=transport, diagnostics=q.YandexPlannerDiagnostics(),
    )
    entered, release, ready = threading.Event(), threading.Event(), threading.Event()
    cleanup_errors: list[str] = []
    error_states = []
    waits: list[float] = []
    original_join = transport._thread.join
    submit = asyncio.run_coroutine_threadsafe

    def blocked_loop_callback():
        entered.set()
        release.wait()

    transport._loop.call_soon_threadsafe(blocked_loop_callback)
    assert entered.wait(2)

    class Expired:
        def result(self, timeout):
            waits.append(timeout)
            raise FutureTimeout()

        def cancel(self):
            return True

    def timeout_submit(coroutine, loop):
        # Explicit timeout primitive: no fake background coroutine is created.
        coroutine.close()
        return Expired()

    def expired_join(timeout):
        waits.append(timeout)
        original_join(0)

    class OfflineVoice(FullVoiceService):
        async def _voice(self, request, session_id, stopped):
            ready.set()
            assert await asyncio.to_thread(stopped.wait, 2)
            try:
                if failure == "normalized_failure":
                    # Model the permitted local fix's bounded failure result.
                    # Frozen _run/stop must not convert this to STOPPED either.
                    raise q.YandexPlannerTransportError(q.YandexFailureCategory.UNAVAILABLE)
                run.cancel()  # Unmodified production cleanup, including loop.close.
            except Exception as exc:
                cleanup_errors.append(type(exc).__name__)
                raise

    service = OfflineVoice()

    def owner():
        # Unmodified production exception capture/finally; no SRS/voice start.
        request = cast(YandexSrsStartRequest, SimpleNamespace(api_key="offline-placeholder"))
        service._run(request, "offline", service._stop)
        error_states.append(service.status().state)

    service._thread = threading.Thread(target=owner, name="offline-cleanup-owner")
    try:
        with monkeypatch.context() as patch:
            patch.setattr(q.asyncio, "run_coroutine_threadsafe", timeout_submit)
            patch.setattr(transport._thread, "join", expired_join)
            service._thread.start()
            assert ready.wait(2)
            if not stop_during_cleanup:
                service._stop.set()
                service._thread.join(2)
                assert not service._thread.is_alive()
                assert service.status().state is YandexSrsState.ERROR
            began = time.monotonic()
            result = service.stop()  # Corrected state propagation; same six-second bound.
            elapsed = time.monotonic() - began

        expected_error = "YandexPlannerCleanupError" if failure == "actual_cleanup" else "YandexPlannerTransportError"
        assert cleanup_errors == [expected_error]
        assert error_states == [YandexSrsState.ERROR]
        if failure == "actual_cleanup":
            assert len(waits) == 2 and all(0 <= wait <= q._CLEANUP_BUDGET_SECONDS for wait in waits)
        else:
            assert waits == []
        assert result.state is YandexSrsState.ERROR
        assert not service._thread.is_alive()
        assert transport._thread.is_alive() and transport._loop.is_running()
        assert not transport._loop.is_closed() and not run._closed
        assert result.last_error  # Failure remains externally observable.
        record_property("stop_elapsed_seconds", elapsed)
        record_property("state_before_stop", error_states[0].value)
        record_property("stop_state", result.state.value)
        record_property("cleanup_owner_alive", service._thread.is_alive())
        record_property("transport_thread_alive", transport._thread.is_alive())
        record_property("loop_running", transport._loop.is_running())
        record_property("run_closed", run._closed)
        record_property("cleanup_exception_type", cleanup_errors[0])
    finally:
        service._stop.set()
        release.set()
        # Harness rescue is not production cleanup or a proposed workaround.
        if service._thread.ident is not None:
            service._thread.join(3)
        if not transport._loop.is_closed():
            async def drained():
                pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
            # Existing close queued loop.stop before its unsafe loop.close.
            if failure == "actual_cleanup":
                original_join(2)
            if transport._thread.is_alive():
                submit(drained(), transport._loop).result(2)
                transport._loop.call_soon_threadsafe(transport._loop.stop)
                original_join(2)
            assert not transport._thread.is_alive()
            assert not transport._loop.is_running()
            transport._loop.close()
        assert not service._thread.is_alive()
