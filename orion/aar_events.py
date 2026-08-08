from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from orion.aar_rendezvous import AarPhase, AarSession, aar_rendezvous


class AarEventType(StrEnum):
    PRE_CONTACT = "pre_contact"
    CONTACT = "contact"
    DISCONNECT = "disconnect"
    REFUELING = "refueling"
    COMPLETE = "complete"


class AarEventSource(StrEnum):
    DCS = "dcs"
    MISSION_PACK = "mission_pack"
    TEST = "test"


class AarEvent(BaseModel):
    event_id: str = Field(min_length=1)
    event_type: AarEventType
    source: AarEventSource
    tanker_unit_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, object] = Field(default_factory=dict)


class AarEventResult(BaseModel):
    accepted: bool
    duplicate: bool = False
    event: AarEvent
    session: AarSession
    message: str


class AarEventProcessor:
    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._events: list[AarEvent] = []
        self._refueling_active = False

    def reset(self) -> None:
        self._seen.clear()
        self._events.clear()
        self._refueling_active = False

    def list(self) -> list[AarEvent]:
        return [event.model_copy(deep=True) for event in self._events]

    @property
    def refueling_active(self) -> bool:
        return self._refueling_active

    def ingest(self, event: AarEvent) -> AarEventResult:
        if event.event_id in self._seen:
            return AarEventResult(
                accepted=True,
                duplicate=True,
                event=event,
                session=aar_rendezvous.snapshot(),
                message="Duplicate AAR event ignored",
            )

        session = aar_rendezvous.snapshot()
        if session.tanker_unit_id is None:
            return AarEventResult(accepted=False, event=event, session=session, message="No active AAR session")
        if event.tanker_unit_id is not None and event.tanker_unit_id != session.tanker_unit_id:
            return AarEventResult(accepted=False, event=event, session=session, message="AAR event tanker does not match active session")

        try:
            self._apply(event)
        except ValueError as exc:
            return AarEventResult(accepted=False, event=event, session=aar_rendezvous.snapshot(), message=str(exc))

        self._seen.add(event.event_id)
        self._events.append(event.model_copy(deep=True))
        return AarEventResult(accepted=True, event=event, session=aar_rendezvous.snapshot(), message="AAR event accepted")

    def _apply(self, event: AarEvent) -> None:
        if event.event_type is AarEventType.PRE_CONTACT:
            aar_rendezvous.apply_confirmed_phase(AarPhase.PRE_CONTACT, event.tanker_unit_id)
            self._refueling_active = False
            return
        if event.event_type is AarEventType.CONTACT:
            aar_rendezvous.apply_confirmed_phase(AarPhase.CONTACT, event.tanker_unit_id)
            return
        if event.event_type is AarEventType.DISCONNECT:
            aar_rendezvous.apply_confirmed_phase(AarPhase.PRE_CONTACT, event.tanker_unit_id)
            self._refueling_active = False
            return
        if event.event_type is AarEventType.REFUELING:
            if aar_rendezvous.snapshot().phase is not AarPhase.CONTACT:
                raise ValueError("Refueling event requires confirmed CONTACT")
            self._refueling_active = True
            return
        if event.event_type is AarEventType.COMPLETE:
            aar_rendezvous.apply_confirmed_phase(AarPhase.COMPLETE, event.tanker_unit_id)
            self._refueling_active = False
            return
        raise ValueError(f"Unsupported AAR event: {event.event_type}")


aar_events = AarEventProcessor()
