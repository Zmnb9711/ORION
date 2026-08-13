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


def test_core_selection_persists_and_resolves(monkeypatch, tmp_path: Path) -> None:
    catalog = WasapiEndpointCatalog(provider=lambda: [
        WasapiEndpoint(device_id="mic", name="Microphone", direction=WasapiDirection.INPUT),
        WasapiEndpoint(device_id="headset", name="Headset", direction=WasapiDirection.OUTPUT),
    ])
    monkeypatch.setattr(module, "wasapi_endpoint_catalog", catalog)
    service = AudioDeviceConfigService(runtime_dir=tmp_path)
    state = service.select(AudioEndpointSelection(input_device_id="mic", output_device_id="headset"))
    assert state.resolved_input is not None and state.resolved_input.device_id == "mic"
    assert state.resolved_output is not None and state.resolved_output.device_id == "headset"

    restored = AudioDeviceConfigService(runtime_dir=tmp_path)
    monkeypatch.setattr(module, "wasapi_endpoint_catalog", catalog)
    assert restored.state().selection.output_device_id == "headset"
