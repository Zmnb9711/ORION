from uuid import uuid4

import pytest

from orion.atc_core import AtcSessionIdentity, ControllerAgency, ControllerAuthorityScope
from orion.atc_service import VirtualAtcService
from orion.atc_simulator_sync import AtcIntegrationMode


def test_event_gated_handoff_transfers_authority_only_when_event_completes() -> None:
    service = VirtualAtcService()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="hornet", facility_id="cvn")
    service.open_session(identity, procedural_state="catapult_ready")
    service.claim_authority(
        session_id=identity.session_id,
        scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
        agency=ControllerAgency.CARRIER_DECK,
        reason="deck owns pre-launch flight traffic",
    )

    handoff = service.begin_event_gated_handoff(
        session_id=identity.session_id,
        source=ControllerAgency.CARRIER_DECK,
        destination=ControllerAgency.CARRIER_DEPARTURE,
        scopes=[ControllerAuthorityScope.FLIGHT_TRAFFIC],
        reason="transfer on catapult launch",
    )

    owner = service.core.authority.get_owner(identity.session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
    assert owner is not None
    assert owner.agency is ControllerAgency.CARRIER_DECK

    completed = service.complete_event_gated_handoff(
        handoff.handoff_id,
        event_name="airborne",
        reason="aircraft left catapult",
        contact_established=False,
    )

    assert completed.state.value == "completed"
    owner = service.core.authority.get_owner(identity.session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
    assert owner is not None
    assert owner.agency is ControllerAgency.CARRIER_DEPARTURE


def test_service_status_reports_runtime_authority_and_mode() -> None:
    service = VirtualAtcService()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="viper", facility_id="airfield")
    service.open_session(identity, procedural_state="taxi")
    service.claim_authority(
        session_id=identity.session_id,
        scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
        agency=ControllerAgency.AIRPORT_GROUND,
        reason="ground controls taxi traffic",
    )

    status = service.status(identity.session_id)

    assert status.procedural_state == "taxi"
    assert status.integration_mode is AtcIntegrationMode.ORION_PRIMARY
    assert status.authority[ControllerAuthorityScope.FLIGHT_TRAFFIC] is ControllerAgency.AIRPORT_GROUND
    assert status.event_count >= 3


def test_close_session_invalidates_live_runtime_and_cancels_authority() -> None:
    service = VirtualAtcService()
    identity = AtcSessionIdentity(mission_id="m1", aircraft_id="a1")
    service.open_session(identity, procedural_state="inbound")
    service.claim_authority(
        session_id=identity.session_id,
        scope=ControllerAuthorityScope.FLIGHT_TRAFFIC,
        agency=ControllerAgency.AIRPORT_APPROACH,
        reason="approach owns inbound",
    )

    closed = service.close_session(identity.session_id, reason="flight completed")

    assert closed.session_id == identity.session_id
    assert service.sessions.get(identity.session_id) is None
    assert service.core.authority.list_ownership(identity.session_id) == []
    with pytest.raises(KeyError, match="runtime session"):
        service.status(identity.session_id)
    event_types = [event.event_type for event in service.core.history.list(identity.session_id)]
    assert "session_closed" in event_types


def test_event_handoff_rejects_unknown_session() -> None:
    service = VirtualAtcService()

    with pytest.raises(KeyError, match="runtime session"):
        service.begin_event_gated_handoff(
            session_id=uuid4(),
            source=ControllerAgency.CARRIER_DECK,
            destination=ControllerAgency.CARRIER_DEPARTURE,
            scopes=[ControllerAuthorityScope.FLIGHT_TRAFFIC],
            reason="test",
        )
