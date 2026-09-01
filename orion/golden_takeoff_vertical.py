"""Bounded offline Golden Conversational Vertical #1 for takeoff clearance.

The recognizer establishes only a narrow request intent.  Operational truth and
the clearance decision remain owned by the existing deterministic Tower runtime.
"""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orion.airport_surface import RunwayAvailability
from orion.airport_tower_runtime import (
    AirportTowerController,
    TowerDepartureState,
)
from orion.atc_core import (
    AtcSessionIdentity,
    ControllerAgency,
    ControllerAuthorityScope,
)
from orion.atc_operations import FreshnessClass, OperationalInstruction
from orion.communication_contracts import (
    CommunicationContext,
    CommunicationDomain,
    CommunicationPriority,
    CommunicationProfileId,
    OperationalSemanticUnit,
    ProtectedOperationalFragment,
    ProtectedProvenance,
    ProtectedValue,
    ProtectedValueKind,
)
from orion.dialogue import DialogueLanguage, detect_language
from orion.interaction_contracts import ContextReference
from orion.pilot_phraseology import (
    PilotPhraseologyResolver,
    PilotResolutionResult,
    PilotResolutionStatus,
)
from orion.world_model_contracts import WorldFactAuthority


class _GoldenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class TakeoffIntentKind(StrEnum):
    TAKEOFF_CLEARANCE_REQUEST = "takeoff_clearance_request"


class TakeoffIntentStatus(StrEnum):
    RECOGNIZED = "recognized"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"


class TakeoffDecisionStatus(StrEnum):
    GRANTED = "granted"
    HOLD = "hold"
    UNAVAILABLE = "unavailable"


class GoldenTakeoffStatus(StrEnum):
    GRANTED = "granted"
    HOLD = "hold"
    UNAVAILABLE = "unavailable"
    CLARIFICATION_REQUIRED = "clarification_required"
    UNSUPPORTED = "unsupported"


class TakeoffIntent(_GoldenModel):
    status: TakeoffIntentStatus
    language: str = Field(pattern=r"^(?:en-US|ru-RU)$")
    kind: TakeoffIntentKind | None = None
    matched_takeoff_cue: bool = False
    matched_request_cue: bool = False
    matched_conflict_cue: bool = False

    @model_validator(mode="after")
    def require_kind_only_for_recognized(self) -> Self:
        recognized = self.status is TakeoffIntentStatus.RECOGNIZED
        if recognized != (self.kind is not None):
            raise ValueError("only recognized intent may contain an intent kind")
        return self


class TakeoffAtcDecision(_GoldenModel):
    status: TakeoffDecisionStatus
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=80)
    session_id: str = Field(min_length=1, max_length=80)
    callsign: str = Field(min_length=1, max_length=160)
    runway_id: str = Field(min_length=1, max_length=80)
    initial_departure_state: TowerDepartureState | None = None
    final_departure_state: TowerDepartureState | None = None
    runway_availability: RunwayAvailability | None = None
    runway_freshness: FreshnessClass | None = None
    instruction: OperationalInstruction | None = None

    @model_validator(mode="after")
    def require_instruction_only_for_grant(self) -> Self:
        granted = self.status is TakeoffDecisionStatus.GRANTED
        if granted != (self.instruction is not None):
            raise ValueError("only a granted ATC decision may contain an instruction")
        if granted and self.final_departure_state is not TowerDepartureState.TAKEOFF_CLEARED:
            raise ValueError("granted decision must end in TAKEOFF_CLEARED")
        return self


class GoldenTakeoffResult(_GoldenModel):
    status: GoldenTakeoffStatus
    utterance: str = Field(min_length=1, max_length=1_000, repr=False)
    intent: TakeoffIntent
    decision: TakeoffAtcDecision | None = None
    semantic_unit: OperationalSemanticUnit | None = Field(default=None, repr=False)
    resolution: PilotResolutionResult | None = Field(default=None, repr=False)
    fragment: ProtectedOperationalFragment | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def require_bounded_result_shape(self) -> Self:
        if self.status is GoldenTakeoffStatus.UNSUPPORTED:
            if any(
                item is not None
                for item in (self.decision, self.semantic_unit, self.resolution, self.fragment)
            ):
                raise ValueError("unsupported input must stop before ATC and rendering")
            return self
        if self.status is GoldenTakeoffStatus.CLARIFICATION_REQUIRED:
            if self.decision is not None:
                raise ValueError("ambiguous input must not reach the ATC decision seam")
        elif self.decision is None:
            raise ValueError("recognized intent requires a typed ATC decision")
        if self.semantic_unit is None or self.resolution is None or self.fragment is None:
            raise ValueError("supported result requires complete semantic rendering chain")
        if self.resolution.status is not PilotResolutionStatus.RENDERED:
            raise ValueError("Golden result requires a rendered Pilot fragment")
        return self


_RU_TAKEOFF = re.compile(r"\bвзлет(?:а|у|ом|е|ать|аю|аем|аете|ают)?\b")
_RU_REQUEST = re.compile(r"\b(?:разреш|разрешите|можно|готов|готовы|запрашиваю|запрашиваем)\w*\b")
_RU_CONFLICT = re.compile(r"\b(?:не|отмена|отменяю|запрещено)\b")
_EN_TAKEOFF = re.compile(r"\b(?:takeoff|take-off|departure)\b")
_EN_REQUEST = re.compile(r"\b(?:request|requesting|ready|clearance|cleared|may|can)\b")
_EN_CONFLICT = re.compile(r"\b(?:not|cancel|canceling|cancelling|unable)\b")

# These are the already-approved bounded Golden forms, normalized for case,
# punctuation and whitespace.  Recognition is deliberately whole-utterance:
# cue presence still produces AMBIGUOUS below, but can never authorize the
# production deterministic bypass for a mixed or conversational utterance.
_PURE_TAKEOFF_FORMS = frozenset(
    {
        "разрешите взлет",
        "можно взлетать",
        "башня готов к взлету",
        "готов к взлету разрешите взлет",
        "запрашиваю разрешение на взлет",
        "tower request takeoff clearance",
        "ready for takeoff",
        "request takeoff",
        "tower viper 2-1 ready for departure",
    }
)


def classify_takeoff_intent(text: str) -> TakeoffIntent:
    """Classify only the bounded RU/EN takeoff-clearance request family."""

    normalized = unicodedata.normalize("NFKC", text).strip().casefold().replace("ё", "е")
    canonical = re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", " ", normalized)).strip()
    language = detect_language(normalized)
    if language is DialogueLanguage.RU:
        takeoff = _RU_TAKEOFF.search(normalized) is not None
        request = _RU_REQUEST.search(normalized) is not None
        conflict = _RU_CONFLICT.search(normalized) is not None
        language_id = "ru-RU"
    else:
        takeoff = _EN_TAKEOFF.search(normalized) is not None
        request = _EN_REQUEST.search(normalized) is not None
        conflict = _EN_CONFLICT.search(normalized) is not None
        language_id = "en-US"

    if canonical in _PURE_TAKEOFF_FORMS and takeoff and request and not conflict:
        return TakeoffIntent(
            status=TakeoffIntentStatus.RECOGNIZED,
            language=language_id,
            kind=TakeoffIntentKind.TAKEOFF_CLEARANCE_REQUEST,
            matched_takeoff_cue=True,
            matched_request_cue=True,
        )
    if takeoff or request or conflict:
        return TakeoffIntent(
            status=TakeoffIntentStatus.AMBIGUOUS,
            language=language_id,
            matched_takeoff_cue=takeoff,
            matched_request_cue=request,
            matched_conflict_cue=conflict,
        )
    return TakeoffIntent(
        status=TakeoffIntentStatus.UNSUPPORTED,
        language=language_id,
    )


class ExistingAtcTakeoffDecisionService:
    """Narrow adapter over the existing Tower state and runway truth."""

    def __init__(self, tower: AirportTowerController) -> None:
        self.tower = tower

    def decide(self, identity: AtcSessionIdentity) -> TakeoffAtcDecision:
        session_id = identity.session_id
        try:
            departure = self.tower._require_departure(session_id)
        except KeyError:
            raise RuntimeError(
                "Golden takeoff requires an existing Tower departure context"
            ) from None

        runway = self.tower.surface.runways.get(departure.runway_id)
        owner = self.tower.core.authority.get_owner(
            session_id, ControllerAuthorityScope.LANDING_AREA
        )
        common = {
            "identity": identity,
            "runway_id": departure.runway_id,
            "initial_state": departure.state,
            "runway_availability": runway.availability,
            "runway_freshness": runway.freshness,
        }
        if owner is None or owner.agency is not ControllerAgency.AIRPORT_TOWER:
            return self._decision(
                **common,
                status=TakeoffDecisionStatus.UNAVAILABLE,
                reason_code="tower_authority_missing",
            )
        if departure.state not in {
            TowerDepartureState.HOLD_SHORT,
            TowerDepartureState.LINE_UP_AND_WAIT,
        }:
            return self._decision(
                **common,
                status=TakeoffDecisionStatus.HOLD,
                reason_code="departure_state_blocks_clearance",
            )
        if runway.availability in {
            RunwayAvailability.UNKNOWN,
            RunwayAvailability.STALE,
        } or runway.freshness in {FreshnessClass.UNKNOWN, FreshnessClass.STALE}:
            return self._decision(
                **common,
                status=TakeoffDecisionStatus.UNAVAILABLE,
                reason_code="runway_context_unavailable",
            )
        if not runway.usable_for_positive_clearance:
            return self._decision(
                **common,
                status=TakeoffDecisionStatus.HOLD,
                reason_code="runway_not_clear",
            )
        reservation = self.tower.reservations.get(departure.runway_id)
        if reservation is not None and reservation.session_id != session_id:
            return self._decision(
                **common,
                status=TakeoffDecisionStatus.HOLD,
                reason_code="runway_reserved_for_other_session",
            )

        instruction = self.tower.clear_takeoff(
            session_id,
            reason="bounded natural-language takeoff clearance request",
        )
        final_state = self.tower._require_departure(session_id).state
        return self._decision(
            **common,
            status=TakeoffDecisionStatus.GRANTED,
            reason_code="existing_atc_takeoff_clearance_issued",
            final_state=final_state,
            instruction=instruction,
        )

    @staticmethod
    def _decision(
        identity: AtcSessionIdentity,
        *,
        status: TakeoffDecisionStatus,
        reason_code: str,
        runway_id: str = "unknown",
        initial_state: TowerDepartureState | None = None,
        final_state: TowerDepartureState | None = None,
        runway_availability: RunwayAvailability | None = None,
        runway_freshness: FreshnessClass | None = None,
        instruction: OperationalInstruction | None = None,
    ) -> TakeoffAtcDecision:
        return TakeoffAtcDecision(
            status=status,
            reason_code=reason_code,
            session_id=str(identity.session_id),
            callsign=identity.aircraft_id,
            runway_id=runway_id,
            initial_departure_state=initial_state,
            final_departure_state=final_state,
            runway_availability=runway_availability,
            runway_freshness=runway_freshness,
            instruction=instruction,
        )


def adapt_takeoff_decision(decision: TakeoffAtcDecision) -> OperationalSemanticUnit:
    """Convert an already-made deterministic ATC decision into protected semantics."""

    mapping = {
        TakeoffDecisionStatus.GRANTED: (
            "atc.takeoff_clearance_granted",
            "granted",
            "positive",
        ),
        TakeoffDecisionStatus.HOLD: ("atc.takeoff_hold", "hold", "negative"),
        TakeoffDecisionStatus.UNAVAILABLE: (
            "atc.takeoff_context_unavailable",
            "unavailable",
            None,
        ),
    }
    meaning, status, polarity = mapping[decision.status]
    return OperationalSemanticUnit(
        unit_type="atc.takeoff",
        semantic_meaning=meaning,
        domain=CommunicationDomain.ATC,
        priority=CommunicationPriority.IMPORTANT,
        status=status,
        polarity=polarity,
        protected_values=(
            ProtectedValue(
                key="atc.callsign",
                kind=ProtectedValueKind.CALLSIGN,
                value=decision.callsign,
            ),
            ProtectedValue(
                key="atc.runway_id",
                kind=ProtectedValueKind.RUNWAY,
                value=decision.runway_id,
            ),
        ),
        provenance=(_decision_provenance(decision.session_id),),
    )


def _clarification_unit(reference_id: str) -> OperationalSemanticUnit:
    return OperationalSemanticUnit(
        unit_type="general.response",
        semantic_meaning="general.say_again",
        domain=CommunicationDomain.GENERAL,
        priority=CommunicationPriority.ROUTINE,
        status="clarification_required",
        provenance=(_decision_provenance(reference_id, CommunicationDomain.GENERAL),),
    )


def _decision_provenance(
    reference_id: str,
    domain: CommunicationDomain = CommunicationDomain.ATC,
) -> ProtectedProvenance:
    return ProtectedProvenance(
        source=ContextReference(
            context_type="atc_decision",
            reference_id=reference_id,
        ),
        authority=WorldFactAuthority.AUTHORITATIVE,
        domain_origin=domain,
    )


class GoldenTakeoffVertical:
    def __init__(
        self,
        tower: AirportTowerController,
        resolver: PilotPhraseologyResolver,
        *,
        profile_id: CommunicationProfileId = CommunicationProfileId.FAP_RUSSIAN_ATC,
    ) -> None:
        self._decision_service = ExistingAtcTakeoffDecisionService(tower)
        self._resolver = resolver
        self.profile_id = profile_id

    def handle(
        self,
        *,
        identity: AtcSessionIdentity,
        utterance: str,
    ) -> GoldenTakeoffResult:
        intent = classify_takeoff_intent(utterance)
        if intent.status is TakeoffIntentStatus.UNSUPPORTED:
            return GoldenTakeoffResult(
                status=GoldenTakeoffStatus.UNSUPPORTED,
                utterance=utterance,
                intent=intent,
            )
        if intent.status is TakeoffIntentStatus.AMBIGUOUS:
            unit = _clarification_unit(str(identity.session_id))
            resolution = self._resolve(intent.language, unit)
            return GoldenTakeoffResult(
                status=GoldenTakeoffStatus.CLARIFICATION_REQUIRED,
                utterance=utterance,
                intent=intent,
                semantic_unit=unit,
                resolution=resolution,
                fragment=resolution.fragment,
            )

        decision = self._decision_service.decide(identity)
        return self.handle_recognized_intent(
            identity=identity,
            utterance=utterance,
            intent=intent,
            decision=decision,
        )

    def handle_recognized_intent(
        self,
        *,
        identity: AtcSessionIdentity,
        utterance: str,
        intent: TakeoffIntent,
        decision: TakeoffAtcDecision | None = None,
    ) -> GoldenTakeoffResult:
        """Continue from a validated provider intent; ATC still owns the decision."""

        if (
            intent.status is not TakeoffIntentStatus.RECOGNIZED
            or intent.kind is not TakeoffIntentKind.TAKEOFF_CLEARANCE_REQUEST
        ):
            raise ValueError("recognized takeoff intent is required")
        decided = decision or self._decision_service.decide(identity)
        unit = adapt_takeoff_decision(decided)
        resolution = self._resolve(intent.language, unit)
        return GoldenTakeoffResult(
            status=GoldenTakeoffStatus(decided.status.value),
            utterance=utterance,
            intent=intent,
            decision=decided,
            semantic_unit=unit,
            resolution=resolution,
            fragment=resolution.fragment,
        )

    def _resolve(
        self,
        language: str,
        unit: OperationalSemanticUnit,
    ) -> PilotResolutionResult:
        result = self._resolver.resolve(
            CommunicationContext(
                profile_id=self.profile_id,
                domain=unit.domain,
                input_language=language,
                operational_language=language,
                phraseology_snapshot_id=self._resolver.catalog.sha256,
                phraseology_version=self._resolver.catalog.version,
            ),
            unit,
        )
        if result.status is not PilotResolutionStatus.RENDERED:
            raise RuntimeError(
                f"Golden takeoff Pilot rendering failed closed: {result.status.value}"
            )
        return result
