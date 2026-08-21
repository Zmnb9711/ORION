from __future__ import annotations

from array import array
from pathlib import Path

import orion.qwen_live_audio_core as qwen_live_audio_core
from orion.audio_device_config import AudioEndpointSelection, AudioEndpointState
from orion.portaudio_devices import enumerate_portaudio_endpoints
from orion.qwen_live_audio_core import (
    QWEN_INPUT_RATE,
    QWEN_OUTPUT_RATE,
    QwenLiveAudioService,
    _audio_session_update,
    _resample_pcm16_mono,
)
from orion.windows_wasapi_backend import WasapiDirection


class FakeSoundDevice:
    class _Default:
        device = (0, 2)

    default = _Default()

    class WasapiSettings:
        def __init__(self, *, exclusive: bool) -> None:
            self.exclusive = exclusive

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

    def check_input_settings(self, **kwargs: object) -> None:
        assert kwargs["device"] == 1

    def check_output_settings(self, **kwargs: object) -> None:
        assert kwargs["device"] == 2


def test_qwen_live_resolves_exact_persisted_identity_inside_core_process(
    monkeypatch,
) -> None:
    sd = FakeSoundDevice()
    service = QwenLiveAudioService()
    endpoints = enumerate_portaudio_endpoints(sd)
    microphone = next(
        item
        for item in endpoints
        if item.direction is WasapiDirection.INPUT and item.device_index == 1
    )
    speakers = next(
        item
        for item in endpoints
        if item.direction is WasapiDirection.OUTPUT and item.device_index == 2
    )
    selection = AudioEndpointSelection(
        input_device_id=microphone.device_id,
        output_device_id=speakers.device_id,
        input_identity=microphone.identity(),
        output_identity=speakers.identity(),
    )
    state = AudioEndpointState(
        selection=selection,
        resolved_input=microphone,
        resolved_output=speakers,
        endpoint_count=len(endpoints),
    )
    monkeypatch.setattr(
        qwen_live_audio_core.audio_device_config,
        "state",
        lambda: state,
    )

    resolved = service._resolve_audio(sd)

    assert resolved.input_index == 1
    assert resolved.output_index == 2
    assert resolved.input_endpoint.identity() == microphone.identity()
    assert resolved.output_endpoint.identity() == speakers.identity()
    assert resolved.input_rate_plan is not None
    assert resolved.output_rate_plan is not None
    assert resolved.input_rate_plan.physical_rate == QWEN_INPUT_RATE
    assert resolved.output_rate_plan.physical_rate == QWEN_OUTPUT_RATE


def test_qwen_live_resamples_native_48k_microphone_to_required_16k_pcm() -> None:
    source = array("h", range(480)).tobytes()
    converted = _resample_pcm16_mono(source, 48_000, QWEN_INPUT_RATE)
    assert len(converted) == 160 * 2


def test_qwen_live_resamples_qwen_24k_output_to_native_48k() -> None:
    source = array("h", range(240)).tobytes()
    converted = _resample_pcm16_mono(source, QWEN_OUTPUT_RATE, 48_000)
    assert len(converted) == 480 * 2


def test_qwen_live_session_is_audio_audio_and_exposes_only_core_atc_tool() -> None:
    payload = _audio_session_update("qwen3.5-omni-flash-realtime", "Tina")
    session = payload["session"]
    assert session["modalities"] == ["text", "audio"]
    assert session["input_audio_format"] == "pcm"
    assert session["output_audio_format"] == "pcm"
    assert session["turn_detection"]["type"] == "server_vad"
    assert [tool["function"]["name"] for tool in session["tools"]] == [
        "orion_virtual_atc_request"
    ]
    assert "ORION" in session["instructions"]
    assert "realtime" in session["instructions"].lower()
    assert "never invent" in session["instructions"].lower()


def test_qwen_live_uses_reference_aligned_blocking_input_and_output_streams() -> None:
    source = Path(__file__).parents[1].joinpath("orion", "qwen_live_audio_core.py").read_text(encoding="utf-8")
    assert source.count("sd.RawInputStream(") == 1
    assert source.count("sd.RawOutputStream(") == 1
    assert "sd.RawStream(" not in source
    assert "capture_thread" not in source
    assert "callback=" not in source
