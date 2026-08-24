from __future__ import annotations

from orion.realtime_session_control import RealtimeSessionController


class _Core:
    def __init__(self) -> None:
        self.status = {"provider": None, "state": "stopped", "message": "stopped"}
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []

    def __call__(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.calls.append((method, path, payload))
        if path.endswith("/status"):
            return dict(self.status)
        if path.endswith("/start"):
            self.status = {"provider": str(payload["provider"]), "state": "starting", "message": "starting"}  # type: ignore[index]
        else:
            self.status = {"provider": None, "state": "stopped", "message": "stopped"}
        return dict(self.status)


def test_launcher_controller_uses_generic_start_stop_and_status_routes() -> None:
    core = _Core()
    controller = RealtimeSessionController(core)
    result = controller.request_start(lambda: {"provider": "yandex", "api_key": "key", "folder_id": "folder"})
    assert result.executed is True and result.provider == "yandex"
    assert core.calls[:2] == [
        ("GET", "/v1/realtime/live/status", None),
        ("POST", "/v1/realtime/live/start", {"provider": "yandex", "api_key": "key", "folder_id": "folder"}),
    ]
    assert controller.request_stop().state == "stopped"
    assert core.calls[-1] == ("POST", "/v1/realtime/live/stop", None)


def test_launcher_controller_prevents_duplicate_active_start() -> None:
    core = _Core()
    core.status = {"provider": "qwen", "state": "streaming", "message": "active"}
    controller = RealtimeSessionController(core)
    result = controller.request_start(lambda: {"provider": "yandex", "api_key": "key"})
    assert result.executed is False
    assert result.ignored_reason == "already_active"
    assert all(path != "/v1/realtime/live/start" for _, path, _ in core.calls)


def test_provider_neutral_toggle_starts_and_stops_actual_core_session() -> None:
    core = _Core()
    controller = RealtimeSessionController(core)
    payload = lambda: {"provider": "yandex", "transport": "srs", "api_key": "key"}

    started = controller.toggle(payload)
    assert started.action == "start" and started.executed
    core.status = {"provider": "yandex", "state": "streaming", "message": "live"}
    stopped = controller.toggle(payload)

    assert stopped.action == "stop" and stopped.executed
    assert [path for method, path, _ in core.calls if method == "POST"] == [
        "/v1/realtime/live/start",
        "/v1/realtime/live/stop",
    ]


def test_toggle_stops_starting_or_errored_session_before_restart() -> None:
    for state in ("starting", "error"):
        core = _Core()
        core.status = {"provider": "yandex", "state": state, "message": state}
        controller = RealtimeSessionController(core)

        result = controller.toggle(lambda: {"provider": "yandex", "api_key": "unused"})

        assert result.action == "stop" and result.executed
        assert all(path != "/v1/realtime/live/start" for _, path, _ in core.calls)
        restarted = controller.toggle(lambda: {"provider": "yandex", "api_key": "key"})
        assert restarted.action == "start" and restarted.executed
