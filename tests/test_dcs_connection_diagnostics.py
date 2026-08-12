import json
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


def test_reports_healthy_export_heartbeat_without_aircraft() -> None:
    handshake = TelemetryHandshake(stale_after_seconds=5, rate_window_seconds=5)
    handshake.observe(telemetry())
    handshake.observe_heartbeat(source="dcs-export", protocol_version="0.2")

    report = diagnose_dcs_connection(handshake=handshake, process_detector=lambda: True)

    assert report.state == ConnectionState.HEALTHY
    assert report.connected is True
    assert report.aircraft_type is None
    assert report.protocol_version == "0.2"
    assert report.packet_count == 1
    assert "waiting for aircraft telemetry" in report.message


def test_telemetry_recovers_after_heartbeat_only_period() -> None:
    handshake = TelemetryHandshake(stale_after_seconds=5, rate_window_seconds=5)
    handshake.observe_heartbeat(source="dcs-export", protocol_version="0.2")
    handshake.observe(telemetry())

    report = diagnose_dcs_connection(handshake=handshake, process_detector=lambda: True)

    assert report.state == ConnectionState.HEALTHY
    assert report.connected is True
    assert report.aircraft_type == "FA-18C_hornet"
    assert report.packet_count == 1


def test_reports_stale_after_stream_stops() -> None:
    handshake = TelemetryHandshake(stale_after_seconds=0.001)
    handshake.observe(telemetry(), received_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    report = diagnose_dcs_connection(handshake=handshake, process_detector=lambda: True)
    assert report.state == ConnectionState.STALE
    assert report.age_seconds is not None and report.age_seconds >= 1


def test_launcher_diagnostics_use_core_snapshot(monkeypatch) -> None:
    import orion.dcs_connection_diagnostics as diagnostics

    payload = {
        "state": "healthy",
        "connected": True,
        "dcs_process_running": True,
        "aircraft_type": "FA-18C_hornet",
        "source": "dcs-export",
        "protocol_version": "0.1",
        "packet_count": 42,
        "packet_rate_hz": 10.0,
        "age_seconds": 0.1,
        "message": "DCS telemetry connection is healthy",
        "action": None,
    }

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setenv("ORION_PROCESS_ROLE", "launcher")
    monkeypatch.setenv("ORION_CORE_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setattr(diagnostics.urllib.request, "urlopen", lambda *args, **kwargs: Response())

    report = diagnose_dcs_connection()

    assert report.connected is True
    assert report.packet_count == 42
    assert report.state == ConnectionState.HEALTHY
