from __future__ import annotations

import struct
from pathlib import Path
from types import SimpleNamespace

import orion.audio_hardware_test as subject
from orion.audio_hardware_test import AudioHardwareTester, OUTPUT_TEST_PHRASE
from orion.windows_wasapi_backend import WasapiDirection, WasapiEndpoint


class FakeStream:
    def __init__(self, payload: bytes = b"") -> None:
        self.payload = payload
        self.written = b""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, frames: int):
        return self.payload, False

    def write(self, data: bytes) -> None:
        self.written += data


class FakeSoundDevice:
    def __init__(self) -> None:
        self.input_stream = FakeStream(struct.pack("<hhh", 0, 4000, -2000))
        self.input_kwargs = None
        self.devices = [
            {
                "name": "Test Microphone",
                "max_input_channels": 1,
                "max_output_channels": 0,
                "hostapi": 0,
                "default_samplerate": 48000.0,
            },
            {
                "name": "Test Output",
                "max_input_channels": 0,
                "max_output_channels": 2,
                "hostapi": 0,
                "default_samplerate": 44100.0,
            },
        ]

    def query_hostapis(self):
        return [{"name": "Windows WASAPI"}]

    def query_devices(self, device=None):
        return self.devices if device is None else self.devices[device]

    def RawInputStream(self, **kwargs):
        self.input_kwargs = kwargs
        return self.input_stream


def test_input_probe_uses_device_native_rate_and_reports_signal() -> None:
    sd = FakeSoundDevice()
    tester = AudioHardwareTester(sd)
    endpoint = WasapiEndpoint(device_id="mic", name="Test Microphone", direction=WasapiDirection.INPUT)
    result = tester.test_input(endpoint, duration_seconds=0.001)
    assert result.ok
    assert result.peak is not None and result.peak > 0.1
    assert result.samplerate == 48000
    assert sd.input_kwargs["samplerate"] == 48000


def test_output_probe_uses_spoken_phrase_and_selected_endpoint(monkeypatch) -> None:
    endpoint = WasapiEndpoint(device_id="out", name="Test Output", direction=WasapiDirection.OUTPUT)
    captured: dict[str, object] = {}

    class Backend:
        def __init__(self, spool_dir: str) -> None:
            self.spool_dir = Path(spool_dir)

        def render(self, request):
            captured["text"] = request.text
            captured["output_device"] = request.output_device
            target = self.spool_dir / "test.wav"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"RIFF")
            return SimpleNamespace(accepted=True, output_path=str(target), message="ok")

    class Player:
        def play(self, path, selected_endpoint) -> None:
            captured["played_path"] = Path(path)
            captured["endpoint"] = selected_endpoint

    monkeypatch.setattr(subject, "WindowsSapiBackend", Backend)
    monkeypatch.setattr(subject, "NativeWasapiPlayer", Player)

    result = AudioHardwareTester(FakeSoundDevice()).test_output(endpoint)
    assert result.ok
    assert OUTPUT_TEST_PHRASE in str(captured["text"])
    assert captured["output_device"] == "out"
    assert captured["endpoint"] == endpoint
    assert "spoken ORION test phrase" in result.message
