from fastapi.testclient import TestClient

from orion.app import app
from orion.speech_scheduler import speech_scheduler
from orion.tts_audio import TtsBackend, profile_for
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommandCreate, voice_commands


def setup_function() -> None:
    voice_commands._commands.clear()
    speech_scheduler.reset()


def teardown_function() -> None:
    voice_commands._commands.clear()
    speech_scheduler.reset()


def test_agent_voice_profiles_are_distinct() -> None:
    tanker = voice_commands.submit(VoiceCommandCreate(transcript="Texaco available", intent="aar", agent=VoiceAgent.TANKER))
    threat = voice_commands.submit(VoiceCommandCreate(transcript="Missile warning", intent="warning", agent=VoiceAgent.THREAT_ANALYZER, priority=CommandPriority.CRITICAL))

    tanker_profile = profile_for(tanker, "en")
    threat_profile = profile_for(threat, "en")

    assert tanker_profile.profile_id == "tanker"
    assert tanker_profile.radio_effect is True
    assert threat_profile.profile_id == "threat"
    assert threat_profile.rate > tanker_profile.rate


def test_russian_profile_uses_russian_locale() -> None:
    command = voice_commands.submit(VoiceCommandCreate(transcript="Танкер доступен", intent="aar", agent=VoiceAgent.TANKER))
    profile = profile_for(command, "ru")
    assert profile.locale == "ru-RU"


def test_prepare_next_tts_returns_windows_render_contract() -> None:
    command = voice_commands.submit(
        VoiceCommandCreate(
            transcript="Texaco, join-up stabilized.",
            intent="aar_proactive:precontact_ready",
            agent=VoiceAgent.TANKER,
        )
    )

    with TestClient(app) as client:
        response = client.post("/v1/tts/prepare-next", params={"language": "en", "backend": "windows_sapi"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["backend"] == TtsBackend.WINDOWS_SAPI.value
    assert payload["command_id"] == str(command.command_id)
    assert payload["output_path"].endswith(f"{command.command_id}.wav")


def test_prepare_next_tts_is_idle_when_queue_empty() -> None:
    with TestClient(app) as client:
        response = client.post("/v1/tts/prepare-next")
    assert response.status_code == 200
    assert response.json()["decision"] == "idle"
