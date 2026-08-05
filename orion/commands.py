from __future__ import annotations

import json
import socket
from enum import StrEnum

from pydantic import BaseModel, Field

from orion.config import settings


class CommandType(StrEnum):
    PING = "ping"
    SHOW_MESSAGE = "show_message"
    REQUEST_STATUS = "request_status"


class DcsCommand(BaseModel):
    command: CommandType
    message: str | None = Field(default=None, max_length=240)


class CommandDispatcher:
    def send(self, command: DcsCommand) -> None:
        payload = command.model_dump_json(exclude_none=True).encode("utf-8")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(payload, (settings.command_host, settings.command_port))
