from fastapi.testclient import TestClient

from orion.app import app
from orion.application_state import get_application_state


def test_application_state_contract_is_available():
    client = TestClient(app)
    response = client.get('/v1/application-state')
    assert response.status_code == 200
    payload = response.json()
    assert payload['readiness'] in {'ready', 'degraded', 'action_required'}
    assert 'dcs_connected' in payload
    assert 'startup_health' in payload
    assert 'mission_bridge' in payload
    assert 'voice' in payload
    assert 'audio' in payload


def test_application_state_stream_is_registered_in_openapi():
    schema = app.openapi()
    assert '/v1/application-state/stream' in schema['paths']


def test_application_state_aggregates_subsystems():
    state = get_application_state()
    assert state.mission_bridge.pending >= 0
    assert state.mission_bridge.failed >= 0
    assert state.voice.queued >= 0
    assert state.voice.running >= 0
    assert state.voice.failed >= 0
