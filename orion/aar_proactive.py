from __future__ import annotations

from pydantic import BaseModel

from orion.aar_closure import AarClosureAssessment, ClosureBand, compute_closure, spoken_closure
from orion.aar_guidance import AarInterceptGuidance, compute_intercept_guidance
from orion.aar_rendezvous import AarPhase, AarRendezvousService
from orion.aar_vertical import AarVerticalAssessment, VerticalBand, compute_vertical, spoken_vertical
from orion.mission_context import LiveMissionContext, build_live_mission_context


class AarProactiveUpdate(BaseModel):
    should_announce: bool = False
    spoken_text: str = ""
    reason: str | None = None
    phase: AarPhase
    guidance: AarInterceptGuidance | None = None
    closure: AarClosureAssessment | None = None
    vertical: AarVerticalAssessment | None = None


class AarProactiveMonitor:
    """Produces sparse, event-driven AAR callouts instead of continuous chatter."""

    HEADING_DELTA_DEG = 15.0
    ETA_DELTA_S = 45.0

    def __init__(self, rendezvous: AarRendezvousService) -> None:
        self._rendezvous = rendezvous
        self._last_phase = AarPhase.IDLE
        self._last_guidance: AarInterceptGuidance | None = None
        self._last_closure_band: ClosureBand | None = None
        self._last_vertical_band: VerticalBand | None = None

    def reset(self) -> None:
        self._last_phase = AarPhase.IDLE
        self._last_guidance = None
        self._last_closure_band = None
        self._last_vertical_band = None

    def poll(self, language: str = "en") -> AarProactiveUpdate:
        session = self._rendezvous.snapshot()
        if session.phase not in {AarPhase.RENDEZVOUS, AarPhase.JOIN_UP} or not session.tanker_unit_id:
            self._last_phase = session.phase
            self._last_guidance = None
            self._last_closure_band = None
            self._last_vertical_band = None
            return AarProactiveUpdate(phase=session.phase)

        context = build_live_mission_context()
        tanker = _active_tanker(context, session.tanker_unit_id)
        if not context.available or tanker is None:
            return AarProactiveUpdate(phase=session.phase)

        previous_phase = session.phase
        self._rendezvous._update_phase_from_range(tanker)
        session = self._rendezvous.snapshot()
        guidance = compute_intercept_guidance(context, tanker)
        closure = compute_closure(context, tanker)
        vertical = compute_vertical(context, tanker)

        if session.phase != previous_phase and session.phase == AarPhase.JOIN_UP:
            self._last_phase = session.phase
            self._last_guidance = guidance
            self._last_closure_band = closure.band if closure is not None else None
            self._last_vertical_band = vertical.band if vertical is not None else None
            text = f"{tanker.callsign}, переходим к join-up. Стабилизируйте сближение и готовьтесь к pre-contact." if language == "ru" else f"{tanker.callsign}, entering join-up. Stabilize closure and prepare for pre-contact."
            return AarProactiveUpdate(should_announce=True, spoken_text=text, reason="phase_transition", phase=session.phase, guidance=guidance, closure=closure, vertical=vertical)

        if session.phase == AarPhase.JOIN_UP:
            previous_vertical = self._last_vertical_band
            self._last_vertical_band = vertical.band if vertical is not None else None
            if vertical is not None and previous_vertical is not None and vertical.band != previous_vertical:
                self._last_phase = session.phase
                self._last_guidance = guidance
                self._last_closure_band = closure.band if closure is not None else None
                return AarProactiveUpdate(should_announce=True, spoken_text=_vertical_callout(vertical, tanker, language), reason=f"vertical_{vertical.band.value}", phase=session.phase, guidance=guidance, closure=closure, vertical=vertical)

            closure_reason = self._closure_change(closure)
            previous_band = self._last_closure_band
            self._last_closure_band = closure.band if closure is not None else None
            if closure_reason is not None and closure is not None and closure.band != previous_band:
                self._last_phase = session.phase
                self._last_guidance = guidance
                text = _closure_callout(closure, tanker, language)
                return AarProactiveUpdate(should_announce=True, spoken_text=text, reason=closure_reason, phase=session.phase, guidance=guidance, closure=closure, vertical=vertical)

        reason = self._guidance_change(guidance)
        self._last_phase = session.phase
        previous_guidance = self._last_guidance
        self._last_guidance = guidance
        if closure is not None and self._last_closure_band is None:
            self._last_closure_band = closure.band
        if vertical is not None and self._last_vertical_band is None:
            self._last_vertical_band = vertical.band
        if reason is None or guidance is None or previous_guidance is None:
            return AarProactiveUpdate(phase=session.phase, guidance=guidance, closure=closure, vertical=vertical)
        eta_min = guidance.eta_s / 60.0
        text = f"Обновление сближения: курс перехвата {guidance.intercept_heading_deg:.0f}, ETA {eta_min:.1f} минуты." if language == "ru" else f"Rendezvous update: intercept heading {guidance.intercept_heading_deg:.0f}, ETA {eta_min:.1f} minutes."
        return AarProactiveUpdate(should_announce=True, spoken_text=text, reason=reason, phase=session.phase, guidance=guidance, closure=closure, vertical=vertical)

    def _guidance_change(self, current: AarInterceptGuidance | None) -> str | None:
        if current is None or self._last_guidance is None:
            return None
        heading_delta = abs((current.intercept_heading_deg - self._last_guidance.intercept_heading_deg + 180.0) % 360.0 - 180.0)
        if heading_delta >= self.HEADING_DELTA_DEG:
            return "heading_change"
        if abs(current.eta_s - self._last_guidance.eta_s) >= self.ETA_DELTA_S:
            return "eta_change"
        return None

    def _closure_change(self, current: AarClosureAssessment | None) -> str | None:
        if current is None or self._last_closure_band is None or current.band == self._last_closure_band:
            return None
        return f"closure_{current.band.value}"


def _vertical_callout(vertical: AarVerticalAssessment, tanker, language: str) -> str:
    measured = spoken_vertical(vertical, tanker, language)
    if vertical.band == VerticalBand.HIGH:
        return f"Высоко, {measured}. Снижайтесь к высоте танкера." if language == "ru" else f"High, {measured}. Descend toward tanker altitude."
    if vertical.band == VerticalBand.LOW:
        return f"Низко, {measured}. Набирайте к высоте танкера." if language == "ru" else f"Low, {measured}. Climb toward tanker altitude."
    return f"Высота согласована, {measured}. Держать." if language == "ru" else f"Altitude matched, {measured}. Hold."


def _closure_callout(closure: AarClosureAssessment, tanker, language: str) -> str:
    measured = spoken_closure(closure, tanker, language)
    if closure.band == ClosureBand.EXCESSIVE:
        return f"Сближение слишком высокое, {measured}. Уменьшите скорость сближения." if language == "ru" else f"Closure excessive, {measured}. Reduce closure rate."
    if closure.band == ClosureBand.HIGH:
        return f"Сближение высокое, {measured}. Плавно уменьшайте." if language == "ru" else f"Closure high, {measured}. Ease the closure."
    if closure.band == ClosureBand.STABLE:
        return f"Сближение стабильное, {measured}. Держать." if language == "ru" else f"Closure stable, {measured}. Hold."
    if closure.band == ClosureBand.HOLD:
        return f"Скорости почти выровнены, {measured}. Держать." if language == "ru" else f"Speeds nearly matched, {measured}. Hold."
    return f"Началось расхождение, {measured}. Восстановите сближение." if language == "ru" else f"Now opening, {measured}. Re-establish closure."


def _active_tanker(context: LiveMissionContext, unit_id: str):
    return next((asset for asset in context.tankers if asset.unit_id == unit_id and asset.available), None)
