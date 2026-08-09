from uuid import uuid4

import pytest

from orion.airport_surface import (
    CrossingState,
    HoldShortConstraint,
    RunwayAvailability,
    RunwayCrossingTransaction,
    RunwayState,
    TaxiRoute,
)
from orion.atc_operations import FreshnessClass


def test_taxi_route_crossing_list_does_not_authorize_crossing() -> None:
    session_id = uuid4()
    route = TaxiRoute(
        session_id=session_id,
        facility_id="batumi",
        origin="parking-1",
        destination="hold-short-13",
        runway_crossings=["13/31"],
        reason="taxi to active runway",
    )
    crossing = RunwayCrossingTransaction(
        session_id=session_id,
        runway_id="13/31",
        reason="explicit runway crossing required",
    )

    assert route.runway_crossings == ["13/31"]
    assert crossing.state is CrossingState.REQUESTED


def test_unknown_or_stale_runway_cannot_support_positive_crossing_clearance() -> None:
    crossing = RunwayCrossingTransaction(
        session_id=uuid4(),
        runway_id="04/22",
        reason="crossing request",
    )

    with pytest.raises(ValueError, match="not safe enough"):
        crossing.clear(RunwayState(runway_id="04/22"))

    with pytest.raises(ValueError, match="not safe enough"):
        crossing.clear(
            RunwayState(
                runway_id="04/22",
                availability=RunwayAvailability.CLEAR,
                freshness=FreshnessClass.STALE,
            )
        )


def test_fresh_clear_runway_allows_acknowledged_crossing_commit() -> None:
    crossing = RunwayCrossingTransaction(
        session_id=uuid4(),
        runway_id="09/27",
        reason="cross active runway",
    )
    runway = RunwayState(
        runway_id="09/27",
        availability=RunwayAvailability.CLEAR,
        freshness=FreshnessClass.FRESH,
    )

    crossing.clear(runway)
    assert crossing.state is CrossingState.CLEARED
    with pytest.raises(ValueError, match="must be acknowledged"):
        crossing.commit()

    crossing.acknowledge()
    crossing.commit()
    assert crossing.state is CrossingState.COMMITTED


def test_committed_crossing_cannot_be_normally_cancelled() -> None:
    crossing = RunwayCrossingTransaction(
        session_id=uuid4(),
        runway_id="08/26",
        reason="cross active runway",
    )
    crossing.clear(
        RunwayState(
            runway_id="08/26",
            availability=RunwayAvailability.CLEAR,
            freshness=FreshnessClass.FRESH,
        )
    )
    crossing.acknowledge()
    crossing.commit()

    with pytest.raises(ValueError, match="Physically committed"):
        crossing.cancel()


def test_hold_short_remains_active_until_explicit_release() -> None:
    constraint = HoldShortConstraint(
        session_id=uuid4(),
        resource_id="runway-13-boundary",
        reason="hold short runway 13",
    )

    constraint.acknowledge()
    assert constraint.active is True
    assert constraint.acknowledged is True

    constraint.release()
    assert constraint.active is False
    assert constraint.released_at is not None
