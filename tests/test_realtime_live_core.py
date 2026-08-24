from __future__ import annotations

from typing import Any

import pytest

from orion.realtime_live_core import RealtimeLiveCoordinator, RealtimeLiveStartRequest
from orion.realtime_provider import RealtimeLiveStatus


class _Provider:
    def __init__(self, provider_id: str, transport_id: str = "direct") -> None:
        self.provider_id = provider_id
        self.transport_id = transport_id
        self.state = "stopped"
        self.starts = 0
        self.stops = 0

    def start_live(self, payload: dict[str, Any]) -> RealtimeLiveStatus:
        self.starts += 1
        self.state = "streaming"
        return self.live_status()

    def live_status(self) -> RealtimeLiveStatus:
        return RealtimeLiveStatus(
            provider=self.provider_id,
            transport=self.transport_id,
            state=self.state,
            message=self.state,
        )

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


def test_provider_transport_matrix_and_legacy_direct_default() -> None:
    qwen_direct = _Provider("qwen")
    yandex_direct = _Provider("yandex")
    yandex_srs = _Provider("yandex", "srs")
    coordinator = RealtimeLiveCoordinator([qwen_direct, yandex_direct, yandex_srs])
    legacy = _request("yandex")
    assert legacy.transport == "direct"
    coordinator.start(legacy)
    coordinator.stop()
    srs = RealtimeLiveStartRequest(
        provider="yandex",
        transport="srs",
        api_key="memory-only",
        folder_id="folder",
        srs={"eam_password": "eam-memory-only"},
    )
    coordinator.start(srs)
    assert yandex_srs.starts == 1
    assert coordinator.status().transport == "srs"
    coordinator.stop()


def test_qwen_srs_is_explicitly_rejected_without_fallback() -> None:
    qwen_direct = _Provider("qwen")
    coordinator = RealtimeLiveCoordinator([qwen_direct])
    request = RealtimeLiveStartRequest(
        provider="qwen",
        transport="srs",
        api_key="key",
        workspace_id="workspace",
        srs={"eam_password": "secret"},
    )
    with pytest.raises(ValueError, match=r"Qwen \+ SRS"):
        coordinator.start(request)
    assert qwen_direct.starts == 0


def test_secret_fields_are_redacted_from_request_repr() -> None:
    request = RealtimeLiveStartRequest(
        provider="yandex",
        transport="srs",
        api_key="api-visible-only-in-memory",
        folder_id="folder",
        srs={"eam_password": "eam-visible-only-in-memory"},
    )
    rendered = repr(request)
    assert "api-visible-only-in-memory" not in rendered
    assert "eam-visible-only-in-memory" not in rendered
    assert "**********" in rendered
