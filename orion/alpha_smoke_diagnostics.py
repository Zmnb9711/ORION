from __future__ import annotations

import json
import os
import platform
import socket
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from pydantic import BaseModel, Field

from orion import __version__
from orion.dcs_connection_diagnostics import DcsConnectionReport, diagnose_dcs_connection
from orion.startup_health import StartupHealthReport, inspect_startup_health


class SmokeCheckState(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class SmokeCheck(BaseModel):
    key: str
    state: SmokeCheckState
    message: str
    action: str | None = None


class AlphaSmokeReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    orion_version: str = __version__
    hostname: str = Field(default_factory=socket.gethostname)
    platform: str = Field(default_factory=platform.platform)
    python: str = Field(default_factory=platform.python_version)
    checks: list[SmokeCheck] = Field(default_factory=list)
    startup: StartupHealthReport
    dcs_connection: DcsConnectionReport

    @property
    def passed(self) -> bool:
        return not any(check.state is SmokeCheckState.FAIL for check in self.checks)


def collect_alpha_smoke_report() -> AlphaSmokeReport:
    startup = inspect_startup_health()
    connection = diagnose_dcs_connection()
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
    return AlphaSmokeReport(startup=startup, dcs_connection=connection, checks=checks)


def write_alpha_diagnostics_bundle(output_dir: Path | None = None) -> Path:
    report = collect_alpha_smoke_report()
    root = output_dir or _diagnostics_root()
    root.mkdir(parents=True, exist_ok=True)
    stamp = report.generated_at.strftime("%Y%m%d-%H%M%S")
    json_path = root / f"orion-alpha-smoke-{stamp}.json"
    zip_path = root / f"orion-alpha-smoke-{stamp}.zip"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    summary = _text_summary(report)
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.write(json_path, arcname=json_path.name)
        archive.writestr("summary.txt", summary)
    return zip_path


def _text_summary(report: AlphaSmokeReport) -> str:
    lines = [
        f"ORION Alpha smoke diagnostics {report.orion_version}",
        f"Generated: {report.generated_at.isoformat()}",
        f"Host: {report.hostname}",
        f"Platform: {report.platform}",
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
