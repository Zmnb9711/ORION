from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from orion.fa18c_diagnostics_recorder import MappingCandidate, hornet_diagnostics_recorder
from orion.fa18c_mapping_registry import hornet_mapping_registry
from orion.fa18c_mapping_sync import hornet_mapping_synchronizer
from orion.fa18c_value_profiles import (
    ControlValueProfile,
    HornetValueProfileSet,
    calibrated_detents,
    hornet_value_profile_registry,
)


class CalibrationStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETE = "complete"
    NEEDS_RETRY = "needs_retry"


class CalibrationStep(BaseModel):
    key: str
    instruction_en: str
    instruction_ru: str
    repetitions: int = Field(default=3, ge=1, le=20)


class CalibrationResult(BaseModel):
    key: str
    accepted_argument_id: int | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    candidates: list[MappingCandidate] = Field(default_factory=list)


class CalibrationSession(BaseModel):
    session_id: str
    status: CalibrationStatus
    current_step: int = 0
    steps: list[CalibrationStep]
    results: list[CalibrationResult] = Field(default_factory=list)
    mapping_version: str | None = None
    value_profile_version: str | None = None
    mapping_sync_sent: bool = False

    @property
    def active_step(self) -> CalibrationStep | None:
        if 0 <= self.current_step < len(self.steps):
            return self.steps[self.current_step]
        return None


DEFAULT_HORNET_STEPS = [
    CalibrationStep(
        key="tacan_power",
        instruction_en="Start at TACAN OFF, move to the normal operating position, then return to OFF; repeat three times.",
        instruction_ru="Начните с TACAN OFF, переведите в рабочее положение и верните в OFF; повторите три раза.",
    ),
    CalibrationStep(
        key="tacan_channel_tens",
        instruction_en="Set TACAN tens to 0, then move sequentially 1→2→3→4→5→6→7→8→9.",
        instruction_ru="Установите десятки TACAN на 0, затем последовательно 1→2→3→4→5→6→7→8→9.",
        repetitions=8,
    ),
    CalibrationStep(
        key="tacan_channel_ones",
        instruction_en="Set TACAN ones to 0, then move sequentially 1→2→3→4→5→6→7→8→9.",
        instruction_ru="Установите единицы TACAN на 0, затем последовательно 1→2→3→4→5→6→7→8→9.",
        repetitions=8,
    ),
    CalibrationStep(
        key="tacan_xy",
        instruction_en="Start at TACAN X, switch to Y and back to X three times.",
        instruction_ru="Начните с TACAN X, переключите в Y и обратно в X три раза.",
    ),
    CalibrationStep(key="comm1_selector", instruction_en="Move the COMM1 selector between two positions three times.", instruction_ru="Переключите селектор COMM1 между двумя положениями три раза."),
    CalibrationStep(key="comm2_selector", instruction_en="Move the COMM2 selector between two positions three times.", instruction_ru="Переключите селектор COMM2 между двумя положениями три раза."),
]


TACAN_PROFILE_KEYS = ("tacan_power", "tacan_channel_tens", "tacan_channel_ones", "tacan_xy")


@dataclass
class HornetCalibrationWizard:
    session: CalibrationSession | None = None
    _diagnostic_session_id: str | None = field(default=None, init=False)

    def start(self, steps: list[CalibrationStep] | None = None) -> CalibrationSession:
        selected = list(steps or DEFAULT_HORNET_STEPS)
        if not selected:
            raise ValueError("Calibration requires at least one step")
        session_id = str(uuid4())
        self._diagnostic_session_id = hornet_diagnostics_recorder.start(f"calibration:{session_id}")
        self.session = CalibrationSession(session_id=session_id, status=CalibrationStatus.RUNNING, steps=selected)
        hornet_diagnostics_recorder.mark(selected[0].key)
        return self.session

    def current(self) -> CalibrationSession:
        if self.session is None:
            raise RuntimeError("No calibration session exists")
        return self.session

    def evaluate_step(self, minimum_confidence: float = 0.72) -> CalibrationSession:
        session = self.current()
        step = session.active_step
        if step is None or session.status != CalibrationStatus.RUNNING:
            raise RuntimeError("No active calibration step")
        report = hornet_diagnostics_recorder.report()
        marker_ids = set(report.markers.get(step.key, []))
        candidates = [candidate for candidate in report.candidates if candidate.argument_id in marker_ids]
        candidates.sort(key=lambda candidate: (-candidate.score, -candidate.observations, candidate.argument_id))
        confidence = self._confidence(candidates, step.repetitions)
        accepted = candidates[0].argument_id if candidates and candidates[0].observations >= step.repetitions and confidence >= minimum_confidence else None
        result = CalibrationResult(key=step.key, accepted_argument_id=accepted, confidence=confidence, candidates=candidates[:5])
        session.results = [item for item in session.results if item.key != step.key] + [result]
        if accepted is None:
            session.status = CalibrationStatus.NEEDS_RETRY
            return session
        session.current_step += 1
        if session.current_step >= len(session.steps):
            session.status = CalibrationStatus.COMPLETE
            hornet_diagnostics_recorder.stop()
            self._persist_and_sync_mapping(session)
            return session
        hornet_diagnostics_recorder.mark(session.steps[session.current_step].key)
        return session

    def retry(self) -> CalibrationSession:
        session = self.current()
        step = session.active_step
        if session.status != CalibrationStatus.NEEDS_RETRY or step is None:
            raise RuntimeError("Calibration step is not awaiting retry")
        session.status = CalibrationStatus.RUNNING
        hornet_diagnostics_recorder.mark(step.key)
        return session

    def cancel(self) -> None:
        if self.session and self.session.status in {CalibrationStatus.RUNNING, CalibrationStatus.NEEDS_RETRY}:
            hornet_diagnostics_recorder.stop()
        self.session = None
        self._diagnostic_session_id = None

    @staticmethod
    def _persist_and_sync_mapping(session: CalibrationSession) -> None:
        arguments = {
            item.key: item.accepted_argument_id
            for item in session.results
            if item.accepted_argument_id is not None
        }
        confidence = {item.key: item.confidence for item in session.results if item.accepted_argument_id is not None}
        mapping = hornet_mapping_registry.save(arguments, confidence)
        session.mapping_version = mapping.version

        controls: dict[str, ControlValueProfile] = {}
        for item in session.results:
            if item.key not in TACAN_PROFILE_KEYS or item.accepted_argument_id is None:
                continue
            accepted_candidate = next(
                (candidate for candidate in item.candidates if candidate.argument_id == item.accepted_argument_id),
                None,
            )
            if accepted_candidate is None:
                continue
            detents = calibrated_detents(accepted_candidate.transitions)
            if item.key in {"tacan_channel_tens", "tacan_channel_ones"} and len(detents) != 10:
                continue
            if item.key in {"tacan_power", "tacan_xy"} and len(detents) < 2:
                continue
            controls[item.key] = ControlValueProfile(
                control=item.key,
                argument_id=item.accepted_argument_id,
                detents=detents,
            )

        if all(key in controls for key in TACAN_PROFILE_KEYS):
            profiles = hornet_value_profile_registry.save(
                HornetValueProfileSet(mapping_version=mapping.version, controls=controls)
            )
            session.value_profile_version = profiles.version

        session.mapping_sync_sent = hornet_mapping_synchronizer.sync(mapping).sent

    @staticmethod
    def _confidence(candidates: list[MappingCandidate], repetitions: int) -> float:
        if not candidates:
            return 0.0
        top = candidates[0].score
        runner_up = candidates[1].score if len(candidates) > 1 else 0.0
        if top <= 0:
            return 0.0
        separation = max(0.0, min(1.0, (top - runner_up) / top))
        evidence = max(0.0, min(1.0, candidates[0].observations / float(max(repetitions, 1))))
        return round(0.6 * evidence + 0.4 * separation, 3)


hornet_calibration_wizard = HornetCalibrationWizard()
