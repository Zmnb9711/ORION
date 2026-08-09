from uuid import uuid4

import pytest

from orion.atc_core import (
    AtcAuthorityRegistry,
    AtcSessionIdentity,
    ContactState,
    ControllerAgency,
    ControllerAuthorityScope,
    HandoffState,
    HandoffTransferMode,
)


def test_session_identity_is_mission_scoped() -> None:
    session = AtcSessionIdentity(mission_id="mission-1", aircraft_id="Enfield11", facility_id="CVN-71")

    assert session.mission_id == "mission-1"
    assert session.aircraft_id == "Enfield11"
    assert session.facility_id == "CVN-71"


def test_scoped_authority_allows_tower_and_lso_without_conflict() -> None:
    registry = AtcAuthorityRegistry()
    session_id = uuid4()

    registry.claim(
        session_id=session_id,
        scope=ControllerAuthorityScope.LANDING_AREA,
        agency=ControllerAgency.CARRIER_TOWER,
        reason="Tower retains landing-area authority",
    )
    registry.claim(
        session_id=session_id,
        scope=ControllerAuthorityScope.FINAL_GUIDANCE,
        agency=ControllerAgency.CARRIER_LSO,
        reason="LSO owns final guidance",
    )

    assert registry.get_owner(session_id, ControllerAuthorityScope.LANDING_AREA).agency is ControllerAgency.CARRIER_TOWER
    assert registry.get_owner(session_id, ControllerAuthorityScope.FINAL_GUIDANCE).agency is ControllerAgency.CARRIER_LSO


def test_airport_scopes_allow_clearance_ground_tower_approach_and_par_to_coexist() -> None:
    registry = AtcAuthorityRegistry()
    session_id = uuid4()
    assignments = {
        ControllerAuthorityScope.ROUTE_CLEARANCE: ControllerAgency.AIRPORT_CLEARANCE_DELIVERY,
        ControllerAuthorityScope.SURFACE_MOVEMENT: ControllerAgency.AIRPORT_GROUND,
        ControllerAuthorityScope.LANDING_AREA: ControllerAgency.AIRPORT_TOWER,
        ControllerAuthorityScope.FLIGHT_TRAFFIC: ControllerAgency.AIRPORT_APPROACH,
        ControllerAuthorityScope.FINAL_GUIDANCE: ControllerAgency.AIRPORT_PAR,
    }

    for scope, agency in assignments.items():
        registry.claim(session_id=session_id, scope=scope, agency=agency, reason="airport scoped authority")

    owners = {item.scope: item.agency for item in registry.list_ownership(session_id)}
    assert owners == assignments


def test_same_scope_cannot_have_two_owners() -> None:
    registry = AtcAuthorityRegistry()
    session_id = uuid4()
    registry.claim(
        session_id=session_id,
        scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
        agency=ControllerAgency.CARRIER_MARSHAL,
        reason="Inbound under Marshal control",
    )

    with pytest.raises(ValueError, match="already owned"):
        registry.claim(
            session_id=session_id,
            scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
            agency=ControllerAgency.CARRIER_APPROACH,
            reason="Conflicting premature Approach claim",
        )


def test_surface_movement_scope_cannot_have_ground_and_tower_as_simultaneous_owners() -> None:
    registry = AtcAuthorityRegistry()
    session_id = uuid4()
    registry.claim(
        session_id=session_id,
        scope=ControllerAuthorityScope.SURFACE_MOVEMENT,
        agency=ControllerAgency.AIRPORT_GROUND,
        reason="Ground owns taxi movement",
    )

    with pytest.raises(ValueError, match="already owned"):
        registry.claim(
            session_id=session_id,
            scope=ControllerAuthorityScope.SURFACE_MOVEMENT,
            agency=ControllerAgency.AIRPORT_TOWER,
            reason="Tower cannot conflict with Ground surface ownership",
        )


def test_acknowledgement_gated_handoff_requires_ack_before_transfer() -> None:
    registry = AtcAuthorityRegistry()
    session_id = uuid4()
    registry.claim(
        session_id=session_id,
        scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
        agency=ControllerAgency.CARRIER_MARSHAL,
        reason="Case III Marshal control",
    )
    handoff = registry.begin_handoff(
        session_id=session_id,
        source_agency=ControllerAgency.CARRIER_MARSHAL,
        destination_agency=ControllerAgency.CARRIER_APPROACH,
        scopes=[ControllerAuthorityScope.FLIGHT_TRAFFIC],
        transfer_mode=HandoffTransferMode.ACKNOWLEDGEMENT_GATED,
        reason="Commencing and switching to Approach",
        frequency="127.5",
    )

    with pytest.raises(ValueError, match="must be acknowledged"):
        registry.complete_handoff(handoff.handoff_id)

    acknowledged = registry.acknowledge_handoff(handoff.handoff_id)
    assert acknowledged.state is HandoffState.ACKNOWLEDGED
    assert acknowledged.contact_state is ContactState.ESTABLISHED

    completed = registry.complete_handoff(handoff.handoff_id)
    assert completed.state is HandoffState.COMPLETED
    assert registry.get_owner(session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC).agency is ControllerAgency.CARRIER_APPROACH


def test_event_gated_irreversible_handoff_transfers_without_radio_ack() -> None:
    registry = AtcAuthorityRegistry()
    session_id = uuid4()
    registry.claim(
        session_id=session_id,
        scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
        agency=ControllerAgency.CARRIER_DECK,
        reason="Pre-launch transition placeholder",
    )
    handoff = registry.begin_handoff(
        session_id=session_id,
        source_agency=ControllerAgency.CARRIER_DECK,
        destination_agency=ControllerAgency.CARRIER_DEPARTURE,
        scopes=[ControllerAuthorityScope.FLIGHT_TRAFFIC],
        transfer_mode=HandoffTransferMode.EVENT_GATED_IRREVERSIBLE,
        reason="Authoritative airborne event",
    )

    completed = registry.complete_handoff(handoff.handoff_id, contact_established=False)

    assert completed.state is HandoffState.COMPLETED
    assert completed.contact_state is ContactState.PENDING
    assert registry.get_owner(session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC).agency is ControllerAgency.CARRIER_DEPARTURE


def test_handoff_cannot_transfer_scope_source_does_not_own() -> None:
    registry = AtcAuthorityRegistry()
    session_id = uuid4()
    registry.claim(
        session_id=session_id,
        scope=ControllerAuthorityScope.LANDING_AREA,
        agency=ControllerAgency.CARRIER_TOWER,
        reason="Tower landing-area authority",
    )

    with pytest.raises(ValueError, match="current owner"):
        registry.begin_handoff(
            session_id=session_id,
            source_agency=ControllerAgency.CARRIER_LSO,
            destination_agency=ControllerAgency.CARRIER_TOWER,
            scopes=[ControllerAuthorityScope.LANDING_AREA],
            transfer_mode=HandoffTransferMode.ACKNOWLEDGEMENT_GATED,
            reason="Invalid ownership transfer",
        )


def test_clear_session_releases_ownership_and_cancels_open_handoff() -> None:
    registry = AtcAuthorityRegistry()
    session_id = uuid4()
    registry.claim(
        session_id=session_id,
        scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
        agency=ControllerAgency.CARRIER_MARSHAL,
        reason="Marshal control",
    )
    handoff = registry.begin_handoff(
        session_id=session_id,
        source_agency=ControllerAgency.CARRIER_MARSHAL,
        destination_agency=ControllerAgency.CARRIER_APPROACH,
        scopes=[ControllerAuthorityScope.FLIGHT_TRAFFIC],
        transfer_mode=HandoffTransferMode.ACKNOWLEDGEMENT_GATED,
        reason="Approach handoff",
    )

    registry.clear_session(session_id)

    assert registry.get_owner(session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC) is None
    assert registry.get_handoff(handoff.handoff_id).state is HandoffState.CANCELLED
