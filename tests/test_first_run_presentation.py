from fastapi.testclient import TestClient

from orion.app import app
from orion.first_run_presentation import UiLanguage


def test_first_run_presentation_api_supports_russian():
    response = TestClient(app).get("/v1/first-run/presentation?language=ru")
    assert response.status_code == 200
    payload = response.json()
    assert payload["language"] == UiLanguage.RU
    assert payload["title"]
    assert payload["description"]
    assert payload["status_text"]


def test_first_run_presentation_defaults_to_english():
    response = TestClient(app).get("/v1/first-run/presentation")
    assert response.status_code == 200
    payload = response.json()
    assert payload["language"] == UiLanguage.EN
    assert payload["progress_percent"] in {0, 25, 50, 75, 100}


def test_presentation_exposes_primary_action_when_needed():
    response = TestClient(app).get("/v1/first-run/presentation?language=en")
    payload = response.json()
    if payload["step"] != "ready":
        assert payload["buttons"]
        assert payload["buttons"][0]["primary"] is True
