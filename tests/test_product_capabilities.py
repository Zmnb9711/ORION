from fastapi.testclient import TestClient

from orion.app import app
from orion.orion_settings import OrionSettings, OrionSettingsUpdate


def test_audio_output_can_be_selected_independently() -> None:
    settings = OrionSettings(audio_output_id="speakers-usb", microphone_id="mic-vr")
    assert settings.audio_output_id == "speakers-usb"
    assert settings.microphone_id == "mic-vr"

    update = OrionSettingsUpdate(audio_output_id="windows-default")
    assert update.audio_output_id == "windows-default"


def test_capabilities_catalog_is_structured_and_exposed() -> None:
    client = TestClient(app)
    response = client.get("/v1/capabilities")
    assert response.status_code == 200
    sections = response.json()
    ids = {section["id"] for section in sections}
    assert {"flight", "atc", "awacs", "mission-control", "mission-pack", "diagnostics"} <= ids
    assert all(section["title"] and section["description"] and section["capabilities"] for section in sections)
