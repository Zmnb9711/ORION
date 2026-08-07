import pytest

from orion.capabilities import (
    MissionCapability,
    MissionPackRegistration,
    capability_registry,
)
from orion.mission_bridge import MissionBridge, MissionCommand, MissionCommandType


class FakeSocket:
    def __init__(self, *args, **kwargs) -> None:
        self.sent: tuple[bytes, tuple[str, int]] | None = None

    def __enter__(self) -> "FakeSocket":
        return self

    def __exit__(self, *args) -> None:
        return None

    def sendto(self, payload: bytes, address: tuple[str, int]) -> None:
        self.sent = (payload, address)


def test_mission_command_is_rejected_without_capability() -> None:
    capability_registry._registration = None
    command = MissionCommand(
        command=MissionCommandType.LASER,
        target_unit_id="target-1",
        laser_code=1688,
    )

    with pytest.raises(ValueError, match="Mission capability is unavailable"):
        MissionBridge().send(command)


def test_registered_capability_allows_command(monkeypatch) -> None:
    capability_registry.register(
        MissionPackRegistration(
            mission_id="demo",
            pack_version="0.1.0",
            capabilities={MissionCapability.LASER},
        )
    )
    fake_socket = FakeSocket()
    monkeypatch.setattr("orion.mission_bridge.socket.socket", lambda *args, **kwargs: fake_socket)

    MissionBridge().send(
        MissionCommand(
            command=MissionCommandType.LASER,
            target_unit_id="target-1",
            laser_code=1688,
        )
    )

    assert fake_socket.sent is not None
    assert b'"command":"laser"' in fake_socket.sent[0]
