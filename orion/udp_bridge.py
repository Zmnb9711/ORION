import asyncio
import json
import logging
from collections.abc import Callable

from pydantic import ValidationError

from orion.fa18c_diagnostics_recorder import hornet_diagnostics_recorder
from orion.fa18c_mapping_auto_progress import hornet_mapping_auto_progress
from orion.fa18c_mapping_sync import hornet_mapping_synchronizer
from orion.models import TelemetryEnvelope
from orion.telemetry_handshake import telemetry_handshake

logger = logging.getLogger(__name__)

HeartbeatHandler = Callable[..., None]


class TelemetryProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_telemetry, on_heartbeat: HeartbeatHandler | None = None):
        self.on_telemetry = on_telemetry
        self.on_heartbeat = on_heartbeat or telemetry_handshake.observe_heartbeat

    def datagram_received(self, data: bytes, addr) -> None:
        try:
            decoded = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("Rejected invalid telemetry datagram from %s", addr, exc_info=True)
            return

        if isinstance(decoded, dict) and decoded.get("kind") == "heartbeat":
            self._handle_heartbeat(decoded, addr)
            return

        try:
            payload = TelemetryEnvelope.model_validate(decoded)
        except ValidationError:
            logger.warning("Rejected invalid telemetry datagram from %s", addr, exc_info=True)
            return
        ingested_changes = hornet_diagnostics_recorder.ingest(payload.state.diagnostics)
        if ingested_changes:
            hornet_mapping_auto_progress.on_diagnostics_packet()
        if payload.state.aircraft_type == "FA-18C_hornet":
            hornet_mapping_synchronizer.ensure_for_cockpit(payload.state.cockpit_state)
        self.on_telemetry(payload)

    def _handle_heartbeat(self, payload: dict[str, object], addr) -> None:
        source = payload.get("source")
        protocol_version = payload.get("protocol_version")
        if not isinstance(source, str) or not source or not isinstance(protocol_version, str) or not protocol_version:
            logger.warning("Rejected invalid DCS export heartbeat from %s", addr)
            return
        self.on_heartbeat(source=source, protocol_version=protocol_version)


async def start_udp_bridge(
    on_telemetry,
    on_heartbeat: HeartbeatHandler | None = None,
    host: str = "127.0.0.1",
    port: int = 45100,
):
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: TelemetryProtocol(on_telemetry, on_heartbeat),
        local_addr=(host, port),
    )
    return transport, protocol
