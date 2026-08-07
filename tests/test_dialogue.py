from fastapi.testclient import TestClient

from orion.app import app
from orion.dialogue import DialogueIntent, DialogueLanguage, DialogueRequest, classify_dialogue


def test_detects_russian_threat_request() -> None:
    result = classify_dialogue(DialogueRequest(text="Какие угрозы вокруг меня?"))
    assert result.language == DialogueLanguage.RU
    assert result.intent == DialogueIntent.THREATS
    assert result.requires_confirmation is False


def test_detects_english_tanker_request() -> None:
    result = classify_dialogue(DialogueRequest(text="Where is the tanker?"))
    assert result.language == DialogueLanguage.EN
    assert result.intent == DialogueIntent.TANKER


def test_target_designation_requires_confirmation() -> None:
    result = classify_dialogue(DialogueRequest(text="Подсвети цель лазером"))
    assert result.intent == DialogueIntent.LASER
    assert result.requires_confirmation is True


def test_unknown_request_is_not_executed() -> None:
    result = classify_dialogue(DialogueRequest(text="Расскажи что-нибудь неожиданное"))
    assert result.intent == DialogueIntent.UNKNOWN
    assert result.confidence < 0.5


def test_dialogue_endpoint() -> None:
    with TestClient(app) as client:
        response = client.post("/v1/dialogue", json={"text": "Request AWACS picture", "language": "auto"})

    assert response.status_code == 200
    assert response.json()["intent"] == "awacs"
