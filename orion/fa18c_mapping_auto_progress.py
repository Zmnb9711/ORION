from __future__ import annotations

from dataclasses import dataclass

from orion.fa18c_calibration_wizard import CalibrationStatus, hornet_calibration_wizard
from orion.fa18c_diagnostics_recorder import hornet_diagnostics_recorder
from orion.fa18c_mapping_notifications import hornet_mapping_notifier


@dataclass(frozen=True)
class AutoProgressEvent:
    advanced: bool
    completed: bool
    previous_step: str | None = None
    next_step: str | None = None
    confidence: float = 0.0
    notification_correlation_id: str | None = None


class HornetMappingAutoProgress:
    def __init__(self, minimum_confidence: float = 0.72) -> None:
        self.minimum_confidence = minimum_confidence
        self._last_event: AutoProgressEvent | None = None

    def on_diagnostics_packet(self) -> AutoProgressEvent | None:
        try:
            session = hornet_calibration_wizard.current()
        except RuntimeError:
            return None
        if session.status != CalibrationStatus.RUNNING or session.active_step is None:
            return None

        step = session.active_step
        try:
            report = hornet_diagnostics_recorder.report()
        except RuntimeError:
            return None

        marker_ids = set(report.markers.get(step.key, []))
        candidates = [candidate for candidate in report.candidates if candidate.argument_id in marker_ids]
        candidates.sort(key=lambda candidate: (-candidate.score, -candidate.observations, candidate.argument_id))
        confidence = hornet_calibration_wizard._confidence(candidates, step.repetitions)
        if not candidates or candidates[0].observations < step.repetitions or confidence < self.minimum_confidence:
            return None

        previous = step.key
        updated = hornet_calibration_wizard.evaluate_step(self.minimum_confidence)
        next_step = updated.active_step.key if updated.active_step else None
        notification = hornet_mapping_notifier.step_advanced(updated, previous)
        event = AutoProgressEvent(
            advanced=True,
            completed=updated.status == CalibrationStatus.COMPLETE,
            previous_step=previous,
            next_step=next_step,
            confidence=confidence,
            notification_correlation_id=notification.correlation_id,
        )
        self._last_event = event
        return event

    def last_event(self) -> AutoProgressEvent | None:
        return self._last_event

    def clear(self) -> None:
        self._last_event = None


hornet_mapping_auto_progress = HornetMappingAutoProgress()
