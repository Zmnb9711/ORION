from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import BaseModel

from orion.config import settings
from orion.fa18c_mapping_registry import HornetArgumentMapping, HornetMappingRegistry, hornet_mapping_registry


class MappingSyncStatus(BaseModel):
    available: bool
    sent: bool
    mapping_version: str | None = None
    bytes_sent: int = 0
    sent_at: datetime | None = None
    reported_version: str | None = None
    reported_validated: bool = False
    reason: str | None = None
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
    def __init__(
        self,
        sender: UdpCommandSender | None = None,
        registry: HornetMappingRegistry | None = None,
        cooldown_seconds: float = 2.0,
    ) -> None:
        self.sender = sender or UdpCommandSender()
        self.registry = registry or hornet_mapping_registry
        self.cooldown_seconds = max(0.0, cooldown_seconds)
        self._last_attempt_monotonic: float | None = None
        self._last_attempt_version: str | None = None
        self._last_status = MappingSyncStatus(available=False, sent=False)

    def sync(self, mapping: HornetArgumentMapping | None = None, *, reason: str = "manual") -> MappingSyncStatus:
        selected = mapping or self.registry.current()
        if selected is None:
            self._last_status = MappingSyncStatus(
                available=False,
                sent=False,
                reason=reason,
                error="No validated Hornet mapping is stored",
            )
            return self._last_status
        try:
            count = self.sender.send(selected.dcs_command())
        except OSError as exc:
            self._last_status = MappingSyncStatus(
                available=True,
                sent=False,
                mapping_version=selected.version,
                reason=reason,
                error=str(exc),
            )
            return self._last_status
        self._last_attempt_monotonic = time.monotonic()
        self._last_attempt_version = selected.version
        self._last_status = MappingSyncStatus(
            available=True,
            sent=True,
            mapping_version=selected.version,
            bytes_sent=count,
            sent_at=datetime.now(timezone.utc),
            reason=reason,
        )
        return self._last_status

    def ensure_for_cockpit(self, cockpit_state: object) -> MappingSyncStatus:
        selected = self.registry.current()
        if selected is None:
            self._last_status = MappingSyncStatus(
                available=False,
                sent=False,
                reason="telemetry",
                error="No validated Hornet mapping is stored",
            )
            return self._last_status

        payload = cockpit_state if isinstance(cockpit_state, dict) else {}
        reported_version = payload.get("mapping_version") if isinstance(payload.get("mapping_version"), str) else None
        reported_validated = payload.get("mapping_validated") is True

        if reported_validated and reported_version == selected.version:
            self._last_status = MappingSyncStatus(
                available=True,
                sent=False,
                mapping_version=selected.version,
                reported_version=reported_version,
                reported_validated=True,
                reason="already-synchronized",
            )
            return self._last_status

        now = time.monotonic()
        if (
            self._last_attempt_monotonic is not None
            and self._last_attempt_version == selected.version
            and now - self._last_attempt_monotonic < self.cooldown_seconds
        ):
            self._last_status = MappingSyncStatus(
                available=True,
                sent=False,
                mapping_version=selected.version,
                reported_version=reported_version,
                reported_validated=reported_validated,
                reason="cooldown",
            )
            return self._last_status

        status = self.sync(selected, reason="telemetry-mismatch")
        status.reported_version = reported_version
        status.reported_validated = reported_validated
        self._last_status = status
        return status

    def status(self) -> MappingSyncStatus:
        return self._last_status


hornet_mapping_synchronizer = HornetMappingSynchronizer()
