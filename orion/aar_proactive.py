from __future__ import annotations

from pydantic import BaseModel

from orion.aar_guidance import AarInterceptGuidance, compute_intercept_guidance
from orion.aar_rendezvous import AarPhase, AarRendezvousService
from orion.mission_context import LiveMissionContext, build_live_mission_context


class AarProactiveUpdate(BaseModel):
    should_announce: bool = False
    spoken_text: str = ""
    reason: str | None = None
    phase: AarPhase
    guidance: AarInterceptGuidance | None = None


class AarProactiveMonitor:
    """Produces sparse, event-driven AAR callouts instead of continuous chatter."""

    HEADING_DELTA_DEG = 15.0
    ETA_DELTA_S = 45.0

    def __init__(self, rendezvous: AarRendezvousService) -> None:
        self._rendezvous = rendezvous
        self._last_phase = AarPhase.IDLE
        self._last_guidance: AarInterceptGuidance | None = None

    def reset(self) -> None:
        self._last_phase = AarPhase.IDLE
        self._last_guidance = None

    def poll(self, language: str = "en") -> AarProactiveUpdate:
        session = self._rendezvous.snapshot()
        if session.phase not in {AarPhase.RENDEZVOUS, AarPhase.JOIN_UP} or not session.tanker_unit_id:
            self._last_phase = session.phase
            self._last_guidance = None
            return AarProactiveUpdate(phase=session.phase)

        context = build_live_mission_context()
        tanker = _active_tanker(context, session.tanker_unit_id)
        if not context.available or tanker is None:
            return AarProactiveUpdate(phase=session.phase)

        previous_phase = session.phase
        self._rendezvous._update_phase_from_range(tanker)
        session = self._rendezvous.snapshot()
        guidance = compute_intercept_guidance(context, tanker)

        if session.phase != previous_phase and session.phase == AarPhase.JOIN_UP:
            self._last_phase = session.phase
            self._last_guidance = guidance
            text = (
                f"{tanker.callsign}, переходим к join-up. Стабилизируйте сближение и готовьтесь к pre-contact."
                if language == "ru"
                else f"{tanker.callsign}, entering join-up. Stabilize closure and prepare for pre-contact."
            )
            return AarProactiveUpdate(should_announce=True, spoken_text=text, reason="phase_transition", phase=session.phase, guidance=guidance)

        reason = self._guidance_change(guidance)
        self._last_phase = session.phase
        if reason is None:
            if guidance is not None and self._last_guidance is None:
                self._last_guidance = guidance
            return AarProactiveUpdate(phase=session.phase, guidance=guidance)

        self._last_guidance = guidance
        if guidance is None:
            return AarProactiveUpdate(phase=session.phase)
        eta_min = guidance.eta_s / 60.0
        text = (
            f"Обновление сближения: курс перехвата {guidance.intercept_heading_deg:.0f}, ETA {eta_min:.1f} минуты."
            if language == "ru"
            else f"Rendezvous update: intercept heading {guidance.intercept_heading_deg:.0f}, ETA {eta_min:.1f} minutes."
        )
        return AarProactiveUpdate(should_announce=True, spoken_text=text, reason=reason, phase=session.phase, guidance=guidance)

    def _guidance_change(self, current: AarInterceptGuidance | None) -> str | None:
        if current is None or self._last_guidance is None:
            return None
        heading_delta = abs((current.intercept_heading_deg - self._last_guidance.intercept_heading_deg + 180.0) % 360.0 - 180.0)
        if heading_delta >= self.HEADING_DELTA_DEG:
            return "heading_change"
        if abs(current.eta_s - self._last_guidance.eta_s) >= self.ETA_DELTA_S:
            return "eta_change"
        return None


def _active_tanker(context: LiveMissionContext, unit_id: str):
    return next((asset for asset in context.tankers if asset.unit_id == unit_id and asset.available), None)
