from __future__ import annotations

import wave

import pytest

from orion.pcm_dsp import _encode
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


@pytest.mark.parametrize("width", [1, 2, 3, 4])
def test_prepare_radio_supports_pcm_widths_and_outputs_mono(tmp_path, width: int) -> None:
    source = tmp_path / f"input-{width}.wav"
    frames = _encode([100, -100, 200, 0] * 32, width)
    with wave.open(str(source), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(width)
        wav.setframerate(16000)
        wav.writeframes(frames)

    target = WindowsSapiBackend(str(tmp_path)).prepare_radio(source)

    assert target.name == f"input-{width}.radio.wav"
    with wave.open(str(target), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == width
        assert wav.getframerate() == 16000
        assert wav.getnframes() > 0
        assert wav.readframes(wav.getnframes())


def test_prepare_radio_rejects_multichannel_pcm(tmp_path) -> None:
    source = tmp_path / "surround.wav"
    with wave.open(str(source), "wb") as wav:
        wav.setnchannels(3)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(_encode([0, 0, 0] * 8, 2))

    with pytest.raises(ValueError, match="mono or stereo"):
        WindowsSapiBackend(str(tmp_path)).prepare_radio(source)
