from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from orion.dcs_installation_discovery import DcsDiscoveryCandidate, candidate_from_install_root
from orion.dcs_installations import DcsInstallationType


class SetupStep(IntEnum):
    DCS = 1
    SAVED_GAMES = 2
    INTEGRATION = 3
    TELEMETRY = 4
    READY = 5


@dataclass(slots=True)
class SetupWizardState:
    step: SetupStep = SetupStep.DCS
    candidate: DcsDiscoveryCandidate | None = None
    saved_games_path: str | None = None
    integration_ready: bool = False
    telemetry_ready: bool = False
    error: str | None = None

    @property
    def can_install(self) -> bool:
        return self.candidate is not None and self.saved_games_path is not None

    @property
    def can_test(self) -> bool:
        return self.integration_ready

    @property
    def ready(self) -> bool:
        return self.integration_ready and self.telemetry_ready

    def select_dcs(self, path: str, installation_type: DcsInstallationType = DcsInstallationType.STANDALONE) -> bool:
        candidate = candidate_from_install_root(Path(path), installation_type)
        if candidate is None:
            self.error = "Selected folder is not a valid DCS World installation"
            return False
        self.candidate = candidate
        self.error = None
        self.step = SetupStep.SAVED_GAMES
        return True

    def select_saved_games(self, path: str) -> bool:
        root = Path(path).expanduser()
        if not root.is_dir():
            self.error = "Selected Saved Games folder does not exist"
            return False
        # Accept DCS and DCS.openbeta profiles, including custom profile names,
        # but require the directory itself rather than silently guessing it.
        self.saved_games_path = str(root)
        self.error = None
        self.step = SetupStep.INTEGRATION
        return True

    def mark_integration(self, ok: bool) -> None:
        self.integration_ready = ok
        self.error = None if ok else "ORION DCS integration is not ready"
        self.step = SetupStep.TELEMETRY if ok else SetupStep.INTEGRATION

    def mark_telemetry(self, ok: bool) -> None:
        self.telemetry_ready = ok
        self.error = None if ok else "Waiting for live telemetry from DCS"
        self.step = SetupStep.READY if ok else SetupStep.TELEMETRY
