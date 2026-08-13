from __future__ import annotations

import struct

from orion.audio_hardware_test import AudioHardwareTester
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
        self.output_stream = FakeStream()

    def query_hostapis(self):
        return [{"name": "Windows WASAPI"}]

    def query_devices(self):
        return [
            {"name": "Test Microphone", "max_input_channels": 1, "max_output_channels": 0, "hostapi": 0},
            {"name": "Test Output", "max_input_channels": 0, "max_output_channels": 2, "hostapi": 0},
        ]

    def RawInputStream(self, **kwargs):
        return self.input_stream

    def RawOutputStream(self, **kwargs):
        return self.output_stream


def test_input_probe_reports_signal() -> None:
    tester = AudioHardwareTester(FakeSoundDevice())
    endpoint = WasapiEndpoint(device_id="mic", name="Test Microphone", direction=WasapiDirection.INPUT)
    result = tester.test_input(endpoint, duration_seconds=0.001)
    assert result.ok
    assert result.peak is not None and result.peak > 0.1


def test_output_probe_writes_tone() -> None:
    sd = FakeSoundDevice()
    tester = AudioHardwareTester(sd)
    endpoint = WasapiEndpoint(device_id="out", name="Test Output", direction=WasapiDirection.OUTPUT)
    result = tester.test_output(endpoint, duration_seconds=0.001)
    assert result.ok
    assert sd.output_stream.written
