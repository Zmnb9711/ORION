from fastapi.testclient import TestClient

from orion.airport_arrival_orchestration import AirportArrivalOrchestrator
from orion.airport_arrival_runtime import AirportArrivalRuntime, AirportArrivalState, ApproachType
from orion.airport_atc_dialogue import AtcDialogueRequest, AirportAtcDialogueGateway
from orion.airport_surface_runtime import AirportSurfaceCoordinator
from orion.atc_core import AtcSessionIdentity, ControllerAgency, ControllerAuthorityScope
from orion.atc_service import VirtualAtcService
from orion.app import app


def _gateway():
    service = VirtualAtcService()
    identity = AtcSessionIdentity(mission_id="dialogue", aircraft_id="hornet", facility_id="kutaisi")
    service.open_session(identity, procedural_state="arrival_contact")
    surface = AirportSurfaceCoordinator(service.core)
    arrival = AirportArrivalRuntime(surface)
    orchestration = AirportArrivalOrchestrator(service=service, arrival=arrival)
    gateway = AirportAtcDialogueGateway(service=service, arrival=arrival, arrival_orchestrator=orchestration)
    orchestration.start_arrival(session_id=identity.session_id, runway_id="07/25")
    return service, arrival, orchestration, gateway, identity


def _advance_to_tower(service, arrival, orchestration, identity):
    arrival.assume_arrival_control(identity.session_id, reason="radar identified")
    arrival.issue_descent_vectors(identity.session_id, heading_deg=120, altitude_ft=4000, speed_kt=250, reason="sequence")
    arrival.enter_approach_control(identity.session_id, reason="approach active")
    arrival.position_for_approach(identity.session_id, reason="position")
    arrival.clear_approach(identity.session_id, approach_type=ApproachType.TACAN, reason="cleared TACAN")
    arrival.confirm_final(identity.session_id)
    arrival.begin_tower_handoff(identity.session_id, frequency="250.000", reason="contact Tower")
    orchestration.complete_approach_to_tower(identity.session_id, reason="Tower contact established")
    assert service.status(identity.session_id).procedural_state == "tower_arrival"


def test_gateway_handles_russian_arrival_free_form_in_existing_session() -> None:
    service, arrival, _, gateway, identity = _gateway()

    result = gateway.handle(identity.session_id, AtcDialogueRequest(text="Возвращаюсь на базу"))

    assert result.domain == "arrival"
    assert result.language == "ru"
    assert result.intent == "return_to_base"
    assert result.action == "arrival_control"
    assert arrival.get(identity.session_id).state is AirportArrivalState.ARRIVAL_CONTROL
    owner = service.core.authority.get_owner(identity.session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
    assert owner is not None and owner.agency is ControllerAgency.AIRPORT_APPROACH


def test_gateway_requests_missing_vector_parameter_without_mutating_state() -> None:
    _, arrival, _, gateway, identity = _gateway()
    arrival.assume_arrival_control(identity.session_id, reason="identified")

    result = gateway.handle(identity.session_id, AtcDialogueRequest(text="Дай курс"))

    assert result.intent == "request_vector"
    assert result.action == "needs_parameter"
    assert result.requires_parameter is True
    assert arrival.get(identity.session_id).state is AirportArrivalState.ARRIVAL_CONTROL


def test_gateway_go_around_uses_orchestration_and_returns_authority_to_approach() -> None:
    service, arrival, orchestration, gateway, identity = _gateway()
    _advance_to_tower(service, arrival, orchestration, identity)

    result = gateway.handle(identity.session_id, AtcDialogueRequest(text="Ухожу на второй"))

    assert result.intent == "go_around"
    assert result.action == "go_around"
    assert result.procedural_state == "approach_go_around"
    assert arrival.get(identity.session_id).state is AirportArrivalState.GO_AROUND
    owner = service.core.authority.get_owner(identity.session_id, ControllerAuthorityScope.FLIGHT_TRAFFIC)
    assert owner is not None and owner.agency is ControllerAgency.AIRPORT_APPROACH


def test_gateway_marks_unwired_ground_domain_explicitly() -> None:
    service = VirtualAtcService()
    identity = AtcSessionIdentity(mission_id="dialogue", aircraft_id="hornet", facility_id="kutaisi")
    service.open_session(identity, procedural_state="ground_taxi")
    surface = AirportSurfaceCoordinator(service.core)
    arrival = AirportArrivalRuntime(surface)
    orchestration = AirportArrivalOrchestrator(service=service, arrival=arrival)
    gateway = AirportAtcDialogueGateway(service=service, arrival=arrival, arrival_orchestrator=orchestration)

    result = gateway.handle(identity.session_id, AtcDialogueRequest(text="Request taxi"))

    assert result.domain == "ground"
    assert result.action == "domain_not_yet_wired"


def test_atc_dialogue_api_router_is_registered() -> None:
    # The endpoint is registered even when the requested session is unknown.
    with TestClient(app) as client:
        response = client.post(
            "/v1/atc/sessions/00000000-0000-0000-0000-000000000001/dialogue",
            json={"text": "returning to base"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "ATC session not found"
