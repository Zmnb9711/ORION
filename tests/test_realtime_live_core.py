from __future__ import annotations

from typing import Any

import pytest

from orion.realtime_live_core import RealtimeLiveCoordinator, RealtimeLiveStartRequest
from orion.realtime_provider import RealtimeLiveStatus


class _Provider:
    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        self.state = "stopped"
        self.starts = 0
        self.stops = 0

    def start_live(self, payload: dict[str, Any]) -> RealtimeLiveStatus:
        self.starts += 1
        self.state = "streaming"
        return self.live_status()

    def live_status(self) -> RealtimeLiveStatus:
        return RealtimeLiveStatus(provider=self.provider_id, state=self.state, message=self.state)

    def stop_live(self) -> RealtimeLiveStatus:
        self.stops += 1
        self.state = "stopped"
        return self.live_status()


def _request(provider: str) -> RealtimeLiveStartRequest:
    return RealtimeLiveStartRequest(provider=provider, api_key="key", folder_id="folder", workspace_id="workspace")


def test_coordinator_registers_qwen_and_yandex_and_owns_selected_status() -> None:
    qwen = _Provider("qwen")
    yandex = _Provider("yandex")
    coordinator = RealtimeLiveCoordinator([qwen, yandex])
    assert coordinator.start(_request("yandex")).provider == "yandex"
    assert coordinator.status().provider == "yandex"


def test_only_one_provider_and_duplicate_start_are_rejected() -> None:
    qwen = _Provider("qwen")
    yandex = _Provider("yandex")
    coordinator = RealtimeLiveCoordinator([qwen, yandex])
    coordinator.start(_request("qwen"))
    with pytest.raises(ValueError, match="already active"):
        coordinator.start(_request("qwen"))
    with pytest.raises(ValueError, match="Stop current realtime provider"):
        coordinator.start(_request("yandex"))
    assert yandex.starts == 0


def test_stop_is_idempotent_and_releases_exact_provider() -> None:
    qwen = _Provider("qwen")
    yandex = _Provider("yandex")
    coordinator = RealtimeLiveCoordinator([qwen, yandex])
    coordinator.start(_request("qwen"))
    assert coordinator.stop().state == "stopped"
    assert coordinator.stop().state == "stopped"
    assert qwen.stops == 1
    assert yandex.stops == 0


def test_error_provider_can_be_stopped_then_other_provider_started() -> None:
    qwen = _Provider("qwen")
    yandex = _Provider("yandex")
    coordinator = RealtimeLiveCoordinator([qwen, yandex])
    coordinator.start(_request("qwen"))
    qwen.state = "error"
    with pytest.raises(ValueError, match="Stop errored realtime provider"):
        coordinator.start(_request("yandex"))
    coordinator.stop()
    assert coordinator.start(_request("yandex")).provider == "yandex"
