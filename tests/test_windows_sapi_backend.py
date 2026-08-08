from __future__ import annotations

from orion.tts_audio import AudioRenderRequest, VoiceProfile
from orion.voice_core import VoiceAgent
from orion.windows_sapi_backend import WindowsSapiBackend, _powershell_sapi_script


def test_powershell_sapi_script_escapes_text_and_voice() -> None:
    script = _powershell_sapi_script(
        text="Pilot's ready",
        target="C:\\Temp\\orion.wav",
        rate=1,
        volume=80,
        voice_name="Voice's Name",
    )
    assert "Pilot''s ready" in script
    assert "Voice''s Name" in script
    assert "$s.Rate = 1" in script
    assert "$s.Volume = 80" in script


def test_non_windows_native_backend_reports_unavailable(monkeypatch, tmp_path) -> None:
    import orion.windows_sapi_backend as module

    monkeypatch.setattr(module.os, "name", "posix")
    backend = WindowsSapiBackend(str(tmp_path))
    request = AudioRenderRequest(
        command_id="00000000-0000-0000-0000-000000000001",
        text="Texaco available",
        agent=VoiceAgent.TANKER,
        profile=VoiceProfile(profile_id="tanker"),
    )
    result = backend.render(request)
    assert result.accepted is False
    assert "only available on Windows" in result.message
