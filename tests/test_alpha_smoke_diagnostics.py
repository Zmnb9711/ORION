from datetime import datetime, timezone
from pathlib import Path

from orion import alpha_smoke_diagnostics as diagnostics
from orion.alpha_smoke_diagnostics import SmokeCheckState
from orion.dcs_connection_diagnostics import ConnectionState, DcsConnectionReport
from orion.startup_health import StartupHealthCheck, StartupHealthReport, StartupHealthState
from orion.telemetry_history import TelemetryHistoryReport, TelemetryPacketSample


def _startup() -> StartupHealthReport:
    return StartupHealthReport(
        state=StartupHealthState.DEGRADED,
        checks=[
            StartupHealthCheck(key="active_dcs", passed=True, blocking=True, message="DCS ready"),
            StartupHealthCheck(key="telemetry", passed=False, blocking=False, message="Waiting for telemetry"),
        ],
    )


def _connection() -> DcsConnectionReport:
    return DcsConnectionReport(
        state=ConnectionState.DCS_NOT_RUNNING,
        connected=False,
        dcs_process_running=False,
        message="DCS.exe is not running",
        action="Start DCS World",
    )


def _history() -> TelemetryHistoryReport:
    received_at = datetime(2026, 8, 13, 0, 0, tzinfo=timezone.utc)
    return TelemetryHistoryReport(
        capacity=5000,
        retained_packet_count=1,
        total_packet_count=12224,
        session_started_at=received_at,
        last_packet_at=received_at,
        last_seen_aircraft_type="FA-18C_hornet",
        last_source="dcs-export",
        last_protocol_version="0.2",
        average_packet_rate_hz=30.0,
        samples=[
            TelemetryPacketSample(
                received_at=received_at,
                payload={"protocol_version": "0.2", "source": "dcs-export", "state": {"aircraft_type": "FA-18C_hornet"}},
            )
        ],
    )


def test_collect_smoke_report_maps_blocking_and_nonblocking_checks(monkeypatch) -> None:
    monkeypatch.setattr(diagnostics, "inspect_startup_health", _startup)
    monkeypatch.setattr(diagnostics, "diagnose_dcs_connection", _connection)
    report = diagnostics.collect_alpha_smoke_report(_history())
    states = {item.key: item.state for item in report.checks}
    assert states["active_dcs"] is SmokeCheckState.PASS
    assert states["telemetry"] is SmokeCheckState.WARN
    assert states["dcs_connection"] is SmokeCheckState.WARN
    assert states["voice_input"] is SmokeCheckState.WARN
    assert report.telemetry_history.last_seen_aircraft_type == "FA-18C_hornet"
    assert report.telemetry_history.total_packet_count == 12224
    assert report.passed is True


def test_diagnostics_bundle_contains_telemetry_history(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(diagnostics, "inspect_startup_health", _startup)
    monkeypatch.setattr(diagnostics, "diagnose_dcs_connection", _connection)
    monkeypatch.setattr(diagnostics, "collect_telemetry_history", _history)
    bundle = diagnostics.write_alpha_diagnostics_bundle(tmp_path)
    assert bundle.is_file()
    import zipfile

    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
        assert "summary.txt" in names
        assert "telemetry-session.json" in names
        assert "telemetry-history.jsonl" in names
        assert any(name.startswith("orion-alpha-smoke-") and name.endswith(".json") for name in names)
        summary = archive.read("summary.txt").decode("utf-8")
        telemetry = archive.read("telemetry-history.jsonl").decode("utf-8")
        assert "voice_input" in summary
        assert "DCS.exe is not running" in summary
        assert "FA-18C_hornet" in summary
        assert "FA-18C_hornet" in telemetry
