from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from orion.fa18c_diagnostics_recorder import MappingCandidate, hornet_diagnostics_recorder


class CalibrationStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETE = "complete"
    NEEDS_RETRY = "needs_retry"


class CalibrationStep(BaseModel):
    key: str
    instruction_en: str
    instruction_ru: str
    repetitions: int = Field(default=3, ge=1, le=10)


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

    @property
    def active_step(self) -> CalibrationStep | None:
        if 0 <= self.current_step < len(self.steps):
            return self.steps[self.current_step]
        return None


DEFAULT_HORNET_STEPS = [
    CalibrationStep(key="tacan_power", instruction_en="Toggle TACAN power OFF to ON and back three times.", instruction_ru="Переключите питание TACAN OFF→ON→OFF три раза."),
    CalibrationStep(key="tacan_channel_tens", instruction_en="Change the TACAN tens selector back and forth three times.", instruction_ru="Измените десятки канала TACAN туда и обратно три раза."),
    CalibrationStep(key="tacan_channel_ones", instruction_en="Change the TACAN ones selector back and forth three times.", instruction_ru="Измените единицы канала TACAN туда и обратно три раза."),
    CalibrationStep(key="tacan_xy", instruction_en="Toggle TACAN X/Y three times.", instruction_ru="Переключите TACAN X/Y три раза."),
    CalibrationStep(key="comm1_selector", instruction_en="Move the COMM1 selector between two positions three times.", instruction_ru="Переключите селектор COMM1 между двумя положениями три раза."),
    CalibrationStep(key="comm2_selector", instruction_en="Move the COMM2 selector between two positions three times.", instruction_ru="Переключите селектор COMM2 между двумя положениями три раза."),
]


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
