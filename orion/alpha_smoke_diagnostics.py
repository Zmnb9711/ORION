from __future__ import annotations

import os
import platform as platform_module
import socket
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from pydantic import BaseModel, Field

from orion import __version__
from orion.dcs_connection_diagnostics import DcsConnectionReport, diagnose_dcs_connection
from orion.startup_health import StartupHealthReport, inspect_startup_health
from orion.telemetry_history import TelemetryHistoryReport, collect_telemetry_history


class SmokeCheckState(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class SmokeCheck(BaseModel):
    key: str
    state: SmokeCheckState
    message: str
    action: str | None = None


class TelemetryHistorySummary(BaseModel):
    capacity: int
    retained_packet_count: int
    total_packet_count: int
    session_started_at: datetime | None = None
    last_packet_at: datetime | None = None
    last_seen_aircraft_type: str | None = None
    last_source: str | None = None
    last_protocol_version: str | None = None
    average_packet_rate_hz: float = 0.0


class AlphaSmokeReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    orion_version: str = __version__
    hostname: str = Field(default_factory=socket.gethostname)
    platform: str = Field(default_factory=platform_module.platform)
    python: str = Field(default_factory=platform_module.python_version)
    checks: list[SmokeCheck] = Field(default_factory=list)
    startup: StartupHealthReport
    dcs_connection: DcsConnectionReport
    telemetry_history: TelemetryHistorySummary

    @property
    def passed(self) -> bool:
        return not any(check.state is SmokeCheckState.FAIL for check in self.checks)

    @property
    def overall_state(self) -> SmokeCheckState:
        if any(check.state is SmokeCheckState.FAIL for check in self.checks):
            return SmokeCheckState.FAIL
        if any(check.state is SmokeCheckState.WARN for check in self.checks):
            return SmokeCheckState.WARN
        return SmokeCheckState.PASS


def collect_alpha_smoke_report(history: TelemetryHistoryReport | None = None) -> AlphaSmokeReport:
    startup = inspect_startup_health()
    connection = diagnose_dcs_connection()
    telemetry_history = history or collect_telemetry_history()
    checks: list[SmokeCheck] = []

    for item in startup.checks:
        if item.passed:
            state = SmokeCheckState.PASS
        elif item.blocking:
            state = SmokeCheckState.FAIL
        else:
            state = SmokeCheckState.WARN
        checks.append(
            SmokeCheck(
                key=item.key,
                state=state,
                message=item.message,
                action=item.recovery_action.value if item.recovery_action is not None else None,
            )
        )

    if connection.connected:
        checks.append(SmokeCheck(key="dcs_connection", state=SmokeCheckState.PASS, message=connection.message))
    else:
        checks.append(
            SmokeCheck(
                key="dcs_connection",
                state=SmokeCheckState.WARN,
                message=connection.message,
                action=connection.action,
            )
        )

    checks.append(
        SmokeCheck(
            key="voice_input",
            state=SmokeCheckState.WARN,
            message="Live microphone capture is not automatically verifiable in Alpha 0.1",
            action="Run one spoken command during the live DCS smoke test",
        )
    )
    history_summary = TelemetryHistorySummary.model_validate(
        telemetry_history.model_dump(exclude={"samples"})
    )
    return AlphaSmokeReport(
        startup=startup,
        dcs_connection=connection,
        telemetry_history=history_summary,
        checks=checks,
    )


def write_alpha_diagnostics_bundle(output_dir: Path | None = None) -> Path:
    history = collect_telemetry_history()
    report = collect_alpha_smoke_report(history)
    root = output_dir or _diagnostics_root()
    root.mkdir(parents=True, exist_ok=True)
    stamp = report.generated_at.strftime("%Y%m%d-%H%M%S")
    json_name = f"orion-alpha-smoke-{stamp}.json"
    zip_path = root / f"orion-alpha-smoke-{stamp}.zip"

    summary = _text_summary(report)
    session_json = history.model_dump_json(indent=2, exclude={"samples"})
    telemetry_jsonl = "".join(sample.model_dump_json() + "\n" for sample in history.samples)
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(json_name, report.model_dump_json(indent=2))
        archive.writestr("summary.txt", summary)
        archive.writestr("telemetry-session.json", session_json)
        archive.writestr("telemetry-history.jsonl", telemetry_jsonl)
    return zip_path


def _text_summary(report: AlphaSmokeReport) -> str:
    lines = [
        f"ORION Alpha smoke diagnostics {report.orion_version}",
        f"Overall: {report.overall_state.value.upper()}",
        f"Generated: {report.generated_at.isoformat()}",
        f"Host: {report.hostname}",
        f"Platform: {report.platform}",
        "",
        "Telemetry history:",
        f"  Total packets: {report.telemetry_history.total_packet_count}",
        f"  Retained packets: {report.telemetry_history.retained_packet_count}",
        f"  Last aircraft: {report.telemetry_history.last_seen_aircraft_type or 'unknown'}",
        f"  Last source: {report.telemetry_history.last_source or 'unknown'}",
        f"  Last protocol: {report.telemetry_history.last_protocol_version or 'unknown'}",
        f"  Average rate: {report.telemetry_history.average_packet_rate_hz:.2f} Hz",
        "",
    ]
    for check in report.checks:
        lines.append(f"[{check.state.value.upper()}] {check.key}: {check.message}")
        if check.action:
            lines.append(f"  Action: {check.action}")
    return "\n".join(lines) + "\n"


def _diagnostics_root() -> Path:
    runtime = os.environ.get("ORION_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "diagnostics"
    return Path.cwd() / "runtime" / "diagnostics"
