from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from orion.aar_guidance import compute_intercept_guidance
from orion.coalition_units import spoken_altitude, spoken_distance, spoken_speed
from orion.mission_context import LiveMissionContext, SupportAsset, build_live_mission_context


class AarPhase(StrEnum):
    IDLE = "idle"
    RENDEZVOUS = "rendezvous"
    JOIN_UP = "join_up"
    PRE_CONTACT = "pre_contact"
    CONTACT = "contact"
    COMPLETE = "complete"
    ABORTED = "aborted"


class AarSession(BaseModel):
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
        self._session = AarSession()

    def reset(self) -> None:
        self._session = AarSession()

    def snapshot(self) -> AarSession:
        return self._session.model_copy(deep=True)

    def execute(self, intent: str, transcript: str) -> AarResult:
        language = _language(transcript)
        if intent == "aar_abort":
            self._session.phase = AarPhase.ABORTED
            return self._result(True, "Процедура дозаправки отменена." if language == "ru" else "Aerial refueling procedure aborted.")
        if intent == "aar_complete":
            self._session.phase = AarPhase.COMPLETE
            return self._result(True, "Дозаправка завершена." if language == "ru" else "Aerial refueling complete.")

        context = build_live_mission_context()
        if not context.available:
            return self._result(False, "Данные Mission Bridge недоступны." if language == "ru" else "Mission Bridge data is unavailable.", {"issues": context.issues})

        if intent == "aar_start":
            tanker = _nearest_available_tanker(context)
            if tanker is None:
                return self._result(False, "Доступный танкер не найден." if language == "ru" else "No available tanker was found.")
            self._session = AarSession(phase=AarPhase.RENDEZVOUS, tanker_unit_id=tanker.unit_id, tanker_callsign=tanker.callsign)
            self._update_phase_from_range(tanker)
            return self._brief(context, tanker, language, prefix="Начинаю сближение с" if language == "ru" else "Starting rendezvous with")

        tanker = _session_tanker(context, self._session.tanker_unit_id)
        if tanker is None:
            return self._result(False, "Активный танкер потерян из контекста миссии." if language == "ru" else "The active tanker is no longer present in mission context.")

        if intent == "aar_pre_contact":
            self._session.phase = AarPhase.PRE_CONTACT
            return self._brief(context, tanker, language, prefix="Переходим к pre-contact с" if language == "ru" else "Proceeding to pre-contact with")
        if intent == "aar_contact":
            self._session.phase = AarPhase.CONTACT
            return self._brief(context, tanker, language, prefix="Contact с" if language == "ru" else "Contact with")

        self._update_phase_from_range(tanker)
        return self._brief(context, tanker, language, prefix="Текущий танкер" if language == "ru" else "Current tanker")

    def _update_phase_from_range(self, tanker: SupportAsset) -> None:
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
        if self._session.phase in {AarPhase.RENDEZVOUS, AarPhase.JOIN_UP}:
            guidance = compute_intercept_guidance(context, tanker)
            if guidance is not None:
                distance = spoken_distance(guidance.intercept_distance_km, tanker.coalition, language)
                minutes = guidance.eta_s / 60.0
                if language == "ru":
                    parts.append(f"Рекомендуемый курс перехвата {guidance.intercept_heading_deg:.0f}, ETA {minutes:.1f} минуты, путь до точки встречи {distance}.")
                else:
                    parts.append(f"Recommended intercept heading {guidance.intercept_heading_deg:.0f}, ETA {minutes:.1f} minutes, distance to rendezvous {distance}.")

        data: dict[str, object] = {
            "phase": self._session.phase.value,
            "tanker": tanker.model_dump(mode="json"),
            "intercept_guidance": guidance.model_dump() if guidance is not None else None,
        }
        return self._result(True, " ".join(parts), data)

    def _result(self, completed: bool, text: str, data: dict[str, object] | None = None) -> AarResult:
        return AarResult(completed=completed, spoken_text=text, session=self.snapshot(), data=data or {})


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
