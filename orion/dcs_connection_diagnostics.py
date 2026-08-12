from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from enum import StrEnum
from typing import Callable

from pydantic import BaseModel, Field

from orion.telemetry_handshake import TelemetryHandshake, telemetry_handshake


class ConnectionState(StrEnum):
    DCS_NOT_RUNNING = "dcs_not_running"
    EXPORT_SILENT = "export_silent"
    NO_TELEMETRY = "no_telemetry"
    STALE = "stale"
    DEGRADED = "degraded"
    HEALTHY = "healthy"


class DcsConnectionReport(BaseModel):
    state: ConnectionState
    connected: bool
    dcs_process_running: bool | None = None
    aircraft_type: str | None = None
    source: str | None = None
    protocol_version: str | None = None
    packet_count: int = 0
    packet_rate_hz: float = Field(default=0.0, ge=0)
    age_seconds: float | None = Field(default=None, ge=0)
    message: str
    action: str | None = None


ProcessDetector = Callable[[], bool | None]


def detect_dcs_process() -> bool | None:
    """Return whether DCS.exe is running on Windows, or None when detection is unavailable."""
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq DCS.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return '"DCS.exe"' in result.stdout


def diagnose_dcs_connection(
    *,
    handshake: TelemetryHandshake = telemetry_handshake,
    process_detector: ProcessDetector = detect_dcs_process,
    minimum_healthy_rate_hz: float = 5.0,
) -> DcsConnectionReport:
    if (
        os.environ.get("ORION_PROCESS_ROLE") == "launcher"
        and handshake is telemetry_handshake
        and process_detector is detect_dcs_process
    ):
        return _diagnose_dcs_connection_via_core()
    return _diagnose_dcs_connection_local(
        handshake=handshake,
        process_detector=process_detector,
        minimum_healthy_rate_hz=minimum_healthy_rate_hz,
    )


def _diagnose_dcs_connection_local(
    *,
    handshake: TelemetryHandshake,
    process_detector: ProcessDetector,
    minimum_healthy_rate_hz: float,
) -> DcsConnectionReport:
    snapshot = handshake.snapshot()
    process_running = process_detector()

    common = dict(
        connected=snapshot.connected,
        dcs_process_running=process_running,
        aircraft_type=snapshot.aircraft_type,
        source=snapshot.source,
        protocol_version=snapshot.protocol_version,
        packet_count=snapshot.packet_count,
        packet_rate_hz=snapshot.packet_rate_hz,
        age_seconds=snapshot.age_seconds,
    )

    if snapshot.connected:
        if snapshot.aircraft_type is None:
            return DcsConnectionReport(
                state=ConnectionState.HEALTHY,
                message="DCS Export connection is healthy; waiting for aircraft telemetry",
                action="Enter or resume an aircraft slot to restore live flight telemetry",
                **common,
            )
        if snapshot.packet_rate_hz and snapshot.packet_rate_hz < minimum_healthy_rate_hz:
            return DcsConnectionReport(
                state=ConnectionState.DEGRADED,
                message=f"DCS telemetry is live but slow ({snapshot.packet_rate_hz:.2f} Hz)",
                action="Check DCS frame rate, Export.lua load and local system load",
                **common,
            )
        return DcsConnectionReport(
            state=ConnectionState.HEALTHY,
            message="DCS telemetry connection is healthy",
            **common,
        )

    if snapshot.last_received_at is not None:
        return DcsConnectionReport(
            state=ConnectionState.STALE,
            message=f"DCS telemetry stopped {snapshot.age_seconds:.1f} seconds ago",
            action="Check whether DCS is still running and ORION Export.lua is active",
            **common,
        )

    if process_running is False:
        return DcsConnectionReport(
            state=ConnectionState.DCS_NOT_RUNNING,
            message="DCS.exe is not running",
            action="Start DCS World",
            **common,
        )
    if process_running is True:
        return DcsConnectionReport(
            state=ConnectionState.EXPORT_SILENT,
            message="DCS.exe is running but no ORION telemetry has been received",
            action="Check Saved Games\\DCS\\Scripts\\Export.lua and ORION DCS integration",
            **common,
        )
    return DcsConnectionReport(
        state=ConnectionState.NO_TELEMETRY,
        message="No DCS telemetry has been received yet",
        action="Start DCS and enter an aircraft; if already running, check Export.lua",
        **common,
    )


def _diagnose_dcs_connection_via_core() -> DcsConnectionReport:
    base_url = os.environ.get("ORION_CORE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    request = urllib.request.Request(f"{base_url}/v1/dcs-connection/diagnostics", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=2.0) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return DcsConnectionReport(
            state=ConnectionState.NO_TELEMETRY,
            connected=False,
            message=f"Unable to query ORION Core DCS diagnostics: {exc}",
            action="Check ORION Core status and retry",
        )
    return DcsConnectionReport.model_validate(payload)
