from pathlib import Path

import orion.audio_device_config as module
from orion.audio_device_config import AudioDeviceConfigService, AudioEndpointSelection
from orion.portaudio_devices import PortAudioEndpoint, PortAudioEndpointCatalog
from orion.windows_wasapi_backend import WasapiDirection, WasapiEndpoint, WasapiEndpointCatalog, direction_from_device_id


def _portaudio_endpoint(
    device_index: int,
    name: str,
    direction: WasapiDirection,
) -> PortAudioEndpoint:
    host_api_index = 0
    return PortAudioEndpoint(
        device_id=(
            f"sounddevice:portaudio:{direction.value}:"
            f"{host_api_index}:{device_index}"
        ),
        name=name,
        device_name=name,
        direction=direction,
        device_index=device_index,
        host_api_index=host_api_index,
        host_api_name="MME",
        max_input_channels=1 if direction is WasapiDirection.INPUT else 0,
        max_output_channels=2 if direction is WasapiDirection.OUTPUT else 0,
        default_samplerate=44_100,
    )


def test_direction_from_mmdevice_id() -> None:
    assert direction_from_device_id(r"SWD\MMDEVAPI\{0.0.0.00000000}.{out}") is WasapiDirection.OUTPUT
    assert direction_from_device_id(r"SWD\MMDEVAPI\{0.0.1.00000000}.{in}") is WasapiDirection.INPUT


def test_catalog_separates_inputs_outputs() -> None:
    catalog = WasapiEndpointCatalog(provider=lambda: [
        WasapiEndpoint(device_id="mic", name="Microphone", direction=WasapiDirection.INPUT),
        WasapiEndpoint(device_id="headset", name="Headset", direction=WasapiDirection.OUTPUT),
    ])
    assert [item.device_id for item in catalog.inputs()] == ["mic"]
    assert [item.device_id for item in catalog.outputs()] == ["headset"]


def test_catalog_reuses_cached_snapshot() -> None:
    calls = 0

    def provider() -> list[WasapiEndpoint]:
        nonlocal calls
        calls += 1
        return [
            WasapiEndpoint(device_id="mic", name="Microphone", direction=WasapiDirection.INPUT, is_default=True),
            WasapiEndpoint(device_id="headset", name="Headset", direction=WasapiDirection.OUTPUT, is_default=True),
        ]

    catalog = WasapiEndpointCatalog(provider=provider, cache_ttl_s=60.0)
    assert catalog.inputs()[0].device_id == "mic"
    assert catalog.outputs()[0].device_id == "headset"
    assert catalog.choose("default", WasapiDirection.INPUT) is not None
    assert calls == 1


def test_core_selection_persists_and_resolves_from_one_snapshot(monkeypatch, tmp_path: Path) -> None:
    calls = 0

    def provider() -> list[PortAudioEndpoint]:
        nonlocal calls
        calls += 1
        return [
            _portaudio_endpoint(1, "Microphone", WasapiDirection.INPUT),
            _portaudio_endpoint(6, "Headset", WasapiDirection.OUTPUT),
        ]

    catalog = PortAudioEndpointCatalog(provider=provider, cache_ttl_s=60.0)
    monkeypatch.setattr(module, "portaudio_endpoint_catalog", catalog)
    service = AudioDeviceConfigService(runtime_dir=tmp_path)
    endpoints = catalog.endpoints()
    state = service.select(
        AudioEndpointSelection(
            input_device_id=endpoints[0].device_id,
            output_device_id=endpoints[1].device_id,
        )
    )
    assert state.resolved_input is not None and state.resolved_input.device_index == 1
    assert state.resolved_output is not None and state.resolved_output.device_index == 6
    assert state.selection.input_identity is not None
    assert state.selection.output_identity is not None
    assert calls == 1

    restored = AudioDeviceConfigService(runtime_dir=tmp_path)
    monkeypatch.setattr(module, "portaudio_endpoint_catalog", catalog)
    assert restored.state().selection.output_device_id == endpoints[1].device_id
    assert calls == 1


def test_legacy_wasapi_ids_migrate_only_at_the_same_wasapi_index(
    monkeypatch,
    tmp_path: Path,
) -> None:
    microphone = _portaudio_endpoint(
        3, "Legacy microphone", WasapiDirection.INPUT
    ).model_copy(
        update={
            "device_id": "sounddevice:portaudio:input:1:3",
            "host_api_index": 1,
            "host_api_name": "Windows WASAPI",
        }
    )
    speakers = _portaudio_endpoint(
        4, "Legacy speakers", WasapiDirection.OUTPUT
    ).model_copy(
        update={
            "device_id": "sounddevice:portaudio:output:1:4",
            "host_api_index": 1,
            "host_api_name": "Windows WASAPI",
        }
    )
    catalog = PortAudioEndpointCatalog(
        provider=lambda: [microphone, speakers], cache_ttl_s=60.0
    )
    monkeypatch.setattr(module, "portaudio_endpoint_catalog", catalog)
    selection_path = tmp_path / "audio-device-selection.json"
    selection_path.write_text(
        AudioEndpointSelection(
            input_device_id="sounddevice:wasapi:input:3",
            output_device_id="sounddevice:wasapi:output:4",
        ).model_dump_json(),
        encoding="utf-8",
    )

    state = AudioDeviceConfigService(runtime_dir=tmp_path).state()

    assert state.selection.input_device_id == microphone.device_id
    assert state.selection.output_device_id == speakers.device_id
    assert state.selection.input_identity == microphone.identity()
    assert state.selection.output_identity == speakers.identity()


def test_legacy_wasapi_id_never_migrates_to_non_wasapi_endpoint(
    monkeypatch,
    tmp_path: Path,
) -> None:
    microphone = _portaudio_endpoint(3, "MME microphone", WasapiDirection.INPUT)
    speakers = _portaudio_endpoint(4, "MME speakers", WasapiDirection.OUTPUT)
    catalog = PortAudioEndpointCatalog(
        provider=lambda: [microphone, speakers], cache_ttl_s=60.0
    )
    monkeypatch.setattr(module, "portaudio_endpoint_catalog", catalog)
    (tmp_path / "audio-device-selection.json").write_text(
        AudioEndpointSelection(
            input_device_id="sounddevice:wasapi:input:3",
            output_device_id="sounddevice:wasapi:output:4",
        ).model_dump_json(),
        encoding="utf-8",
    )

    state = AudioDeviceConfigService(runtime_dir=tmp_path).state()

    assert state.resolved_input is None
    assert state.resolved_output is None
    assert "reselect the exact PortAudio endpoint" in state.message
