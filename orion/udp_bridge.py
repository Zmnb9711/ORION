import asyncio
import json
import logging

from pydantic import ValidationError

from orion.fa18c_diagnostics_recorder import hornet_diagnostics_recorder
from orion.models import TelemetryEnvelope

logger = logging.getLogger(__name__)


class TelemetryProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_telemetry):
        self.on_telemetry = on_telemetry

    def datagram_received(self, data: bytes, addr) -> None:
        try:
            payload = TelemetryEnvelope.model_validate(json.loads(data.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError):
            logger.warning("Rejected invalid telemetry datagram from %s", addr, exc_info=True)
            return
        hornet_diagnostics_recorder.ingest(payload.state.diagnostics)
        self.on_telemetry(payload)


async def start_udp_bridge(on_telemetry, host: str = "127.0.0.1", port: int = 45100):
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: TelemetryProtocol(on_telemetry),
        local_addr=(host, port),
    )
    return transport, protocol
