from __future__ import annotations

from enum import StrEnum
from threading import RLock

from pydantic import BaseModel, Field

from orion.aar_closure import compute_closure
from orion.aar_guidance import compute_intercept_guidance
from orion.aar_stability import evaluate_joinup_stability
from orion.aar_vertical import compute_vertical
from orion.coalition_units import spoken_altitude, spoken_distance, spoken_speed
from orion.mission_context import LiveMissionContext, SupportAsset, build_live_mission_context
from orion.mission_store import mission_store


class AarPhase(StrEnum):
    IDLE = "idle"
    RENDEZVOUS = "rendezvous"
    JOIN_UP = "join_up"
    PRE_CONTACT = "pre_contact"
    CONTACT = "contact"
    COMPLETE = "complete"
    ABORTED = "aborted"


class AarSession(BaseModel):
    mission_id: str | None = None
    phase: AarPhase = AarPhase.IDLE
    tanker_unit_id: str | None = None
    tanker_callsign: str | None = None


class AarResult(BaseModel):
    completed: bool
    spoken_text: str
    session: AarSession
    data: dict[str, object] = Field(default_factory=dict)


class AarRendezvousService:
    def __init__(self) -> None:
        self._lock = RLock()
        self._session = AarSession()
        self._mission_id: str | None = None

    def reset(self) -> None:
        with self._lock:
            self._session = AarSession()
            self._mission_id = None

    def snapshot(self) -> AarSession:
        self._sync_mission()
        with self._lock:
            return self._session.model_copy(deep=True)

    def apply_confirmed_phase(self, phase: AarPhase, tanker_unit_id: str | None = None) -> AarSession:
        self._sync_mission()
        with self._lock:
            if self._session.tanker_unit_id is None:
                raise ValueError("No active AAR session")
            if tanker_unit_id is not None and tanker_unit_id != self._session.tanker_unit_id:
                raise ValueError("AAR event tanker does not match active session")
            allowed: dict[AarPhase, set[AarPhase]] = {
                AarPhase.RENDEZVOUS: {AarPhase.JOIN_UP, AarPhase.PRE_CONTACT},
                AarPhase.JOIN_UP: {AarPhase.PRE_CONTACT},
                AarPhase.PRE_CONTACT: {AarPhase.CONTACT, AarPhase.JOIN_UP},
                AarPhase.CONTACT: {AarPhase.PRE_CONTACT, AarPhase.COMPLETE},
            }
            current = self._session.phase
            if phase == current:
                return self._session.model_copy(deep=True)
            if phase not in allowed.get(current, set()):
                raise ValueError(f"Invalid confirmed AAR transition: {current.value} -> {phase.value}")
            self._session.phase = phase
            return self._session.model_copy(deep=True)

    def execute(self, intent: str, transcript: str, context: LiveMissionContext | None = None) -> AarResult:
        self._sync_mission()
        language = _language(transcript)
        if intent == "aar_abort":
            with self._lock:
                self._session.phase = AarPhase.ABORTED
            return self._result(True, "Процедура дозаправки отменена." if language == "ru" else "Aerial refueling procedure aborted.")
        if intent == "aar_complete":
            with self._lock:
                self._session.phase = AarPhase.COMPLETE
            return self._result(True, "Дозаправка завершена." if language == "ru" else "Aerial refueling complete.")
        live_context = context if context is not None else build_live_mission_context()
        if not live_context.available:
            return self._result(False, "Данные Mission Bridge недоступны." if language == "ru" else "Mission Bridge data is unavailable.", {"issues": live_context.issues})
        if intent == "aar_start":
            tanker = _nearest_available_tanker(live_context)
            if tanker is None:
                return self._result(False, "Доступный танкер не найден." if language == "ru" else "No available tanker was found.")
            with self._lock:
                self._session = AarSession(mission_id=self._mission_id, phase=AarPhase.RENDEZVOUS, tanker_unit_id=tanker.unit_id, tanker_callsign=tanker.callsign)
                self._update_phase_from_range_locked(tanker)
            return self._brief(live_context, tanker, language, prefix="Начинаю сближение с" if language == "ru" else "Starting rendezvous with")
        with self._lock:
            tanker_unit_id = self._session.tanker_unit_id
        tanker = _session_tanker(live_context, tanker_unit_id)
        if tanker is None:
            return self._result(False, "Активный танкер потерян из контекста миссии." if language == "ru" else "The active tanker is no longer present in mission context.")
        if intent == "aar_pre_contact":
            closure = compute_closure(live_context, tanker)
            vertical = compute_vertical(live_context, tanker)
            stability = evaluate_joinup_stability(tanker, closure, vertical)
            with self._lock:
                phase = self._session.phase
            if phase != AarPhase.JOIN_UP or not stability.ready_for_precontact:
                text = "Pre-contact пока не разрешён: сначала стабилизируйте дистанцию, сближение и высоту." if language == "ru" else "Pre-contact is not ready yet: stabilize range, closure and altitude first."
                return self._result(False, text, {"precontact_readiness": stability.model_dump()})
            with self._lock:
                self._session.phase = AarPhase.PRE_CONTACT
            result = self._brief(live_context, tanker, language, prefix="Переходим к pre-contact с" if language == "ru" else "Proceeding to pre-contact with")
            result.data["precontact_readiness"] = stability.model_dump()
            return result
        if intent == "aar_contact":
            with self._lock:
                self._session.phase = AarPhase.CONTACT
            return self._brief(live_context, tanker, language, prefix="Contact с" if language == "ru" else "Contact with")
        self._update_phase_from_range(tanker)
        return self._brief(live_context, tanker, language, prefix="Текущий танкер" if language == "ru" else "Current tanker")

    def _update_phase_from_range(self, tanker: SupportAsset) -> None:
        self._sync_mission()
        with self._lock:
            self._update_phase_from_range_locked(tanker)

    def _update_phase_from_range_locked(self, tanker: SupportAsset) -> None:
        if tanker.distance_km is None or self._session.phase in {AarPhase.PRE_CONTACT, AarPhase.CONTACT, AarPhase.COMPLETE, AarPhase.ABORTED}:
            return
        distance_nm = tanker.distance_km / 1.852
        self._session.phase = AarPhase.JOIN_UP if distance_nm <= 3.0 else AarPhase.RENDEZVOUS

    def _brief(self, context: LiveMissionContext, tanker: SupportAsset, language: str, prefix: str) -> AarResult:
        parts = [f"{prefix} {tanker.callsign}."]
        if tanker.bearing_deg is not None and tanker.distance_km is not None:
            parts.append(f"Азимут {tanker.bearing_deg:.0f}, дальность {spoken_distance(tanker.distance_km, tanker.coalition, language)}." if language == "ru" else f"Bearing {tanker.bearing_deg:.0f}, range {spoken_distance(tanker.distance_km, tanker.coalition, language)}.")
        if tanker.altitude_m is not None:
            parts.append(f"Высота {spoken_altitude(tanker.altitude_m, tanker.coalition, language)}." if language == "ru" else f"Altitude {spoken_altitude(tanker.altitude_m, tanker.coalition, language)}.")
        if tanker.heading_deg is not None:
            parts.append(f"Курс {tanker.heading_deg:.0f}." if language == "ru" else f"Heading {tanker.heading_deg:.0f}.")
        if tanker.speed_mps is not None:
            parts.append(f"Скорость {spoken_speed(tanker.speed_mps, tanker.coalition, language)}." if language == "ru" else f"Speed {spoken_speed(tanker.speed_mps, tanker.coalition, language)}.")
        if tanker.frequency_mhz is not None:
            parts.append(f"Частота {tanker.frequency_mhz:.3f} мегагерц{(' ' + tanker.modulation) if tanker.modulation else ''}." if language == "ru" else f"Frequency {tanker.frequency_mhz:.3f} megahertz{(' ' + tanker.modulation) if tanker.modulation else ''}.")
        if tanker.tacan_channel is not None and tanker.tacan_band is not None:
            parts.append(f"TACAN {tanker.tacan_channel} {tanker.tacan_band}.")
        guidance = None
        with self._lock:
            phase = self._session.phase
        if phase in {AarPhase.RENDEZVOUS, AarPhase.JOIN_UP}:
            guidance = compute_intercept_guidance(context, tanker)
            if guidance is not None:
                distance = spoken_distance(guidance.intercept_distance_km, tanker.coalition, language)
                minutes = guidance.eta_s / 60.0
                if language == "ru":
                    parts.append(f"Рекомендуемый курс перехвата {guidance.intercept_heading_deg:.0f}, ETA {minutes:.1f} минуты, путь до точки встречи {distance}.")
                else:
                    parts.append(f"Recommended intercept heading {guidance.intercept_heading_deg:.0f}, ETA {minutes:.1f} minutes, distance to rendezvous {distance}.")
        data: dict[str, object] = {"phase": phase.value, "tanker": tanker.model_dump(mode="json"), "intercept_guidance": guidance.model_dump() if guidance is not None else None}
        return self._result(True, " ".join(parts), data)

    def _result(self, completed: bool, text: str, data: dict[str, object] | None = None) -> AarResult:
        return AarResult(completed=completed, spoken_text=text, session=self.snapshot(), data=data or {})

    def _sync_mission(self) -> None:
        snapshot = mission_store.get()
        mission_id = snapshot.mission_id if snapshot is not None else None
        if mission_id is None:
            return
        with self._lock:
            if self._mission_id is None:
                self._mission_id = mission_id
                if self._session.phase is not AarPhase.IDLE:
                    self._session.mission_id = mission_id
                return
            if mission_id != self._mission_id:
                self._mission_id = mission_id
                self._session = AarSession(mission_id=mission_id)


def _nearest_available_tanker(context: LiveMissionContext) -> SupportAsset | None:
    assets = [a for a in context.tankers if a.available and a.aar_available is not False]
    if not assets:
        return None
    ranged = [a for a in assets if a.distance_km is not None]
    return min(ranged, key=lambda a: a.distance_km or 0.0) if ranged else assets[0]


def _session_tanker(context: LiveMissionContext, unit_id: str | None) -> SupportAsset | None:
    if unit_id is None:
        return None
    return next((a for a in context.tankers if a.unit_id == unit_id and a.available), None)


def _language(text: str) -> str:
    return "ru" if any("а" <= c.casefold() <= "я" or c.casefold() == "ё" for c in text) else "en"


aar_rendezvous = AarRendezvousService()
