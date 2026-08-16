from fastapi.testclient import TestClient

from orion.app import app
from orion.voice_text_bridge_api import VOICE_V01_REPLY, _is_voice_v01_greeting


def test_voice_v01_greeting_matching() -> None:
    assert _is_voice_v01_greeting("Привет. Как дела?")
    assert _is_voice_v01_greeting("привет, ну как дела")
    assert not _is_voice_v01_greeting("Привет")


def test_whisper_text_reaches_core_and_gets_fixed_reply() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/voice/text",
            json={"text": "Привет. Как дела?", "source": "whisper", "language": "ru"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["heard"] == "Привет. Как дела?"
    assert payload["matched"] is True
    assert payload["reply"] == VOICE_V01_REPLY == "Всё хорошо. Связь установлена."
    assert payload["tts_requested"] is True


def test_unmatched_text_is_not_faked_as_understood() -> None:
    with TestClient(app) as client:
        response = client.post("/v1/voice/text", json={"text": "Проверка связи", "source": "whisper"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["matched"] is False
    assert payload["reply"] == ""
    assert payload["tts_requested"] is False
