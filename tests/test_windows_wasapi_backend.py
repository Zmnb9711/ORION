from pathlib import Path

from fastapi.testclient import TestClient

import orion.windows_wasapi_backend as wasapi_module
import orion.portaudio_devices as portaudio_module
from orion.app import app
from orion.portaudio_devices import PortAudioEndpoint
from orion.windows_wasapi_backend import WasapiEndpoint, WasapiEndpointCatalog, WasapiPlaybackBackend
from orion.windows_wasapi_backend import WasapiDirection


def _endpoints() -> list[WasapiEndpoint]:
    return [
        WasapiEndpoint(device_id="default-id", name="Speakers (Realtek)", is_default=True),
        WasapiEndpoint(device_id="pimax-id", name="Pimax Crystal Headset"),
        WasapiEndpoint(device_id="dream-id", name="Dream Air VR Audio"),
    ]


def test_choose_endpoint_by_exact_id_and_partial_name() -> None:
    catalog = WasapiEndpointCatalog(provider=_endpoints)
    assert catalog.choose("pimax-id").name == "Pimax Crystal Headset"
    assert catalog.choose("dream air").device_id == "dream-id"
    assert catalog.choose("default").device_id == "default-id"


def test_vr_candidates_filters_regular_speakers() -> None:
    catalog = WasapiEndpointCatalog(provider=_endpoints)
    assert [item.device_id for item in catalog.vr_candidates()] == ["pimax-id", "dream-id"]


def test_playback_backend_passes_resolved_endpoint(tmp_path) -> None:
    wav = tmp_path / "voice.wav"
    wav.write_bytes(b"RIFF")
    calls: list[tuple[Path, str, float]] = []
    catalog = WasapiEndpointCatalog(provider=_endpoints)
    backend = WasapiPlaybackBackend(
        catalog,
        lambda path, endpoint, volume: calls.append((path, endpoint.device_id, volume)),
        lambda: None,
    )

    selected = backend.play_wav(wav, "Pimax", 0.7)

    assert selected.device_id == "pimax-id"
    assert calls == [(wav, "pimax-id", 0.7)]


def test_wasapi_endpoint_api(monkeypatch) -> None:
    monkeypatch.setattr(wasapi_module.wasapi_endpoint_catalog, "_provider", _endpoints)
    with TestClient(app) as client:
        all_response = client.get("/v1/windows-audio/wasapi/endpoints")
        vr_response = client.get("/v1/windows-audio/wasapi/vr-candidates")

    assert all_response.status_code == 200
    assert len(all_response.json()) == 3
    assert vr_response.status_code == 200
    assert [item["device_id"] for item in vr_response.json()] == ["pimax-id", "dream-id"]


def test_portaudio_endpoint_api_includes_host_api_identity(monkeypatch) -> None:
    microphone = PortAudioEndpoint(
        device_id="sounddevice:portaudio:input:0:1",
        name="Microphone (Pimax Dream Air)",
        device_name="Microphone (Pimax Dream Air)",
        direction=WasapiDirection.INPUT,
        device_index=1,
        host_api_index=0,
        host_api_name="MME",
        max_input_channels=2,
        max_output_channels=0,
        default_samplerate=44_100,
    )
    monkeypatch.setattr(
        portaudio_module.portaudio_endpoint_catalog,
        "_provider",
        lambda: [microphone],
    )
    portaudio_module.portaudio_endpoint_catalog._cache = []

    with TestClient(app) as client:
        response = client.get("/v1/windows-audio/portaudio/inputs")

    assert response.status_code == 200
    assert response.json()[0]["device_index"] == 1
    assert response.json()[0]["host_api_name"] == "MME"
