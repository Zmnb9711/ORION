from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import BaseModel

from orion.config import settings
from orion.fa18c_mapping_registry import HornetArgumentMapping, hornet_mapping_registry


class MappingSyncStatus(BaseModel):
    available: bool
    sent: bool
    mapping_version: str | None = None
    bytes_sent: int = 0
    sent_at: datetime | None = None
    error: str | None = None


@dataclass
class UdpCommandSender:
    host: str = settings.command_host
    port: int = settings.command_port

    def send(self, payload: dict[str, object]) -> int:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            return sock.sendto(encoded, (self.host, self.port))


class HornetMappingSynchronizer:
    def __init__(self, sender: UdpCommandSender | None = None) -> None:
        self.sender = sender or UdpCommandSender()
        self._last_status = MappingSyncStatus(available=False, sent=False)

    def sync(self, mapping: HornetArgumentMapping | None = None) -> MappingSyncStatus:
        selected = mapping or hornet_mapping_registry.current()
        if selected is None:
            self._last_status = MappingSyncStatus(available=False, sent=False, error="No validated Hornet mapping is stored")
            return self._last_status
        try:
            count = self.sender.send(selected.dcs_command())
        except OSError as exc:
            self._last_status = MappingSyncStatus(
                available=True,
                sent=False,
                mapping_version=selected.version,
                error=str(exc),
            )
            return self._last_status
        self._last_status = MappingSyncStatus(
            available=True,
            sent=True,
            mapping_version=selected.version,
            bytes_sent=count,
            sent_at=datetime.now(timezone.utc),
        )
        return self._last_status

    def status(self) -> MappingSyncStatus:
        return self._last_status


hornet_mapping_synchronizer = HornetMappingSynchronizer()
