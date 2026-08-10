from pathlib import Path

from orion import alpha_smoke_diagnostics as diagnostics
from orion.alpha_smoke_diagnostics import SmokeCheckState
from orion.dcs_connection_diagnostics import ConnectionState, DcsConnectionReport
from orion.startup_health import StartupHealthCheck, StartupHealthReport, StartupHealthState


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


def test_collect_smoke_report_maps_blocking_and_nonblocking_checks(monkeypatch) -> None:
    monkeypatch.setattr(diagnostics, "inspect_startup_health", _startup)
    monkeypatch.setattr(diagnostics, "diagnose_dcs_connection", _connection)
    report = diagnostics.collect_alpha_smoke_report()
    states = {item.key: item.state for item in report.checks}
    assert states["active_dcs"] is SmokeCheckState.PASS
    assert states["telemetry"] is SmokeCheckState.WARN
    assert states["dcs_connection"] is SmokeCheckState.WARN
    assert states["voice_input"] is SmokeCheckState.WARN
    assert report.passed is True


def test_diagnostics_bundle_contains_json_and_summary(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(diagnostics, "inspect_startup_health", _startup)
    monkeypatch.setattr(diagnostics, "diagnose_dcs_connection", _connection)
    bundle = diagnostics.write_alpha_diagnostics_bundle(tmp_path)
    assert bundle.is_file()
    import zipfile

    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
        assert "summary.txt" in names
        assert any(name.endswith(".json") for name in names)
        summary = archive.read("summary.txt").decode("utf-8")
        assert "voice_input" in summary
        assert "DCS.exe is not running" in summary
