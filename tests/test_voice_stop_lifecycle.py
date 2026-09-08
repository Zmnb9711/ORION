"""Deterministic terminal-state, restart and stale STOP race tests; no voice I/O."""
from __future__ import annotations

import threading

import pytest
from pydantic import SecretStr

from orion.full_voice_service import FullVoiceService
from orion.yandex_srs_live_core import YandexSrsStartRequest, YandexSrsState
from orion.realtime_live_core import RealtimeLiveCoordinator, _YandexSrsLiveAdapter, RealtimeLiveStartRequest
from orion.realtime_session_control import RealtimeSessionController


def request():
    return YandexSrsStartRequest(api_key="offline-placeholder", folder_id="offline",
                                eam_password=SecretStr("offline-placeholder"))


class ControlledVoice(FullVoiceService):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.fatal = False

    async def _voice(self, request, session_id, stopped):
        self.entered.set()
        assert self.release.wait(3), "harness did not release service"
        if self.fatal:
            raise RuntimeError("offline_fatal_not_cleanup_specific")


@pytest.mark.parametrize("fatal", [False, True])
@pytest.mark.parametrize("during_join", [False, True])
def test_completion_error_visibility_and_repeated_stop(monkeypatch, fatal, during_join):
    service = ControlledVoice()
    service.fatal = fatal
    started = service.start(request())
    thread = service._thread
    assert thread is not None
    join = thread.join
    waits = []
    expected = YandexSrsState.ERROR if fatal else YandexSrsState.STOPPED
    try:
        assert service.entered.wait(2)
        if during_join:
            def release_on_join(timeout):
                waits.append(timeout)
                service.release.set()
                join(timeout)
            monkeypatch.setattr(thread, "join", release_on_join)
        else:
            service.release.set()
            join(2)
            assert service.status().state is expected
        result = service.stop()
        assert result.state is expected
        assert not thread.is_alive()
        assert waits == ([6.0] if during_join else [])
        assert result.session_id == started.session_id
        assert result.model_dump() == service.stop().model_dump()
        assert result.model_dump().keys() == started.model_dump().keys()
        assert bool(result.last_error) == fatal
        if fatal:
            assert result.phase == "error" and result.message == "Yandex SRS voice failed"
        else:
            assert result.phase == "idle" and result.message == "Yandex SRS voice stopped"
        # status()/stop() return copies, not writable aliases into the service.
        result.state = YandexSrsState.STARTING
        assert service.status().state is expected
    finally:
        service.release.set()
        join(2)
        assert not thread.is_alive()


def test_idle_stop_public_shape_and_idempotence():
    service = ControlledVoice()
    before = service.status()
    first, second = service.stop(), service.stop()
    assert first.state is YandexSrsState.STOPPED
    assert first.model_dump() == second.model_dump()
    assert before.model_dump().keys() == first.model_dump().keys()
    assert service._thread is None


def test_timeout_bound_unchanged_and_error_survives_later_exit(monkeypatch):
    service = ControlledVoice()
    service.start(request())
    thread = service._thread
    assert thread is not None
    join = thread.join
    waits = []

    def expire(timeout):
        waits.append(timeout)
        join(0)

    try:
        assert service.entered.wait(2)
        monkeypatch.setattr(thread, "join", expire)
        result = service.stop()
        assert waits == [6.0] and thread.is_alive()
        assert result.state is YandexSrsState.ERROR
        assert result.last_error == "Yandex SRS shutdown exceeded its bound"
        service.release.set()
        join(2)
        assert not thread.is_alive()
        assert service.stop().model_dump() == result.model_dump()
    finally:
        service.release.set()
        join(2)


def test_restart_after_error_resets_session_but_rejects_live_owner():
    service = ControlledVoice()
    service.fatal = True
    first = service.start(request())
    thread = service._thread
    assert thread is not None
    try:
        assert service.entered.wait(2)
        with pytest.raises(ValueError, match="already running"):
            service.start(request())
        service.release.set()
        thread.join(2)
        assert service.status().state is YandexSrsState.ERROR
        service.fatal = False
        service.entered.clear()
        service.release.clear()
        second = service.start(request())  # Existing direct service restart policy.
        assert second.session_id != first.session_id
        assert second.last_error is None and second.state is YandexSrsState.STARTING
        assert service.entered.wait(2)
        service.release.set()
        assert service.stop().state is YandexSrsState.STOPPED
    finally:
        service.release.set()
        if service._thread is not None:
            service._thread.join(2)


@pytest.mark.parametrize("old_fatal", [False, True])
def test_stale_stop_cannot_overwrite_new_session(monkeypatch, old_fatal):
    service = ControlledVoice()
    service.fatal = old_fatal
    old = service.start(request())
    old_thread = service._thread
    assert old_thread is not None
    join = old_thread.join
    joined, resume = threading.Event(), threading.Event()
    results, failures = [], []

    def join_then_pause(timeout):
        service.release.set()
        join(timeout)
        assert not old_thread.is_alive()
        joined.set()
        assert resume.wait(3)

    def stop_old():
        try:
            results.append(service.stop())
        except BaseException as exc:
            failures.append(exc)

    stopper = threading.Thread(target=stop_old)
    try:
        assert service.entered.wait(2)
        monkeypatch.setattr(old_thread, "join", join_then_pause)
        stopper.start()
        assert joined.wait(2)
        service.release.clear()
        service.entered.clear()
        service.fatal = False
        new = service.start(request())
        assert new.session_id != old.session_id
        assert service.entered.wait(2)
        resume.set()
        stopper.join(2)
        assert not stopper.is_alive() and not failures
        assert service.status().model_dump() == new.model_dump()
        assert results[0].model_dump() == new.model_dump()
        assert not service._stop.is_set()
        assert service._thread is not None and service._thread.is_alive()
    finally:
        resume.set()
        service.release.set()
        if stopper.ident is not None:
            stopper.join(2)
        join(2)
        if service._thread is not None:
            service._thread.join(2)


def test_coordinator_normalization_release_and_restart_remain_existing(monkeypatch):
    service = ControlledVoice()
    service.fatal = True
    monkeypatch.setattr("orion.full_voice_service.full_voice_service", service)
    coordinator = RealtimeLiveCoordinator([_YandexSrsLiveAdapter()])
    start = RealtimeLiveStartRequest.model_validate({
        "provider": "yandex", "transport": "srs", "api_key": "offline-placeholder",
        "folder_id": "offline", "srs": {"eam_password": "offline-placeholder"},
    })
    try:
        coordinator.start(start)
        assert service.entered.wait(2)
        service.release.set()
        assert service._thread is not None
        service._thread.join(2)
        assert coordinator.status().state == "error"
        with pytest.raises(ValueError, match="Stop errored"):
            coordinator.start(start)
        assert coordinator.stop().state == "error"
        # Existing coordinator releases selection after STOP, even on ERROR.
        assert coordinator._active_selection is None
        assert coordinator.status().state == "stopped"
        assert service.status().state is YandexSrsState.ERROR
        service.fatal = False
        service.release.clear()
        service.entered.clear()
        coordinator.start(start)
        assert service.entered.wait(2)
        assert service.status().last_error is None
        service.release.set()
        assert coordinator.stop().state == "stopped"
    finally:
        service.release.set()
        if service._thread is not None:
            service._thread.join(2)


def test_session_controller_returns_error_without_reinterpreting_it():
    def core_json(path, **kwargs):
        return {"provider": "yandex", "state": "error", "message": "offline_terminal_error"}
    control = RealtimeSessionController(core_json)
    stopped = control.request_stop()
    assert stopped.executed and stopped.state == "error"
    assert stopped.message == "offline_terminal_error"
