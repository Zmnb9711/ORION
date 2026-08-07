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

    def send(self, payload: dict[str, object]) -> int:
        self.payload = payload
        return len(str(payload))


class FailingSender:
    def send(self, payload: dict[str, object]) -> int:
        raise OSError("DCS command socket unavailable")


def test_sync_reports_missing_mapping() -> None:
    sender = FakeSender()
    sync = HornetMappingSynchronizer(sender=sender)
    status = sync.sync(None)
    assert status.available is False
    assert status.sent is False


def test_sync_sends_validated_mapping_command(tmp_path: Path) -> None:
    registry = HornetMappingRegistry(tmp_path / "mapping.json")
    mapping = registry.save(ARGUMENTS)
    sender = FakeSender()
    sync = HornetMappingSynchronizer(sender=sender)
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
    sync = HornetMappingSynchronizer(sender=FailingSender())
    status = sync.sync(mapping)
    assert status.available is True
    assert status.sent is False
    assert "unavailable" in (status.error or "")
