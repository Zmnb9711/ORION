from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from tools.orion_development_console.models import VerificationReport


class VerificationReportStore:
    """Private derived report storage; never writes primary ORION history."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.reports = root / "reports"
        self.latest_path = root / "latest.json"

    def load_latest(self) -> VerificationReport | None:
        try:
            return VerificationReport.model_validate_json(self.latest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError):
            return None

    def save(self, report: VerificationReport) -> Path:
        self.reports.mkdir(parents=True, exist_ok=True)
        target = self.reports / f"{report.verification_id}.json"
        payload = report.model_dump_json(indent=2)
        self._atomic_write(target, payload)
        self._atomic_write(self.latest_path, payload)
        return target

    @staticmethod
    def _atomic_write(path: Path, payload: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.write("\n")
            temporary.replace(path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
