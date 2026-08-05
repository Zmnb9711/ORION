from __future__ import annotations

import json
import socket
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from orion.capabilities import MissionCapability, capability_registry
from orion.config import settings


class MissionCommandType(StrEnum):
    LASER = "laser"
    SMOKE = "smoke"
    REQUEST_AWACS = "request_awacs"
    REQUEST_TANKER = "request_tanker"


COMMAND_CAPABILITY = {
    MissionCommandType.LASER: MissionCapability.LASER,
    MissionCommandType.SMOKE: MissionCapability.SMOKE,
    MissionCommandType.REQUEST_AWACS: MissionCapability.AWACS,
    MissionCommandType.REQUEST_TANKER: MissionCapability.TANKER,
}


class MissionCommand(BaseModel):
    command_id: UUID = Field(default_factory=uuid4)
    command: MissionCommandType
    target_unit_id: str | None = None
    provider_unit_id: str | None = None
    laser_code: int | None = Field(default=None, ge=1111, le=1788)
    smoke_color: str | None = None

    @model_validator(mode="after")
    def validate_targeted_actions(self) -> "MissionCommand":
        if self.command in {MissionCommandType.LASER, MissionCommandType.SMOKE}:
            if not self.target_unit_id:
                raise ValueError("target_unit_id is required")
        if self.command is MissionCommandType.LASER and self.laser_code is None:
            raise ValueError("laser_code is required")
        return self


class MissionBridge:
    def send(self, command: MissionCommand) -> None:
        capability = COMMAND_CAPABILITY[command.command]
        if not capability_registry.supports(capability):
            raise ValueError(f"Mission capability is unavailable: {capability.value}")

        payload = command.model_dump_json(exclude_none=True).encode("utf-8")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(payload, (settings.mission_bridge_host, settings.mission_bridge_port))


mission_bridge = MissionBridge()
