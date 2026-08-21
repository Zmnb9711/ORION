from __future__ import annotations

import importlib
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from uuid import uuid4

from orion.native_wasapi_player import NativeWasapiPlayer
from orion.portaudio_devices import (
    PortAudioEndpoint,
    enumerate_portaudio_endpoints,
    portaudio_extra_settings,
    resolve_portaudio_endpoint,
)
from orion.tts_audio import AudioRenderRequest, TtsBackend, VoiceProfile
from orion.voice_core import VoiceAgent
from orion.windows_sapi_backend import WindowsSapiBackend
from orion.windows_wasapi_backend import WasapiDirection, WasapiEndpoint

OUTPUT_TEST_PHRASE = "Проверка звука ORION. Если вы слышите это сообщение нормально, устройство вывода работает."


@dataclass(frozen=True)
class AudioHardwareTestResult:
    ok: bool
    message: str
    peak: float | None = None
    samplerate: int | None = None


class AudioHardwareTester:
    """Short physical endpoint tests. No audio is persisted."""

    def __init__(self, sounddevice_module: ModuleType | None = None) -> None:
        self._sd = sounddevice_module

    def _sounddevice(self):
        if self._sd is None:
            self._sd = importlib.import_module("sounddevice")
        return self._sd

    def _resolve(
        self,
        endpoint: PortAudioEndpoint | WasapiEndpoint,
        direction: WasapiDirection,
    ) -> int:
        sd = self._sounddevice()
        if isinstance(endpoint, WasapiEndpoint):
            hostapis = sd.query_hostapis()
            wasapi = {
                i
                for i, item in enumerate(hostapis)
                if "wasapi" in str(item.get("name", "")).casefold()
            }
            channel_key = (
                "max_input_channels"
                if direction is WasapiDirection.INPUT
                else "max_output_channels"
            )
            candidates = [
                (index, str(item.get("name", "")))
                for index, item in enumerate(sd.query_devices())
                if int(item.get(channel_key, 0)) > 0
                and (not wasapi or int(item.get("hostapi", -1)) in wasapi)
            ]
            target = endpoint.name.casefold()
            exact = next(
                (index for index, name in candidates if name.casefold() == target),
                None,
            )
            if exact is not None:
                return exact
            partial = next(
                (
                    index
                    for index, name in candidates
                    if target in name.casefold() or name.casefold() in target
                ),
                None,
            )
            if partial is not None:
                return partial
            raise RuntimeError(
                f"WASAPI {direction.value} device not found for endpoint: {endpoint.name}"
            )
        return resolve_portaudio_endpoint(
            enumerate_portaudio_endpoints(sd),
            endpoint.device_id,
            direction,
            identity=endpoint.identity(),
        ).device_index

    def _native_samplerate(self, device: int, fallback: int = 48000) -> int:
        sd = self._sounddevice()
        info = sd.query_devices(device)
        try:
            samplerate = int(round(float(info.get("default_samplerate", fallback))))
        except (TypeError, ValueError):
            samplerate = fallback
        return samplerate if samplerate > 0 else fallback

    def test_input(
        self,
        endpoint: PortAudioEndpoint | WasapiEndpoint,
        duration_seconds: float = 1.5,
    ) -> AudioHardwareTestResult:
        sd = self._sounddevice()
        device = self._resolve(endpoint, WasapiDirection.INPUT)
        samplerate = self._native_samplerate(device)
        frames = max(1, int(duration_seconds * samplerate))
        if isinstance(endpoint, PortAudioEndpoint):
            extra_settings, _mode = portaudio_extra_settings(sd, endpoint)
        else:
            extra_settings = None
        try:
            with sd.RawInputStream(
                samplerate=samplerate,
                device=device,
                channels=1,
                dtype="int16",
                extra_settings=extra_settings,
            ) as stream:
                data, _overflowed = stream.read(frames)
        except Exception as exc:
            raise RuntimeError(
                f"Microphone could not be opened at its PortAudio sample rate ({samplerate} Hz): {exc}"
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

    def test_output(
        self,
        endpoint: PortAudioEndpoint | WasapiEndpoint,
        duration_seconds: float = 0.45,
    ) -> AudioHardwareTestResult:
        del duration_seconds
        try:
            with tempfile.TemporaryDirectory(prefix="orion-output-test-") as tmp:
                backend = WindowsSapiBackend(spool_dir=str(Path(tmp) / "tts"))
                request = AudioRenderRequest(
                    command_id=f"output-test-{uuid4()}",
                    text=OUTPUT_TEST_PHRASE,
                    agent=VoiceAgent.SYSTEM,
                    profile=VoiceProfile(
                        profile_id="output_test_ru",
                        locale="ru-RU",
                        persona="orion",
                        rate=1.0,
                        volume=1.0,
                    ),
                    backend=TtsBackend.WINDOWS_SAPI,
                    output_device=endpoint.device_id,
                )
                rendered = backend.render(request)
                if not rendered.accepted or not rendered.output_path:
                    raise RuntimeError(rendered.message)
                NativeWasapiPlayer().play(Path(rendered.output_path), endpoint)
        except Exception as exc:
            raise RuntimeError(f"Spoken output test failed for {endpoint.name}: {exc}") from exc
        return AudioHardwareTestResult(
            ok=True,
            message=f"Output PASS — spoken ORION test phrase played through {endpoint.name}",
        )
