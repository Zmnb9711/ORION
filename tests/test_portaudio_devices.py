from __future__ import annotations

from types import SimpleNamespace

import pytest

from orion.portaudio_devices import (
    PortAudioEndpoint,
    PortAudioEndpointResolutionError,
    enumerate_portaudio_endpoints,
    portaudio_extra_settings,
    resolve_portaudio_endpoint,
)
from orion.windows_wasapi_backend import WasapiDirection


class FakeSoundDevice:
    def __init__(self) -> None:
        self.default = SimpleNamespace(device=(1, 6))
        self.host_apis = [{"name": "MME"}, {"name": "Windows WASAPI"}]
        self.devices = [
            {
                "name": "Duplicate microphone",
                "hostapi": 1,
                "max_input_channels": 2,
                "max_output_channels": 0,
                "default_samplerate": 48_000,
            },
            {
                "name": "Microphone (Pimax Dream Air)",
                "hostapi": 0,
                "max_input_channels": 2,
                "max_output_channels": 0,
                "default_samplerate": 44_100,
            },
            {
                "name": "Microphone (Pimax Dream Air)",
                "hostapi": 1,
                "max_input_channels": 2,
                "max_output_channels": 0,
                "default_samplerate": 48_000,
            },
            {
                "name": "Unused",
                "hostapi": 0,
                "max_input_channels": 0,
                "max_output_channels": 0,
                "default_samplerate": 44_100,
            },
            {
                "name": "Unused 2",
                "hostapi": 0,
                "max_input_channels": 0,
                "max_output_channels": 0,
                "default_samplerate": 44_100,
            },
            {
                "name": "Unused 3",
                "hostapi": 0,
                "max_input_channels": 0,
                "max_output_channels": 0,
                "default_samplerate": 44_100,
            },
            {
                "name": "Pimax m (NVIDIA High Definition",
                "hostapi": 0,
                "max_input_channels": 0,
                "max_output_channels": 2,
                "default_samplerate": 44_100,
            },
        ]

    def query_devices(self):  # noqa: ANN201
        return self.devices

    def query_hostapis(self):  # noqa: ANN201
        return self.host_apis

    @staticmethod
    def WasapiSettings(**kwargs: object) -> dict[str, object]:
        return dict(kwargs)


def _reindexed(endpoint: PortAudioEndpoint, index: int) -> PortAudioEndpoint:
    return endpoint.model_copy(
        update={
            "device_index": index,
            "device_id": (
                f"sounddevice:portaudio:{endpoint.direction.value}:"
                f"{endpoint.host_api_index}:{index}"
            ),
        }
    )


def test_enumeration_preserves_exact_index_host_api_and_direction() -> None:
    endpoints = enumerate_portaudio_endpoints(FakeSoundDevice())
    microphone = next(item for item in endpoints if item.device_index == 1)
    output = next(item for item in endpoints if item.device_index == 6)

    assert microphone.host_api_name == "MME"
    assert microphone.device_id == "sounddevice:portaudio:input:0:1"
    assert microphone.max_input_channels == 2
    assert microphone.default_samplerate == 44_100
    assert microphone.is_default
    assert output.host_api_name == "MME"
    assert output.device_id == "sounddevice:portaudio:output:0:6"
    assert output.max_output_channels == 2
    assert output.is_default


def test_exact_identity_cannot_redirect_to_duplicate_name_or_host_api() -> None:
    endpoints = enumerate_portaudio_endpoints(FakeSoundDevice())
    selected = next(item for item in endpoints if item.device_index == 1)

    resolved = resolve_portaudio_endpoint(
        endpoints,
        selected.device_id,
        WasapiDirection.INPUT,
        identity=selected.identity(),
    )

    assert resolved.device_index == 1
    assert resolved.host_api_name == "MME"


def test_stale_index_recovers_only_one_complete_identity_match() -> None:
    endpoints = enumerate_portaudio_endpoints(FakeSoundDevice())
    selected = next(item for item in endpoints if item.device_index == 1)
    shifted = _reindexed(selected, 9)
    remaining = [item for item in endpoints if item.device_index != 1]

    resolved = resolve_portaudio_endpoint(
        [*remaining, shifted],
        selected.device_id,
        WasapiDirection.INPUT,
        identity=selected.identity(),
    )

    assert resolved.device_index == 9


def test_ambiguous_complete_identity_recovery_is_explicit_error() -> None:
    endpoints = enumerate_portaudio_endpoints(FakeSoundDevice())
    selected = next(item for item in endpoints if item.device_index == 1)
    candidates = [_reindexed(selected, 8), _reindexed(selected, 9)]

    with pytest.raises(PortAudioEndpointResolutionError, match="ambiguous"):
        resolve_portaudio_endpoint(
            candidates,
            selected.device_id,
            WasapiDirection.INPUT,
            identity=selected.identity(),
        )


def test_duplicate_name_within_one_host_api_cannot_silently_redirect() -> None:
    endpoints = enumerate_portaudio_endpoints(FakeSoundDevice())
    selected = next(item for item in endpoints if item.device_index == 1)
    duplicate = _reindexed(selected, 9)

    with pytest.raises(PortAudioEndpointResolutionError, match="ambiguous"):
        resolve_portaudio_endpoint(
            [duplicate, _reindexed(selected, 8)],
            selected.device_id,
            WasapiDirection.INPUT,
            identity=selected.identity(),
        )


def test_new_identity_never_falls_back_to_partial_device_name() -> None:
    endpoints = enumerate_portaudio_endpoints(FakeSoundDevice())

    with pytest.raises(PortAudioEndpointResolutionError, match="unavailable"):
        resolve_portaudio_endpoint(
            endpoints,
            "Microphone (Pimax Dream Air)",
            WasapiDirection.INPUT,
        )


def test_host_specific_extra_settings_do_not_attach_wasapi_to_mme() -> None:
    sd = FakeSoundDevice()
    endpoints = enumerate_portaudio_endpoints(sd)
    mme = next(item for item in endpoints if item.device_index == 1)
    wasapi = next(item for item in endpoints if item.device_index == 2)

    assert portaudio_extra_settings(sd, mme) == (None, "host_default")
    assert portaudio_extra_settings(sd, wasapi) == (
        {"exclusive": False},
        "wasapi_shared",
    )
