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
