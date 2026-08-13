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
    samplerate: int | None = None


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

    def _native_samplerate(self, device: int, fallback: int = 48000) -> int:
        sd = self._sounddevice()
        info = sd.query_devices(device)
        try:
            samplerate = int(round(float(info.get("default_samplerate", fallback))))
        except (TypeError, ValueError):
            samplerate = fallback
        return samplerate if samplerate > 0 else fallback

    def test_input(self, endpoint: WasapiEndpoint, duration_seconds: float = 1.5) -> AudioHardwareTestResult:
        sd = self._sounddevice()
        device = self._resolve(endpoint, WasapiDirection.INPUT)
        samplerate = self._native_samplerate(device)
        frames = max(1, int(duration_seconds * samplerate))
        try:
            with sd.RawInputStream(samplerate=samplerate, device=device, channels=1, dtype="int16") as stream:
                data, _overflowed = stream.read(frames)
        except Exception as exc:
            raise RuntimeError(
                f"Microphone could not be opened at its Windows/WASAPI sample rate ({samplerate} Hz): {exc}"
            ) from exc
        peak_sample = 0
        for (sample,) in struct.iter_unpack("<h", bytes(data)):
            peak_sample = max(peak_sample, abs(sample))
        peak = peak_sample / 32767.0
        if peak > 0.001:
            message = f"Microphone PASS — signal detected (peak {peak:.3f}, {samplerate} Hz)"
        else:
            message = f"Microphone WARNING — no useful signal detected (peak {peak:.3f}, {samplerate} Hz)"
        return AudioHardwareTestResult(ok=peak > 0.001, peak=peak, samplerate=samplerate, message=message)

    def test_output(self, endpoint: WasapiEndpoint, duration_seconds: float = 0.45) -> AudioHardwareTestResult:
        sd = self._sounddevice()
        device = self._resolve(endpoint, WasapiDirection.OUTPUT)
        samplerate = self._native_samplerate(device)
        frames = max(1, int(duration_seconds * samplerate))
        samples = bytearray()
        # A short, lower-level two-frequency confirmation chime is less harsh than
        # the previous single 660 Hz tone while still testing the physical path.
        split = max(1, frames // 2)
        for n in range(frames):
            frequency = 523.25 if n < split else 659.25
            envelope = min(1.0, n / max(1, int(0.02 * samplerate)), (frames - n) / max(1, int(0.03 * samplerate)))
            value = int(3500 * envelope * math.sin(2.0 * math.pi * frequency * n / samplerate))
            samples.extend(struct.pack("<h", value))
        try:
            with sd.RawOutputStream(samplerate=samplerate, device=device, channels=1, dtype="int16") as stream:
                stream.write(bytes(samples))
        except Exception as exc:
            raise RuntimeError(
                f"Output device could not be opened at its Windows/WASAPI sample rate ({samplerate} Hz): {exc}"
            ) from exc
        return AudioHardwareTestResult(
            ok=True,
            samplerate=samplerate,
            message=f"Output PASS — confirmation chime played through {endpoint.name} ({samplerate} Hz)",
        )
