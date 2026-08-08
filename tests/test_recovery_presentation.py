from fastapi.testclient import TestClient

from orion.app import app


def test_recovery_ui_route_is_registered():
    client = TestClient(app)
    response = client.get('/v1/recovery-ui?language=ru')
    assert response.status_code == 200
    payload = response.json()
    assert payload['state'] in {'action_required', 'ready', 'waiting_for_telemetry', 'failed', 'starting'}


def test_recovery_ui_supports_english_labels():
    client = TestClient(app)
    response = client.get('/v1/recovery-ui?language=en')
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload['title'], str)
    assert isinstance(payload['message'], str)


def test_recovery_start_dcs_returns_presentation_contract():
    client = TestClient(app)
    response = client.post('/v1/recovery-ui/start-dcs?language=ru')
    assert response.status_code == 200
    payload = response.json()
    assert payload['state'] in {'action_required', 'waiting_for_telemetry', 'ready', 'failed'}
    assert 'health' in payload
