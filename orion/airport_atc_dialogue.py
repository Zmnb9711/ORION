from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from orion.aerodrome_information import AerodromePressureObservation
from orion.airport_arrival_orchestration import AirportArrivalOrchestrator
from orion.airport_arrival_request_controller import AirportArrivalRequestController, ArrivalRequestAction
from orion.airport_arrival_requests import ArrivalRequestIntent, classify_arrival_request
from orion.airport_arrival_runtime import AirportArrivalRuntime
from orion.airport_surface_runtime import AirportSurfaceCoordinator
from orion.atc_service import VirtualAtcService
from orion.atc_service import virtual_atc
from orion.dialogue import DialogueLanguage, detect_language


class AtcDialogueDomain(StrEnum):
    AUTO = "auto"
    ARRIVAL = "arrival"
    GROUND = "ground"
    TOWER = "tower"
    DEPARTURE = "departure"
    CARRIER = "carrier"


class AtcDialogueRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    domain: AtcDialogueDomain = AtcDialogueDomain.AUTO
    language: DialogueLanguage = DialogueLanguage.AUTO
    altitude_ft: int | None = Field(default=None, ge=-2000, le=100000)
    heading_deg: int | None = Field(default=None, ge=0, le=359)
    pressure: AerodromePressureObservation | None = None


class AtcDialogueResult(BaseModel):
    session_id: UUID
    domain: AtcDialogueDomain
    language: DialogueLanguage
    intent: str
    action: str
    procedural_state: str
    reply: str
    details: dict[str, str | int | float] = Field(default_factory=dict)
    requires_parameter: bool = False


class AirportAtcDialogueGateway:
    """Session-aware natural-language entry point for airport ATC domains."""

    def __init__(self, *, service: VirtualAtcService, arrival: AirportArrivalRuntime, arrival_orchestrator: AirportArrivalOrchestrator) -> None:
        if service.core is not arrival.core or service.core is not arrival_orchestrator.core:
            raise ValueError("ATC dialogue gateway requires one shared ATC core")
        self.service = service
        self.arrival = arrival
        self.arrival_orchestrator = arrival_orchestrator
        self.arrival_requests = AirportArrivalRequestController(arrival)

    def handle(self, session_id: UUID, request: AtcDialogueRequest) -> AtcDialogueResult:
        self.service.status(session_id)
        language = detect_language(request.text) if request.language is DialogueLanguage.AUTO else request.language
        domain = self._resolve_domain(session_id, request)
        if domain is not AtcDialogueDomain.ARRIVAL:
            return AtcDialogueResult(
                session_id=session_id,
                domain=domain,
                language=language,
                intent="unknown",
                action="domain_not_yet_wired",
                procedural_state=self.service.status(session_id).procedural_state,
                reply=self._pending_reply(language, domain),
            )
        return self._handle_arrival(session_id, request, language)

    def _resolve_domain(self, session_id: UUID, request: AtcDialogueRequest) -> AtcDialogueDomain:
        if request.domain is not AtcDialogueDomain.AUTO:
            return request.domain
        if self.arrival.get(session_id) is not None:
            return AtcDialogueDomain.ARRIVAL
        state = self.service.status(session_id).procedural_state.casefold()
        if any(marker in state for marker in ("arrival", "approach", "final", "landing", "go_around", "missed", "reposition")):
            return AtcDialogueDomain.ARRIVAL
        if "ground" in state or "taxi" in state:
            return AtcDialogueDomain.GROUND
        if "tower" in state or "runway" in state:
            return AtcDialogueDomain.TOWER
        if "depart" in state or "climb" in state:
            return AtcDialogueDomain.DEPARTURE
        if classify_arrival_request(request.text).intent is not ArrivalRequestIntent.UNKNOWN:
            return AtcDialogueDomain.ARRIVAL
        return AtcDialogueDomain.AUTO

    def _handle_arrival(self, session_id: UUID, request: AtcDialogueRequest, language: DialogueLanguage) -> AtcDialogueResult:
        classified = classify_arrival_request(request.text)
        if self.arrival.get(session_id) is None:
            raise KeyError("Airport arrival session not found")
        if classified.intent is ArrivalRequestIntent.GO_AROUND:
            session = self.arrival_orchestrator.go_around_to_approach(session_id, reason=classified.raw_text)
            return AtcDialogueResult(
                session_id=session_id,
                domain=AtcDialogueDomain.ARRIVAL,
                language=language,
                intent=classified.intent.value,
                action=ArrivalRequestAction.GO_AROUND.value,
                procedural_state=self.service.status(session_id).procedural_state,
                reply=("Уход на второй принят. Управление снова у Approach." if language is DialogueLanguage.RU else "Go-around acknowledged. Approach has control again."),
                details={"arrival_state": session.state.value},
            )
        result = self.arrival_requests.handle(
            session_id=session_id,
            text=request.text,
            altitude_ft=request.altitude_ft,
            heading_deg=request.heading_deg,
            pressure=request.pressure,
        )
        return AtcDialogueResult(
            session_id=session_id,
            domain=AtcDialogueDomain.ARRIVAL,
            language=language,
            intent=result.intent.value,
            action=result.action.value,
            procedural_state=self.service.status(session_id).procedural_state,
            reply=self._arrival_reply(language, result.action, result.details),
            details=result.details,
            requires_parameter=result.action is ArrivalRequestAction.NEEDS_PARAMETER,
        )

    @staticmethod
    def _arrival_reply(language: DialogueLanguage, action: ArrivalRequestAction, details: dict[str, str | int | float]) -> str:
        ru = language is DialogueLanguage.RU
        if action is ArrivalRequestAction.ARRIVAL_CONTROL:
            return "Approach принял вас. Продолжайте по указаниям." if ru else "Approach has you. Continue as instructed."
        if action is ArrivalRequestAction.APPROACH_CHANGED:
            approach = details.get("approach_type", "approach")
            return f"Тип захода изменён: {approach}." if ru else f"Approach type changed to {approach}."
        if action is ArrivalRequestAction.VECTOR_ISSUED:
            return "Указание по векторению выдано." if ru else "Vectoring instruction issued."
        if action is ArrivalRequestAction.INFORMATION:
            return "Аэродромная информация подготовлена." if ru else "Aerodrome information is available."
        if action is ArrivalRequestAction.RUNWAY_REPORT:
            return "Доклад о полосе принят." if ru else "Runway report received."
        if action is ArrivalRequestAction.NEEDS_PARAMETER:
            return "Нужен дополнительный параметр." if ru else "An additional parameter is required."
        return "Не понял запрос Approach. Уточните." if ru else "Approach request not understood. Please clarify."

    @staticmethod
    def _pending_reply(language: DialogueLanguage, domain: AtcDialogueDomain) -> str:
        return (f"Домен ATC {domain.value} ещё не подключён к общему диалоговому шлюзу." if language is DialogueLanguage.RU else f"ATC domain {domain.value} is not yet wired into the common dialogue gateway.")


# One canonical application-level gateway shared by HTTP and realtime tools.
_surface = AirportSurfaceCoordinator(virtual_atc.core)
_arrival = AirportArrivalRuntime(_surface)
_arrival_orchestration = AirportArrivalOrchestrator(
    service=virtual_atc,
    arrival=_arrival,
)
airport_atc_dialogue = AirportAtcDialogueGateway(
    service=virtual_atc,
    arrival=_arrival,
    arrival_orchestrator=_arrival_orchestration,
)
