from __future__ import annotations

from types import SimpleNamespace

import pytest

import orion.yandex_live_audio_core as core
from orion.audio_device_config import AudioEndpointSelection, AudioEndpointState
from orion.portaudio_devices import PortAudioEndpoint
from orion.windows_wasapi_backend import WasapiDirection


class _FakeSoundDevice:
    def __init__(self, *, reject_input: bool = False, reject_output: bool = False) -> None:
        self.reject_input = reject_input
        self.reject_output = reject_output
        self.checked: list[tuple[str, dict[str, object]]] = []
        self.default = SimpleNamespace(device=(1, 6))

    def query_devices(self) -> list[dict[str, object]]:
        devices = [
            {"name": f"unused-{index}", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 0, "default_samplerate": 48000}
            for index in range(7)
        ]
        devices[1] = {"name": "Logitech Mic", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0, "default_samplerate": 44100}
        devices[6] = {"name": "Logitech Output", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 44100}
        return devices

    def query_hostapis(self) -> list[dict[str, str]]:
        return [{"name": "MME"}]

    def check_input_settings(self, **kwargs: object) -> None:
        self.checked.append(("input", kwargs))
        if self.reject_input:
            raise RuntimeError("input rejected")

    def check_output_settings(self, **kwargs: object) -> None:
        self.checked.append(("output", kwargs))
        if self.reject_output:
            raise RuntimeError("output rejected")


def _endpoint(direction: WasapiDirection, index: int, name: str) -> PortAudioEndpoint:
    return PortAudioEndpoint(
        direction=direction,
        device_index=index,
        device_name=name,
        host_api_index=0,
        host_api_name="MME",
        max_input_channels=1 if direction is WasapiDirection.INPUT else 0,
        max_output_channels=2 if direction is WasapiDirection.OUTPUT else 0,
        default_samplerate=44100,
        device_id=f"sounddevice:portaudio:{direction.value}:0:{index}",
        name=name,
        is_default=True,
    )


def _state() -> AudioEndpointState:
    input_endpoint = _endpoint(WasapiDirection.INPUT, 1, "Logitech Mic")
    output_endpoint = _endpoint(WasapiDirection.OUTPUT, 6, "Logitech Output")
    return AudioEndpointState(
        selection=AudioEndpointSelection(
            input_device_id=input_endpoint.device_id,
            output_device_id=output_endpoint.device_id,
            input_identity=input_endpoint.identity(),
            output_identity=output_endpoint.identity(),
        ),
        resolved_input=input_endpoint,
        resolved_output=output_endpoint,
        endpoint_count=2,
        message="ready",
    )


def test_yandex_audio_validation_uses_exact_indices_and_direct_44100(monkeypatch: pytest.MonkeyPatch) -> None:
    sd = _FakeSoundDevice()
    monkeypatch.setattr(core.audio_device_config, "state", _state)
    resolved = core.YandexLiveAudioService()._resolve_audio(sd)
    assert resolved.input_endpoint.device_index == 1
    assert resolved.output_endpoint.device_index == 6
    assert sd.checked == [
        ("input", {"device": 1, "channels": 1, "dtype": "int16", "samplerate": 44100, "extra_settings": None}),
        ("output", {"device": 6, "channels": 1, "dtype": "int16", "samplerate": 44100, "extra_settings": None}),
    ]


@pytest.mark.parametrize("direction", ["input", "output"])
def test_unsupported_44100_fails_before_network(monkeypatch: pytest.MonkeyPatch, direction: str) -> None:
    sd = _FakeSoundDevice(reject_input=direction == "input", reject_output=direction == "output")
    monkeypatch.setattr(core.audio_device_config, "state", _state)
    with pytest.raises(core.UnsupportedAudioFormat, match="UNSUPPORTED AUDIO FORMAT"):
        core.YandexLiveAudioService()._resolve_audio(sd)


def test_playback_split_is_20ms_aligned_with_exact_short_tail() -> None:
    pcm = b"a" * core.PLAYBACK_SLICE_BYTES + b"bc" * 17
    slices = core.split_yandex_playback_pcm(pcm)
    assert [len(item) for item in slices] == [1764, 34]
    assert b"".join(slices) == pcm


def test_playback_split_rejects_partial_pcm_frame() -> None:
    with pytest.raises(ValueError, match="complete int16 frames"):
        core.split_yandex_playback_pcm(b"x")
