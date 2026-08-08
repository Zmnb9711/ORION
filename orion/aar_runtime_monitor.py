from __future__ import annotations

from pydantic import BaseModel

from orion.aar_proactive import AarProactiveMonitor, AarProactiveUpdate
from orion.aar_rendezvous import AarPhase, aar_rendezvous
from orion.mission_context import build_live_mission_context


class AarRuntimeMonitorResult(BaseModel):
    update: AarProactiveUpdate
    active_tanker_present: bool


class AarRuntimeMonitor:
    """Runtime wrapper around sparse AAR guidance with explicit tanker-loss callouts."""

    def __init__(self) -> None:
        self._monitor = AarProactiveMonitor(aar_rendezvous)
        self._tanker_missing_announced = False

    def reset(self) -> None:
        self._monitor.reset()
        self._tanker_missing_announced = False

    def poll(self, language: str = "en") -> AarRuntimeMonitorResult:
        session = aar_rendezvous.snapshot()
        if session.phase not in {AarPhase.RENDEZVOUS, AarPhase.JOIN_UP, AarPhase.PRE_CONTACT} or session.tanker_unit_id is None:
            self._tanker_missing_announced = False
            return AarRuntimeMonitorResult(update=self._monitor.poll(language), active_tanker_present=False)

        context = build_live_mission_context()
        tanker_present = any(
            asset.unit_id == session.tanker_unit_id and asset.available
            for asset in context.tankers
        )
        if not context.available or not tanker_present:
            if not self._tanker_missing_announced:
                self._tanker_missing_announced = True
                text = (
                    "Активный танкер потерян из картины миссии. Сохраняйте безопасный полёт и ожидайте обновления."
                    if language == "ru"
                    else "Active tanker lost from the mission picture. Maintain safe flight and await an update."
                )
                update = AarProactiveUpdate(
                    should_announce=True,
                    spoken_text=text,
                    reason="active_tanker_lost",
                    phase=session.phase,
                )
                return AarRuntimeMonitorResult(update=update, active_tanker_present=False)
            return AarRuntimeMonitorResult(
                update=AarProactiveUpdate(phase=session.phase),
                active_tanker_present=False,
            )

        restored = self._tanker_missing_announced
        self._tanker_missing_announced = False
        if restored:
            text = (
                f"Танкер {session.tanker_callsign or session.tanker_unit_id} снова в картине миссии."
                if language == "ru"
                else f"Tanker {session.tanker_callsign or session.tanker_unit_id} is back in the mission picture."
            )
            update = AarProactiveUpdate(
                should_announce=True,
                spoken_text=text,
                reason="active_tanker_restored",
                phase=session.phase,
            )
            return AarRuntimeMonitorResult(update=update, active_tanker_present=True)

        return AarRuntimeMonitorResult(
            update=self._monitor.poll(language),
            active_tanker_present=True,
        )


aar_runtime_monitor = AarRuntimeMonitor()
