from pathlib import Path

from orion.fa18c_mapping_registry import HornetMappingRegistry
from orion.fa18c_mapping_sync import HornetMappingSynchronizer


ARGUMENTS = {
    "tacan_power": 410,
    "tacan_channel_tens": 411,
    "tacan_channel_ones": 412,
    "tacan_xy": 413,
    "comm1_selector": 133,
    "comm2_selector": 134,
}


class FakeSender:
    def __init__(self) -> None:
        self.payload = None
        self.calls = 0

    def send(self, payload: dict[str, object]) -> int:
        self.payload = payload
        self.calls += 1
        return len(str(payload))


class FailingSender:
    def send(self, payload: dict[str, object]) -> int:
        raise OSError("DCS command socket unavailable")


def test_sync_reports_missing_mapping(tmp_path: Path) -> None:
    sender = FakeSender()
    registry = HornetMappingRegistry(tmp_path / "missing.json")
    sync = HornetMappingSynchronizer(sender=sender, registry=registry)
    status = sync.sync(None)
    assert status.available is False
    assert status.sent is False
    assert sender.calls == 0


def test_sync_sends_validated_mapping_command(tmp_path: Path) -> None:
    registry = HornetMappingRegistry(tmp_path / "mapping.json")
    mapping = registry.save(ARGUMENTS)
    sender = FakeSender()
    sync = HornetMappingSynchronizer(sender=sender, registry=registry)
    status = sync.sync(mapping)
    assert status.available is True
    assert status.sent is True
    assert status.mapping_version == "fa18c-clickable-calibrated-v1"
    assert sender.payload is not None
    assert sender.payload["command"] == "set_cockpit_mapping"
    assert sender.payload["tacan_power_id"] == 410


def test_sync_exposes_transport_error(tmp_path: Path) -> None:
    registry = HornetMappingRegistry(tmp_path / "mapping.json")
    mapping = registry.save(ARGUMENTS)
    sync = HornetMappingSynchronizer(sender=FailingSender(), registry=registry)
    status = sync.sync(mapping)
    assert status.available is True
    assert status.sent is False
    assert "unavailable" in (status.error or "")


def test_telemetry_mismatch_triggers_mapping_sync(tmp_path: Path) -> None:
    registry = HornetMappingRegistry(tmp_path / "mapping.json")
    mapping = registry.save(ARGUMENTS)
    sender = FakeSender()
    sync = HornetMappingSynchronizer(sender=sender, registry=registry, cooldown_seconds=10)

    status = sync.ensure_for_cockpit({"mapping_version": "fa18c-clickable-v0", "mapping_validated": False})

    assert status.sent is True
    assert status.reason == "telemetry-mismatch"
    assert status.mapping_version == mapping.version
    assert status.reported_version == "fa18c-clickable-v0"
    assert status.reported_validated is False
    assert sender.calls == 1


def test_telemetry_sync_uses_cooldown_to_avoid_udp_spam(tmp_path: Path) -> None:
    registry = HornetMappingRegistry(tmp_path / "mapping.json")
    registry.save(ARGUMENTS)
    sender = FakeSender()
    sync = HornetMappingSynchronizer(sender=sender, registry=registry, cooldown_seconds=60)

    first = sync.ensure_for_cockpit({"mapping_version": "fa18c-clickable-v0", "mapping_validated": False})
    second = sync.ensure_for_cockpit({"mapping_version": "fa18c-clickable-v0", "mapping_validated": False})

    assert first.sent is True
    assert second.sent is False
    assert second.reason == "cooldown"
    assert sender.calls == 1


def test_matching_validated_mapping_does_not_send(tmp_path: Path) -> None:
    registry = HornetMappingRegistry(tmp_path / "mapping.json")
    mapping = registry.save(ARGUMENTS)
    sender = FakeSender()
    sync = HornetMappingSynchronizer(sender=sender, registry=registry)

    status = sync.ensure_for_cockpit({"mapping_version": mapping.version, "mapping_validated": True})

    assert status.available is True
    assert status.sent is False
    assert status.reason == "already-synchronized"
    assert status.reported_validated is True
    assert sender.calls == 0
