"""Dedicated ownership of the REAL recovery Core telemetry ingress and facade."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import socket

from orion.live_telemetry_store import live_telemetry
from orion.models import TelemetryEnvelope
from orion.telemetry_handshake import telemetry_handshake
from orion.udp_bridge import TelemetryProtocol
from orion.world_model import world_model
from orion.world_model_contracts import WorldFactStatus


class RecoveryLiveWorld:
    """One exclusive UDP45100 owner; no HTTP dependency on an installed Core."""

    def __init__(self, *, port: int = 45100) -> None:
        self.port = port
        self.world = world_model
        self.transport = None

    @staticmethod
    def ingest(payload: TelemetryEnvelope) -> None:
        now = datetime.now(UTC)
        live_telemetry.set(payload, received_at=now)
        telemetry_handshake.observe(payload, received_at=now)

    @staticmethod
    def heartbeat(*, source: str, protocol_version: str) -> None:
        now = datetime.now(UTC)
        live_telemetry.observe_heartbeat(source=source, protocol_version=protocol_version, received_at=now)
        telemetry_handshake.observe_heartbeat(source=source, protocol_version=protocol_version, received_at=now)

    async def start(self, timeout: float = 10.0) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(("127.0.0.1", self.port))
            sock.setblocking(False)
            self.transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
                lambda: TelemetryProtocol(self.ingest, self.heartbeat), sock=sock,
            )
            # Require a NEW packet after acquiring this lifecycle, never old globals.
            generation = live_telemetry.snapshot().generation
            received_after = datetime.now(UTC)
            deadline = asyncio.get_running_loop().time() + timeout
            while asyncio.get_running_loop().time() < deadline:
                current = self.world.ownship()
                telemetry = live_telemetry.snapshot()
                if (
                    telemetry.generation != generation
                    and telemetry.last_received_at is not None
                    and telemetry.last_received_at >= received_after
                    and current.heading_deg.status is WorldFactStatus.KNOWN
                    and current.position.status is WorldFactStatus.KNOWN
                ):
                    return
                await asyncio.sleep(.05)
            raise TimeoutError("recovery_live_ownship_not_ready")
        except BaseException:
            sock.close()
            await self.close()
            raise

    async def close(self) -> None:
        if self.transport is not None:
            self.transport.close()
            self.transport = None
            await asyncio.sleep(0)
