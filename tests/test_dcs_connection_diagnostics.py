from datetime import datetime, timedelta, timezone

from orion.dcs_connection_diagnostics import ConnectionState, diagnose_dcs_connection
from orion.models import AircraftState, Position, TelemetryEnvelope
from orion.telemetry_handshake import TelemetryHandshake


def telemetry() -> TelemetryEnvelope:
    return TelemetryEnvelope(
        protocol_version="0.1",
        source="dcs-export",
        state=AircraftState(
            aircraft_type="FA-18C_hornet",
            position=Position(latitude=41.0, longitude=41.0, altitude_m=1000),
            heading_deg=90,
            true_airspeed_mps=200,
        ),
    )


def test_reports_dcs_not_running_when_process_is_absent() -> None:
    handshake = TelemetryHandshake()
    report = diagnose_dcs_connection(handshake=handshake, process_detector=lambda: False)
    assert report.state == ConnectionState.DCS_NOT_RUNNING
    assert report.connected is False


def test_reports_export_silent_when_dcs_runs_without_packets() -> None:
    handshake = TelemetryHandshake()
    report = diagnose_dcs_connection(handshake=handshake, process_detector=lambda: True)
    assert report.state == ConnectionState.EXPORT_SILENT


def test_reports_healthy_rate_and_protocol() -> None:
    handshake = TelemetryHandshake(stale_after_seconds=5, rate_window_seconds=5)
    start = datetime.now(timezone.utc)
    for index in range(21):
        handshake.observe(telemetry(), received_at=start + timedelta(seconds=index * 0.1))
    report = diagnose_dcs_connection(handshake=handshake, process_detector=lambda: True)
    assert report.state == ConnectionState.HEALTHY
    assert report.packet_rate_hz == 10.0
    assert report.protocol_version == "0.1"
    assert report.aircraft_type == "FA-18C_hornet"


def test_reports_stale_after_stream_stops() -> None:
    handshake = TelemetryHandshake(stale_after_seconds=0.001)
    handshake.observe(telemetry(), received_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    report = diagnose_dcs_connection(handshake=handshake, process_detector=lambda: True)
    assert report.state == ConnectionState.STALE
    assert report.age_seconds is not None and report.age_seconds >= 1
