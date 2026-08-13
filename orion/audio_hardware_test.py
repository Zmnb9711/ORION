from __future__ import annotations

import importlib
import math
import struct
from dataclasses import dataclass
from types import ModuleType

from orion.windows_wasapi_backend import WasapiDirection, WasapiEndpoint


@dataclass(frozen=True)
class AudioHardwareTestResult:
    ok: bool
    message: str
    peak: float | None = None


class AudioHardwareTester:
    """Short physical endpoint tests. No audio is persisted and no STT/TTS is involved."""

    def __init__(self, sounddevice_module: ModuleType | None = None) -> None:
        self._sd = sounddevice_module

    def _sounddevice(self):
        if self._sd is None:
            self._sd = importlib.import_module("sounddevice")
        return self._sd

    def _resolve(self, endpoint: WasapiEndpoint, direction: WasapiDirection) -> int:
        sd = self._sounddevice()
        hostapis = sd.query_hostapis()
        wasapi = {i for i, item in enumerate(hostapis) if "wasapi" in str(item.get("name", "")).casefold()}
        target = endpoint.name.casefold()
        channel_key = "max_input_channels" if direction is WasapiDirection.INPUT else "max_output_channels"
        candidates: list[tuple[int, str]] = []
        for index, item in enumerate(sd.query_devices()):
            if int(item.get(channel_key, 0)) <= 0:
                continue
            if wasapi and int(item.get("hostapi", -1)) not in wasapi:
                continue
            candidates.append((index, str(item.get("name", ""))))
        exact = next((i for i, name in candidates if name.casefold() == target), None)
        if exact is not None:
            return exact
        partial = next((i for i, name in candidates if target in name.casefold() or name.casefold() in target), None)
        if partial is not None:
            return partial
        raise RuntimeError(f"WASAPI {direction.value} device not found for endpoint: {endpoint.name}")

    def test_input(self, endpoint: WasapiEndpoint, duration_seconds: float = 1.0) -> AudioHardwareTestResult:
        sd = self._sounddevice()
        device = self._resolve(endpoint, WasapiDirection.INPUT)
        samplerate = 16000
        frames = max(1, int(duration_seconds * samplerate))
        with sd.RawInputStream(samplerate=samplerate, device=device, channels=1, dtype="int16") as stream:
            data, _overflowed = stream.read(frames)
        peak_sample = 0
        for (sample,) in struct.iter_unpack("<h", bytes(data)):
            peak_sample = max(peak_sample, abs(sample))
        peak = peak_sample / 32767.0
        return AudioHardwareTestResult(ok=peak > 0.001, peak=peak, message=f"Microphone signal peak: {peak:.3f}")

    def test_output(self, endpoint: WasapiEndpoint, duration_seconds: float = 0.6) -> AudioHardwareTestResult:
        sd = self._sounddevice()
        device = self._resolve(endpoint, WasapiDirection.OUTPUT)
        samplerate = 48000
        frames = max(1, int(duration_seconds * samplerate))
        samples = bytearray()
        for n in range(frames):
            value = int(7000 * math.sin(2.0 * math.pi * 660.0 * n / samplerate))
            samples.extend(struct.pack("<h", value))
        with sd.RawOutputStream(samplerate=samplerate, device=device, channels=1, dtype="int16") as stream:
            stream.write(bytes(samples))
        return AudioHardwareTestResult(ok=True, message=f"Test tone played through {endpoint.name}")
