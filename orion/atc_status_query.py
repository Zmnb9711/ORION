"""Bounded persistent ATC session and read-only controller-status proof."""

from __future__ import annotations

import re
import threading
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from orion.airport_atc_orchestration import AirportAtcOrchestrator
from orion.airport_surface import RunwayAvailability, RunwayState
from orion.airport_surface_runtime import AirportSurfaceCoordinator
from orion.airport_tower_runtime import AirportTowerController, TowerDepartureState
from orion.atc_core import (
    AtcSessionIdentity,
    ControllerAgency,
    ControllerAuthorityScope,
)
from orion.atc_operations import FreshnessClass
from orion.atc_service import AtcStatusSnapshot, VirtualAtcService
from orion.communication_contracts import (
    CommunicationDomain,
    CommunicationPriority,
    OperationalSemanticUnit,
    ProtectedProvenance,
    ProtectedValue,
    ProtectedValueKind,
)
from orion.golden_takeoff_vertical import GoldenTakeoffResult, GoldenTakeoffVertical
from orion.interaction_contracts import (
    CapabilityId,
    ContextReference,
    PresentationMode,
    SemanticFact,
    SemanticFactKind,
    SemanticInputIssue,
    SemanticInputStatus,
    SemanticResponse,
)
from orion.pilot_phraseology import PilotPhraseologyResolver
from orion.pilot_phraseology_catalog import build_pilot_phraseology_catalog
from orion.world_model_contracts import WorldFactAuthority


ATC_STATUS_CAPABILITY = CapabilityId("atc.status.current_flight_controller")
ATC_STATUS_CONTRACT = "atc_status_query"
ATC_STATUS_SEMANTIC_MEANING = "atc.current_flight_controller"


class AtcStatusIntentStatus(StrEnum):
    RECOGNIZED = "recognized"
    UNSUPPORTED = "unsupported"


class AtcStatusIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: AtcStatusIntentStatus
    language: str = Field(pattern=r"^(?:ru-RU|en-US)$")


class AtcStatusQueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: UUID | None = None
    facility_id: str | None = None
    controller_agency: ControllerAgency | None = None
    procedural_state: str | None = None
    authority_available: bool = False
    runtime_revision_before: int | None = None
    runtime_revision_after: int | None = None
    atc_truth_unchanged: bool = True
    provenance: ContextReference


class AtcStatusSemanticOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    result: AtcStatusQueryResult
    semantic_unit: OperationalSemanticUnit
    semantic_response: SemanticResponse
    final_text: str
    radio_entity_id: str


_RU_STATUS_FORMS = frozenset(
    {
        "какой диспетчер сейчас управляет моим полетом",
        "кто сейчас управляет моим полетом",
    }
)
_EN_STATUS_FORMS = frozenset(
    {
        "who currently controls my flight",
        "which controller currently controls my flight",
    }
)


def _canonicalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).strip().casefold().replace("ё", "е")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", " ", normalized)).strip()


def classify_atc_status_query(text: str) -> AtcStatusIntent:
    """Recognize only the approved whole-utterance RU/EN status forms."""

    canonical = _canonicalize(text)
    if canonical in _RU_STATUS_FORMS:
        return AtcStatusIntent(status=AtcStatusIntentStatus.RECOGNIZED, language="ru-RU")
    if canonical in _EN_STATUS_FORMS:
        return AtcStatusIntent(status=AtcStatusIntentStatus.RECOGNIZED, language="en-US")
    language = "ru-RU" if re.search(r"[А-Яа-яЁё]", text) else "en-US"
    return AtcStatusIntent(status=AtcStatusIntentStatus.UNSUPPORTED, language=language)


@dataclass(slots=True)
class _BoundAtcSession:
    """Internal binding record; authoritative state remains in VirtualAtcService."""

    main_session_id: str
    run_id: str
    identity: AtcSessionIdentity
    vertical: GoldenTakeoffVertical


class PersistentAtcSessionCoordinator:
    """Bind one bounded voice run to an existing Core-owned ATC session."""

    def __init__(self, service: VirtualAtcService | None = None) -> None:
        self.service = service or VirtualAtcService()
        self._lock = threading.RLock()
        self._bindings: dict[tuple[str, str], _BoundAtcSession] = {}

    @staticmethod
    def _key(main_session_id: str, run_id: str) -> tuple[str, str]:
        return main_session_id, run_id

    def get_or_create_takeoff_session(
        self,
        *,
        main_session_id: str,
        run_id: str,
        callsign: str,
        runway_id: str,
        facility_id: str,
    ) -> tuple[AtcSessionIdentity, GoldenTakeoffVertical, bool]:
        key = self._key(main_session_id, run_id)
        with self._lock:
            existing = self._bindings.get(key)
            if existing is not None:
                return existing.identity.model_copy(deep=True), existing.vertical, False

            identity = AtcSessionIdentity(
                session_id=uuid4(),
                mission_id=f"live-golden-controlled-{run_id[:16]}",
                aircraft_id=callsign,
                facility_id=facility_id,
            )
            self.service.open_session(
                identity,
                procedural_state=TowerDepartureState.HOLD_SHORT.value,
            )
            surface = AirportSurfaceCoordinator(self.service.core)
            tower = AirportTowerController(surface)
            orchestrator = AirportAtcOrchestrator(service=self.service, tower=tower)
            tower.assume_runway_control(
                identity.session_id,
                reason="controlled persistent ATC status proof",
            )
            orchestrator.assume_tower_local_traffic(
                identity.session_id,
                reason="Tower owns flight traffic for controlled takeoff proof",
            )
            tower.start_departure(session_id=identity.session_id, runway_id=runway_id)
            surface.runways.observe(
                RunwayState(
                    runway_id=runway_id,
                    availability=RunwayAvailability.CLEAR,
                    freshness=FreshnessClass.FRESH,
                    reason="controlled persistent ATC status proof",
                )
            )
            vertical = GoldenTakeoffVertical(
                tower,
                PilotPhraseologyResolver(build_pilot_phraseology_catalog()),
            )
            self._bindings[key] = _BoundAtcSession(
                main_session_id=main_session_id,
                run_id=run_id,
                identity=identity,
                vertical=vertical,
            )
            return identity.model_copy(deep=True), vertical, True

    def synchronize_takeoff_result(
        self,
        *,
        main_session_id: str,
        run_id: str,
        result: GoldenTakeoffResult,
    ) -> None:
        binding = self._require(main_session_id, run_id)
        decision = result.decision
        if decision is None or decision.final_departure_state is None:
            return
        current = self.service.status(binding.identity.session_id)
        state = decision.final_departure_state.value
        if current.procedural_state == state:
            return
        self.service.transition(
            binding.identity.session_id,
            state,
            reason="bounded takeoff decision synchronized to persistent ATC session",
        )

    def query_status(
        self,
        *,
        main_session_id: str,
        run_id: str,
        interaction_id: UUID,
        language: str,
    ) -> AtcStatusSemanticOutcome:
        binding = self._get(main_session_id, run_id)
        if binding is None:
            result = AtcStatusQueryResult(
                provenance=ContextReference(
                    context_type="voice_session",
                    reference_id=f"missing:{run_id[:32]}",
                )
            )
        else:
            result = self._read_status(binding)
        return adapt_atc_status_result(result, interaction_id=interaction_id, language=language)

    def release(self, *, main_session_id: str, run_id: str) -> UUID | None:
        key = self._key(main_session_id, run_id)
        with self._lock:
            binding = self._bindings.pop(key, None)
            if binding is None:
                return None
            if self.service.sessions.get(binding.identity.session_id) is not None:
                self.service.close_session(
                    binding.identity.session_id,
                    reason="bounded voice ATC session released",
                )
            return binding.identity.session_id

    def release_main_session(self, main_session_id: str) -> tuple[UUID, ...]:
        with self._lock:
            run_ids = [run_id for session_id, run_id in self._bindings if session_id == main_session_id]
        released = [
            self.release(main_session_id=main_session_id, run_id=run_id) for run_id in run_ids
        ]
        return tuple(item for item in released if item is not None)

    def bound_session_id(self, *, main_session_id: str, run_id: str) -> UUID | None:
        binding = self._get(main_session_id, run_id)
        return binding.identity.session_id if binding is not None else None

    def _read_status(self, binding: _BoundAtcSession) -> AtcStatusQueryResult:
        runtime_before = self.service.sessions.get(binding.identity.session_id)
        snapshot: AtcStatusSnapshot = self.service.status(binding.identity.session_id)
        runtime_after = self.service.sessions.get(binding.identity.session_id)
        owner = snapshot.authority.get(ControllerAuthorityScope.FLIGHT_TRAFFIC)
        before = runtime_before.model_dump(mode="json") if runtime_before is not None else None
        after = runtime_after.model_dump(mode="json") if runtime_after is not None else None
        return AtcStatusQueryResult(
            session_id=snapshot.session_id,
            facility_id=snapshot.facility_id,
            controller_agency=owner,
            procedural_state=snapshot.procedural_state,
            authority_available=owner is not None,
            runtime_revision_before=(
                runtime_before.revision if runtime_before is not None else None
            ),
            runtime_revision_after=(
                runtime_after.revision if runtime_after is not None else None
            ),
            atc_truth_unchanged=before == after,
            provenance=ContextReference(
                context_type="atc_status_snapshot",
                reference_id=str(snapshot.session_id),
            ),
        )

    def _get(self, main_session_id: str, run_id: str) -> _BoundAtcSession | None:
        with self._lock:
            return self._bindings.get(self._key(main_session_id, run_id))

    def _require(self, main_session_id: str, run_id: str) -> _BoundAtcSession:
        item = self._get(main_session_id, run_id)
        if item is None:
            raise KeyError("Persistent ATC session binding not found")
        return item


def adapt_atc_status_result(
    result: AtcStatusQueryResult,
    *,
    interaction_id: UUID,
    language: str,
) -> AtcStatusSemanticOutcome:
    values: list[ProtectedValue] = []
    facts: list[SemanticFact] = []
    unavailable: list[SemanticInputIssue] = []
    if result.controller_agency is not None:
        values.append(
            ProtectedValue(
                key="atc.controller_agency",
                kind=ProtectedValueKind.GENERIC,
                value=result.controller_agency.value,
            )
        )
        facts.append(
            SemanticFact(
                key="atc.controller_agency",
                value=result.controller_agency.value,
                kind=SemanticFactKind.AUTHORITATIVE,
                source=result.provenance,
            )
        )
    else:
        unavailable.append(
            SemanticInputIssue(
                key="atc.controller_agency",
                status=SemanticInputStatus.UNAVAILABLE,
                reason="flight_traffic_authority_unavailable",
                source=result.provenance,
            )
        )
    if result.procedural_state is not None:
        values.append(
            ProtectedValue(
                key="atc.procedural_state",
                kind=ProtectedValueKind.GENERIC,
                value=result.procedural_state,
            )
        )
        facts.append(
            SemanticFact(
                key="atc.procedural_state",
                value=result.procedural_state,
                kind=SemanticFactKind.AUTHORITATIVE,
                source=result.provenance,
            )
        )
    else:
        unavailable.append(
            SemanticInputIssue(
                key="atc.procedural_state",
                status=SemanticInputStatus.UNAVAILABLE,
                reason="active_atc_session_unavailable",
                source=result.provenance,
            )
        )
    if result.facility_id is not None:
        values.append(
            ProtectedValue(
                key="atc.facility_id",
                kind=ProtectedValueKind.GENERIC,
                value=result.facility_id,
            )
        )
        facts.append(
            SemanticFact(
                key="atc.facility_id",
                value=result.facility_id,
                kind=SemanticFactKind.AUTHORITATIVE,
                source=result.provenance,
            )
        )

    status = "available" if result.authority_available else "unavailable"
    provenance = (
        ProtectedProvenance(
            source=result.provenance,
            authority=WorldFactAuthority.AUTHORITATIVE,
            domain_origin=CommunicationDomain.ATC,
        ),
    )
    unit = OperationalSemanticUnit(
        unit_type="atc.status",
        semantic_meaning=ATC_STATUS_SEMANTIC_MEANING,
        domain=CommunicationDomain.ATC,
        priority=CommunicationPriority.ROUTINE,
        status=status,
        protected_values=tuple(values),
        provenance=provenance,
    )
    text = render_atc_status_information(result, language=language)
    semantic_response = SemanticResponse(
        interaction_id=interaction_id,
        capability=ATC_STATUS_CAPABILITY,
        presentation_mode=PresentationMode.VERBATIM,
        authoritative_facts=tuple(facts),
        unavailable_inputs=tuple(unavailable),
        verbatim_text=text,
    )
    entity_id = (
        f"orion.atc.{result.controller_agency.value}"
        if result.controller_agency is not None
        else "orion.atc.status"
    )
    return AtcStatusSemanticOutcome(
        result=result,
        semantic_unit=unit,
        semantic_response=semantic_response,
        final_text=text,
        radio_entity_id=entity_id,
    )


def render_atc_status_information(result: AtcStatusQueryResult, *, language: str) -> str:
    """Render a non-normative diagnostic statement with exact Core-bound values."""

    if result.session_id is None:
        return (
            "Диагностический статус ATC: активная ATC-сессия недоступна."
            if language == "ru-RU"
            else "ATC diagnostic status: no active ATC session is available."
        )
    phase = (result.procedural_state or "unavailable").replace("_", " ")
    if result.controller_agency is None:
        return (
            f"Диагностический статус ATC: владелец FLIGHT TRAFFIC недоступен. "
            f"Процедурная фаза: {phase}."
            if language == "ru-RU"
            else f"ATC diagnostic status: FLIGHT TRAFFIC owner is unavailable. "
            f"Procedural phase: {phase}."
        )
    controller = result.controller_agency.value.replace("_", " ")
    return (
        f"Диагностический статус ATC. Управление полётом: {controller}. "
        f"Процедурная фаза: {phase}."
        if language == "ru-RU"
        else f"ATC diagnostic status. Flight traffic controller: {controller}. "
        f"Procedural phase: {phase}."
    )
