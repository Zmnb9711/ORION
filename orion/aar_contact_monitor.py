from __future__ import annotations

from pydantic import BaseModel

from orion.aar_closure import AarClosureAssessment, compute_closure
from orion.aar_contact_supervision import AarContactSupervision, evaluate_contact_supervision
from orion.aar_rendezvous import AarPhase, AarRendezvousService
from orion.aar_vertical import AarVerticalAssessment, compute_vertical
from orion.mission_context import build_live_mission_context


class AarContactUpdate(BaseModel):
    should_announce: bool = False
    spoken_text: str = ""
    reason: str | None = None
    phase: AarPhase
    supervision: AarContactSupervision | None = None
    closure: AarClosureAssessment | None = None
    vertical: AarVerticalAssessment | None = None


class AarContactMonitor:
    """Supervise an already-confirmed CONTACT state without inferring physical contact."""

    def __init__(self, rendezvous: AarRendezvousService) -> None:
        self._rendezvous = rendezvous
        self._last_stable: bool | None = None

    def reset(self) -> None:
        self._last_stable = None

    def poll(self, language: str = "en") -> AarContactUpdate:
        session = self._rendezvous.snapshot()
        if session.phase != AarPhase.CONTACT or not session.tanker_unit_id:
            self._last_stable = None
            return AarContactUpdate(phase=session.phase)

        context = build_live_mission_context()
        if not context.available:
            return AarContactUpdate(phase=session.phase)
        tanker = next(
            (asset for asset in context.tankers if asset.unit_id == session.tanker_unit_id and asset.available),
            None,
        )
        if tanker is None:
            return AarContactUpdate(phase=session.phase)

        closure = compute_closure(context, tanker)
        vertical = compute_vertical(context, tanker)
        supervision = evaluate_contact_supervision(tanker, closure, vertical)
        previous = self._last_stable
        self._last_stable = supervision.stable

        if previous is None or previous == supervision.stable:
            return AarContactUpdate(
                phase=session.phase,
                supervision=supervision,
                closure=closure,
                vertical=vertical,
            )

        if supervision.stable:
            text = (
                f"{tanker.callsign}, параметры контакта восстановлены. Держать."
                if language == "ru"
                else f"{tanker.callsign}, contact parameters restored. Hold."
            )
            reason = "contact_stable_restored"
        else:
            detail = _detail(supervision, language)
            text = (
                f"Контакт нестабилен: {detail}. Рекомендую disconnect и повторный заход."
                if language == "ru"
                else f"Contact unstable: {detail}. Recommend disconnect and re-contact."
            )
            reason = "contact_degraded"

        return AarContactUpdate(
            should_announce=True,
            spoken_text=text,
            reason=reason,
            phase=session.phase,
            supervision=supervision,
            closure=closure,
            vertical=vertical,
        )


def _detail(supervision: AarContactSupervision, language: str) -> str:
    labels_ru = {
        "contact_range_degraded": "дистанция",
        "contact_closure_degraded": "скорость сближения",
        "contact_vertical_degraded": "высота",
    }
    labels_en = {
        "contact_range_degraded": "range",
        "contact_closure_degraded": "closure",
        "contact_vertical_degraded": "altitude",
    }
    labels = labels_ru if language == "ru" else labels_en
    return ", ".join(labels.get(reason, reason) for reason in supervision.reasons)
