from uuid import uuid4

import pytest

from orion.airport_runway_coordination import (
    AirportTowerBoundaryController,
    RunwayOperationType,
    RunwayReservationManager,
)
from orion.airport_surface import RunwayAvailability, RunwayState
from orion.atc_core import ControllerAgency, ControllerAuthorityScope
from orion.atc_operations import CommitmentState, FreshnessClass
from orion.atc_runtime import AtcCoreFlow


def clear_runway(runway_id: str = "09") -> RunwayState:
    return RunwayState(
        runway_id=runway_id,
        availability=RunwayAvailability.CLEAR,
        freshness=FreshnessClass.FRESH,
        reason="fresh runway observation",
    )


def test_crossing_and_takeoff_conflict_on_same_runway_resource() -> None:
    core = AtcCoreFlow()
    reservations = RunwayReservationManager(core)
    tower = AirportTowerBoundaryController(reservations)
    crossing_session = uuid4()
    takeoff_session = uuid4()

    tower.assume_runway_authority(crossing_session, reason="Tower controls runway")
    tower.assume_runway_authority(takeoff_session, reason="Tower controls runway")
    tower.reserve_operation(
        session_id=crossing_session,
        runway_id="09",
        operation=RunwayOperationType.CROSSING,
        runway_state=clear_runway(),
        reason="cross runway 09",
    )

    with pytest.raises(ValueError, match="already reserved"):
        tower.reserve_operation(
            session_id=takeoff_session,
            runway_id="09",
            operation=RunwayOperationType.TAKEOFF,
            runway_state=clear_runway(),
            reason="depart runway 09",
        )


def test_unknown_runway_blocks_all_positive_operation_reservations() -> None:
    tower = AirportTowerBoundaryController()
    session_id = uuid4()
    tower.assume_runway_authority(session_id, reason="Tower controls runway")

    with pytest.raises(ValueError, match="not safe enough"):
        tower.reserve_operation(
            session_id=session_id,
            runway_id="27",
            operation=RunwayOperationType.LANDING,
            runway_state=RunwayState(runway_id="27"),
            reason="landing runway 27",
        )


def test_ground_and_tower_scopes_coexist_at_boundary() -> None:
    core = AtcCoreFlow()
    tower = AirportTowerBoundaryController(RunwayReservationManager(core))
    session_id = uuid4()
    core.claim_authority(
        session_id=session_id,
        scope=ControllerAuthorityScope.SURFACE_MOVEMENT,
        agency=ControllerAgency.AIRPORT_GROUND,
        reason="Ground controls taxi movement",
    )
    tower.assume_runway_authority(session_id, reason="Tower controls protected runway")

    tower.record_boundary_contact(session_id, runway_id="09", reason="aircraft at holding point")

    assert core.authority.get_owner(session_id, ControllerAuthorityScope.SURFACE_MOVEMENT).agency is ControllerAgency.AIRPORT_GROUND
    assert core.authority.get_owner(session_id, ControllerAuthorityScope.LANDING_AREA).agency is ControllerAgency.AIRPORT_TOWER
    assert core.history.list(session_id)[-1].event_type == "ground_tower_boundary_contact"


def test_commitment_cannot_decrease_implicitly() -> None:
    tower = AirportTowerBoundaryController()
    session_id = uuid4()
    tower.assume_runway_authority(session_id, reason="Tower controls runway")
    tower.reserve_operation(
        session_id=session_id,
        runway_id="09",
        operation=RunwayOperationType.LINE_UP,
        runway_state=clear_runway(),
        reason="line up runway 09",
    )
    tower.reservations.advance_commitment(
        runway_id="09",
        session_id=session_id,
        commitment=CommitmentState.PHYSICALLY_COMMITTED,
        reason="aircraft entered runway",
    )

    with pytest.raises(ValueError, match="cannot decrease"):
        tower.reservations.advance_commitment(
            runway_id="09",
            session_id=session_id,
            commitment=CommitmentState.RESERVED,
            reason="invalid rollback",
        )


def test_physically_committed_operation_cannot_be_normally_released() -> None:
    tower = AirportTowerBoundaryController()
    session_id = uuid4()
    tower.assume_runway_authority(session_id, reason="Tower controls runway")
    tower.reserve_operation(
        session_id=session_id,
        runway_id="09",
        operation=RunwayOperationType.TAKEOFF,
        runway_state=clear_runway(),
        reason="takeoff runway 09",
    )
    tower.reservations.advance_commitment(
        runway_id="09",
        session_id=session_id,
        commitment=CommitmentState.PHYSICALLY_COMMITTED,
        reason="takeoff roll started",
    )

    with pytest.raises(ValueError, match="Physically committed"):
        tower.reservations.release(runway_id="09", session_id=session_id, reason="ordinary cancellation")
