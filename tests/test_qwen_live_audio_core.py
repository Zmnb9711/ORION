from __future__ import annotations

from array import array
from pathlib import Path

from orion.qwen_live_audio_core import (
    QWEN_INPUT_RATE,
    QWEN_OUTPUT_RATE,
    QwenLiveAudioService,
    _audio_session_update,
    _resample_pcm16_mono,
)
from orion.windows_wasapi_backend import WasapiDirection, WasapiEndpoint


class FakeSoundDevice:
    def query_hostapis(self):
        return [
            {"name": "Windows WDM-KS"},
            {"name": "Windows WASAPI"},
        ]

    def query_devices(self, index=None):
        devices = [
            {"name": "Microphone (Logitech PRO X Gaming Headset)", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0, "default_samplerate": 48000},
            {"name": "Microphone (Logitech PRO X Gaming Headset)", "hostapi": 1, "max_input_channels": 1, "max_output_channels": 0, "default_samplerate": 48000},
            {"name": "Speakers (Logitech PRO X Gaming Headset)", "hostapi": 1, "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 48000},
        ]
        return devices if index is None else devices[index]


def test_qwen_live_resolves_selected_device_only_inside_core_process() -> None:
    sd = FakeSoundDevice()
    service = QwenLiveAudioService()
    microphone = WasapiEndpoint(
        device_id="sounddevice:wasapi:input:99",
        name="Microphone (Logitech PRO X Gaming Headset)",
        direction=WasapiDirection.INPUT,
    )
    speakers = WasapiEndpoint(
        device_id="sounddevice:wasapi:output:88",
        name="Speakers (Logitech PRO X Gaming Headset)",
        direction=WasapiDirection.OUTPUT,
    )

    assert service._resolve_device(sd, microphone, WasapiDirection.INPUT) == 1
    assert service._resolve_device(sd, speakers, WasapiDirection.OUTPUT) == 2


def test_qwen_live_resamples_native_48k_microphone_to_required_16k_pcm() -> None:
    source = array("h", range(480)).tobytes()
    converted = _resample_pcm16_mono(source, 48_000, QWEN_INPUT_RATE)
    assert len(converted) == 160 * 2


def test_qwen_live_resamples_qwen_24k_output_to_native_48k() -> None:
    source = array("h", range(240)).tobytes()
    converted = _resample_pcm16_mono(source, QWEN_OUTPUT_RATE, 48_000)
    assert len(converted) == 480 * 2


def test_qwen_live_session_is_audio_audio_and_keeps_tools_disabled() -> None:
    payload = _audio_session_update("qwen3.5-omni-flash-realtime", "Tina")
    session = payload["session"]
    assert session["modalities"] == ["text", "audio"]
    assert session["input_audio_format"] == "pcm"
    assert session["output_audio_format"] == "pcm"
    assert session["turn_detection"]["type"] == "server_vad"
    assert "tools" not in session
    assert "ATC" in session["instructions"]


def test_qwen_live_uses_one_full_duplex_portaudio_stream() -> None:
    source = Path(__file__).parents[1].joinpath("orion", "qwen_live_audio_core.py").read_text(encoding="utf-8")
    assert "sd.RawStream(" in source
    assert "RawInputStream(" not in source
    assert "RawOutputStream(" not in source
    assert "capture_thread" not in source
