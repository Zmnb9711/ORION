from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel

from orion.airport_surface import RunwayAvailability
from orion.airport_surface_runtime import AirportSurfaceCoordinator
from orion.airport_tower_runtime import AirportTowerController
from orion.atc_core import ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import OperationalInstruction, VoicePriority


class ApproachType(StrEnum):
    ILS = "ils"
    TACAN = "tacan"
    VISUAL = "visual"


class AirportArrivalState(StrEnum):
    ARRIVAL_CONTACT = "arrival_contact"
    ARRIVAL_CONTROL = "arrival_control"
    DESCENT_VECTORS = "descent_vectors"
    APPROACH_CONTROL = "approach_control"
    APPROACH_POSITIONING = "approach_positioning"
    APPROACH = "approach"
    FINAL = "final"
    TOWER = "tower"
    LANDING_CLEARED = "landing_cleared"
    TOUCHDOWN = "touchdown"
    ROLLOUT = "rollout"
    RUNWAY_VACATED = "runway_vacated"
    GROUND = "ground"
    GO_AROUND = "go_around"
    MISSED_APPROACH = "missed_approach"
    REPOSITION = "reposition"


class ArrivalClearance(BaseModel):
    runway_id: str
    approach_type: ApproachType
    heading_deg: int | None = None
    altitude_ft: int | None = None
    speed_kt: int | None = None
    direct_to: str | None = None
    frequency: str | None = None
    pressure_setting: str | None = None


class AirportArrivalSession(BaseModel):
    session_id: UUID
    runway_id: str
    state: AirportArrivalState = AirportArrivalState.ARRIVAL_CONTACT
    clearance: ArrivalClearance | None = None
    tower_handoff_id: UUID | None = None


class AirportArrivalRuntime:
    """Military-oriented fixed-airfield arrival/approach flow for DCS."""

    def __init__(self, surface: AirportSurfaceCoordinator | None = None) -> None:
        self.surface = surface or AirportSurfaceCoordinator()
        self.core = self.surface.core
        self.tower = AirportTowerController(self.surface)
        self._sessions: dict[UUID, AirportArrivalSession] = {}

    def start(
        self,
        *,
        session_id: UUID,
        runway_id: str,
        reason: str = "arrival contact established",
    ) -> AirportArrivalSession:
        if session_id in self._sessions:
            raise ValueError("Arrival session already exists")
        owner = self.core.authority.get_owner(session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
        if owner is None:
            self.core.claim_authority(
                session_id=session_id,
                scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
                agency=ControllerAgency.AIRPORT_APPROACH,
                reason=reason,
            )
        elif owner.agency is not ControllerAgency.AIRPORT_APPROACH:
            raise ValueError("Approach must own FLIGHT_TRAFFIC before arrival can start")
        session = AirportArrivalSession(session_id=session_id, runway_id=runway_id)
        self._sessions[session_id] = session
        self._record(session, reason)
        return session.model_copy(deep=True)

    def assume_arrival_control(self, session_id: UUID, *, reason: str) -> AirportArrivalSession:
        return self._transition(
            session_id,
            {AirportArrivalState.ARRIVAL_CONTACT},
            AirportArrivalState.ARRIVAL_CONTROL,
            reason,
        )

    def issue_descent_vectors(
        self,
        session_id: UUID,
        *,
        heading_deg: int | None = None,
        altitude_ft: int | None = None,
        speed_kt: int | None = None,
        direct_to: str | None = None,
        reason: str,
    ) -> OperationalInstruction:
        session = self._require(session_id)
        if session.state not in {
            AirportArrivalState.ARRIVAL_CONTROL,
            AirportArrivalState.DESCENT_VECTORS,
            AirportArrivalState.REPOSITION,
        }:
            raise ValueError("Descent/vector instructions are not valid from current arrival state")
        params = {
            key: value
            for key, value in {
                "heading_deg": heading_deg,
                "altitude_ft": altitude_ft,
                "speed_kt": speed_kt,
                "direct_to": direct_to,
            }.items()
            if value is not None
        }
        if not params:
            raise ValueError("At least one arrival instruction parameter is required")
        instruction = self.core.issue_instruction(
            OperationalInstruction(
                session_id=session_id,
                issuing_agency=ControllerAgency.AIRPORT_APPROACH,
                authority_scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
                semantic_action="arrival_vector",
                parameters=params,
                acknowledgement_required=True,
                voice_priority=VoicePriority.PROCEDURAL,
            )
        )
        session.state = AirportArrivalState.DESCENT_VECTORS
        self._sessions[session_id] = session
        self._record(session, reason)
        return instruction

    def enter_approach_control(self, session_id: UUID, *, reason: str) -> AirportArrivalSession:
        return self._transition(
            session_id,
            {
                AirportArrivalState.ARRIVAL_CONTROL,
                AirportArrivalState.DESCENT_VECTORS,
                AirportArrivalState.MISSED_APPROACH,
            },
            AirportArrivalState.APPROACH_CONTROL,
            reason,
        )

    def position_for_approach(self, session_id: UUID, *, reason: str) -> AirportArrivalSession:
        return self._transition(
            session_id,
            {AirportArrivalState.APPROACH_CONTROL, AirportArrivalState.REPOSITION},
            AirportArrivalState.APPROACH_POSITIONING,
            reason,
        )

    def clear_approach(
        self,
        session_id: UUID,
        *,
        approach_type: ApproachType,
        heading_deg: int | None = None,
        altitude_ft: int | None = None,
        speed_kt: int | None = None,
        direct_to: str | None = None,
        frequency: str | None = None,
        pressure_setting: str | None = None,
        reason: str,
    ) -> OperationalInstruction:
        session = self._require(session_id)
        if session.state is not AirportArrivalState.APPROACH_POSITIONING:
            raise ValueError("Approach clearance requires APPROACH_POSITIONING state")
        clearance = ArrivalClearance(
            runway_id=session.runway_id,
            approach_type=approach_type,
            heading_deg=heading_deg,
            altitude_ft=altitude_ft,
            speed_kt=speed_kt,
            direct_to=direct_to,
            frequency=frequency,
            pressure_setting=pressure_setting,
        )
        instruction = self.core.issue_instruction(
            OperationalInstruction(
                session_id=session_id,
                issuing_agency=ControllerAgency.AIRPORT_APPROACH,
                authority_scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
                semantic_action="approach_clearance",
                parameters=clearance.model_dump(mode="json", exclude_none=True),
                acknowledgement_required=True,
                voice_priority=VoicePriority.PROCEDURAL,
            )
        )
        session.clearance = clearance
        session.state = AirportArrivalState.APPROACH
        self._sessions[session_id] = session
        self._record(session, reason)
        return instruction

    def confirm_final(
        self,
        session_id: UUID,
        *,
        reason: str = "aircraft established on final",
    ) -> AirportArrivalSession:
        return self._transition(
            session_id,
            {AirportArrivalState.APPROACH},
            AirportArrivalState.FINAL,
            reason,
        )

    def begin_tower_handoff(
        self,
        session_id: UUID,
        *,
        reason: str,
        frequency: str | None = None,
    ) -> UUID:
        session = self._require(session_id)
        if session.state is not AirportArrivalState.FINAL:
            raise ValueError("Tower handoff requires FINAL state")
        if session.tower_handoff_id is not None:
            return session.tower_handoff_id
        handoff_id = self.core.acknowledgement_handoff(
            session_id=session_id,
            source=ControllerAgency.AIRPORT_APPROACH,
            destination=ControllerAgency.AIRPORT_TOWER,
            scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
            reason=reason,
        )
        if frequency is not None:
            self.core.history.record(
                session_id=session_id,
                event_type="airport_arrival_tower_frequency",
                reason=reason,
                source_agency=ControllerAgency.AIRPORT_APPROACH,
                related_id=handoff_id,
                details={"frequency": frequency},
            )
        session.tower_handoff_id = handoff_id
        self._sessions[session_id] = session
        return handoff_id

    def complete_tower_handoff(self, session_id: UUID, *, reason: str) -> AirportArrivalSession:
        session = self._require(session_id)
        if session.state is AirportArrivalState.TOWER:
            return session.model_copy(deep=True)
        if session.state is not AirportArrivalState.FINAL or session.tower_handoff_id is None:
            raise ValueError("Tower handoff is not ready to complete")
        self.core.complete_acknowledged_handoff(session.tower_handoff_id)
        landing_owner = self.core.authority.get_owner(session_id, ControllerAuthorityScope.LANDING_AREA)
        if landing_owner is None:
            self.tower.assume_runway_control(session_id, reason=reason)
        elif landing_owner.agency is not ControllerAgency.AIRPORT_TOWER:
            raise ValueError("Tower cannot accept arrival because LANDING_AREA is owned by another agency")
        self.tower.start_arrival(session_id=session_id, runway_id=session.runway_id)
        session.state = AirportArrivalState.TOWER
        self._sessions[session_id] = session
        self._record(session, reason)
        return session.model_copy(deep=True)

    def clear_landing(self, session_id: UUID, *, reason: str) -> OperationalInstruction:
        session = self._require(session_id)
        if session.state is not AirportArrivalState.TOWER:
            raise ValueError("Landing clearance requires Tower control")
        runway = self.surface.runways.require_positive_clearance_state(session.runway_id)
        if runway.availability is not RunwayAvailability.CLEAR:
            raise ValueError("Runway is not confirmed clear for landing")
        instruction = self.tower.clear_landing(session_id, reason=reason)
        session.state = AirportArrivalState.LANDING_CLEARED
        self._sessions[session_id] = session
        self._record(session, reason)
        return instruction

    def confirm_touchdown(
        self,
        session_id: UUID,
        *,
        reason: str = "touchdown physically confirmed",
    ) -> AirportArrivalSession:
        session = self._require(session_id)
        if session.state is not AirportArrivalState.LANDING_CLEARED:
            raise ValueError("Touchdown requires LANDING_CLEARED state")
        self.tower.begin_landing_attempt(session_id)
        session.state = AirportArrivalState.TOUCHDOWN
        self._sessions[session_id] = session
        self._record(session, reason)
        return session.model_copy(deep=True)

    def confirm_rollout(
        self,
        session_id: UUID,
        *,
        reason: str = "landing rollout observed",
    ) -> AirportArrivalSession:
        session = self._require(session_id)
        if session.state is not AirportArrivalState.TOUCHDOWN:
            raise ValueError("Rollout requires TOUCHDOWN state")
        self.tower.mark_rollout(session_id)
        session.state = AirportArrivalState.ROLLOUT
        self._sessions[session_id] = session
        self._record(session, reason)
        return session.model_copy(deep=True)

    def confirm_runway_vacated(
        self,
        session_id: UUID,
        *,
        reason: str = "runway vacated physically confirmed",
    ) -> AirportArrivalSession:
        session = self._require(session_id)
        if session.state is not AirportArrivalState.ROLLOUT:
            raise ValueError("Runway vacated requires ROLLOUT state")
        self.tower.mark_runway_vacated(session_id)
        session.state = AirportArrivalState.RUNWAY_VACATED
        self._sessions[session_id] = session
        self._record(session, reason)
        return session.model_copy(deep=True)

    def transfer_to_ground(self, session_id: UUID, *, reason: str) -> AirportArrivalSession:
        session = self._require(session_id)
        if session.state is not AirportArrivalState.RUNWAY_VACATED:
            raise ValueError("Ground transfer requires confirmed RUNWAY_VACATED state")
        owner = self.core.authority.get_owner(session_id, ControllerAuthorityScope.SURFACE_MOVEMENT)
        if owner is None:
            self.core.claim_authority(
                session_id=session_id,
                scope=ControllerAuthorityScope.SURFACE_MOVEMENT,
                agency=ControllerAgency.AIRPORT_GROUND,
                reason=reason,
            )
        elif owner.agency is not ControllerAgency.AIRPORT_GROUND:
            raise ValueError("SURFACE_MOVEMENT is owned by a non-Ground agency")
        session.state = AirportArrivalState.GROUND
        self._sessions[session_id] = session
        self._record(session, reason)
        return session.model_copy(deep=True)

    def go_around(self, session_id: UUID, *, reason: str) -> AirportArrivalSession:
        session = self._require(session_id)
        if session.state not in {
            AirportArrivalState.APPROACH,
            AirportArrivalState.FINAL,
            AirportArrivalState.TOWER,
            AirportArrivalState.LANDING_CLEARED,
        }:
            raise ValueError("Go-around is not valid from current arrival state")
        if session.state in {AirportArrivalState.TOWER, AirportArrivalState.LANDING_CLEARED}:
            self.tower.go_around(session_id, reason=reason)
            owner = self.core.authority.get_owner(session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
            if owner is not None and owner.agency is ControllerAgency.AIRPORT_TOWER:
                handoff_id = self.core.acknowledgement_handoff(
                    session_id=session_id,
                    source=ControllerAgency.AIRPORT_TOWER,
                    destination=ControllerAgency.AIRPORT_APPROACH,
                    scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
                    reason=reason,
                )
                self.core.complete_acknowledged_handoff(handoff_id)
        session.state = AirportArrivalState.GO_AROUND
        session.tower_handoff_id = None
        self._sessions[session_id] = session
        self._record(session, reason)
        return session.model_copy(deep=True)

    def enter_missed_approach(self, session_id: UUID, *, reason: str) -> AirportArrivalSession:
        return self._transition(
            session_id,
            {AirportArrivalState.GO_AROUND},
            AirportArrivalState.MISSED_APPROACH,
            reason,
        )

    def reposition(self, session_id: UUID, *, reason: str) -> AirportArrivalSession:
        return self._transition(
            session_id,
            {AirportArrivalState.MISSED_APPROACH, AirportArrivalState.APPROACH_CONTROL},
            AirportArrivalState.REPOSITION,
            reason,
        )

    def get(self, session_id: UUID) -> AirportArrivalSession | None:
        item = self._sessions.get(session_id)
        return item.model_copy(deep=True) if item else None

    def _transition(
        self,
        session_id: UUID,
        allowed: set[AirportArrivalState],
        target: AirportArrivalState,
        reason: str,
    ) -> AirportArrivalSession:
        session = self._require(session_id)
        if session.state not in allowed:
            raise ValueError(f"Cannot transition from {session.state.value} to {target.value}")
        session.state = target
        self._sessions[session_id] = session
        self._record(session, reason)
        return session.model_copy(deep=True)

    def _require(self, session_id: UUID) -> AirportArrivalSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError("Airport arrival session not found")
        return session.model_copy(deep=True)

    def _record(self, session: AirportArrivalSession, reason: str) -> None:
        if session.state is AirportArrivalState.GROUND:
            source = ControllerAgency.AIRPORT_GROUND
        elif session.state in {
            AirportArrivalState.TOWER,
            AirportArrivalState.LANDING_CLEARED,
            AirportArrivalState.TOUCHDOWN,
            AirportArrivalState.ROLLOUT,
            AirportArrivalState.RUNWAY_VACATED,
        }:
            source = ControllerAgency.AIRPORT_TOWER
        else:
            source = ControllerAgency.AIRPORT_APPROACH
        self.core.history.record(
            session_id=session.session_id,
            event_type="airport_arrival_state_changed",
            reason=reason,
            source_agency=source,
            details={"state": session.state.value, "runway_id": session.runway_id},
        )
