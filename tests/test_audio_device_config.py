from pathlib import Path

import orion.audio_device_config as module
from orion.audio_device_config import AudioDeviceConfigService, AudioEndpointSelection
from orion.windows_wasapi_backend import WasapiDirection, WasapiEndpoint, WasapiEndpointCatalog, direction_from_device_id


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

    def provider() -> list[WasapiEndpoint]:
        nonlocal calls
        calls += 1
        return [
            WasapiEndpoint(device_id="mic", name="Microphone", direction=WasapiDirection.INPUT),
            WasapiEndpoint(device_id="headset", name="Headset", direction=WasapiDirection.OUTPUT),
        ]

    catalog = WasapiEndpointCatalog(provider=provider, cache_ttl_s=60.0)
    monkeypatch.setattr(module, "wasapi_endpoint_catalog", catalog)
    service = AudioDeviceConfigService(runtime_dir=tmp_path)
    state = service.select(AudioEndpointSelection(input_device_id="mic", output_device_id="headset"))
    assert state.resolved_input is not None and state.resolved_input.device_id == "mic"
    assert state.resolved_output is not None and state.resolved_output.device_id == "headset"
    assert calls == 1

    restored = AudioDeviceConfigService(runtime_dir=tmp_path)
    monkeypatch.setattr(module, "wasapi_endpoint_catalog", catalog)
    assert restored.state().selection.output_device_id == "headset"
    assert calls == 1
