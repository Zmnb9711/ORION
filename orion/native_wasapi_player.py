from __future__ import annotations

import importlib
import threading
import wave
from pathlib import Path
from types import ModuleType

from orion.windows_wasapi_backend import WasapiEndpoint


class NativeWasapiPlayer:
    """Shared-mode WASAPI player backed by python-sounddevice/PortAudio.

    The dependency is optional and loaded only on Windows/audio-worker installations.
    Playback is chunked so stop/preemption can interrupt between writes.
    """

    def __init__(self, sounddevice_module: ModuleType | None = None, chunk_frames: int = 2048) -> None:
        self._sd = sounddevice_module
        self._chunk_frames = chunk_frames
        self._stop_event = threading.Event()
        self._stream = None
        self._lock = threading.RLock()

    @property
    def available(self) -> bool:
        try:
            self._sounddevice()
            return True
        except Exception:
            return False

    def play(self, path: Path, endpoint: WasapiEndpoint, volume: float = 1.0) -> None:
        if not path.exists():
            raise FileNotFoundError(path)
        sd = self._sounddevice()
        device_index = self._resolve_device(sd, endpoint)
        self._stop_event.clear()

        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            dtype = {1: "uint8", 2: "int16", 3: "int24", 4: "int32"}.get(sample_width)
            if dtype is None:
                raise RuntimeError(f"Unsupported WAV sample width: {sample_width}")

            extra_settings = sd.WasapiSettings(exclusive=False)
            with sd.RawOutputStream(
                samplerate=sample_rate,
                blocksize=self._chunk_frames,
                device=device_index,
                channels=channels,
                dtype=dtype,
                extra_settings=extra_settings,
            ) as stream:
                with self._lock:
                    self._stream = stream
                try:
                    while not self._stop_event.is_set():
                        data = wav.readframes(self._chunk_frames)
                        if not data:
                            break
                        stream.write(data)
                finally:
                    with self._lock:
                        self._stream = None

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            stream = self._stream
        if stream is not None:
            try:
                stream.abort()
            except Exception:
                pass

    def _sounddevice(self):
        if self._sd is None:
            self._sd = importlib.import_module("sounddevice")
        return self._sd

    @staticmethod
    def _resolve_device(sd, endpoint: WasapiEndpoint) -> int:
        hostapis = sd.query_hostapis()
        wasapi_hostapis = {
            index for index, item in enumerate(hostapis)
            if "wasapi" in str(item.get("name", "")).casefold()
        }
        devices = sd.query_devices()
        endpoint_name = endpoint.name.casefold()

        candidates: list[tuple[int, str]] = []
        for index, item in enumerate(devices):
            if int(item.get("max_output_channels", 0)) <= 0:
                continue
            if wasapi_hostapis and int(item.get("hostapi", -1)) not in wasapi_hostapis:
                continue
            name = str(item.get("name", ""))
            candidates.append((index, name))

        if not candidates:
            raise RuntimeError("No WASAPI output devices are available")

        exact = next((index for index, name in candidates if name.casefold() == endpoint_name), None)
        if exact is not None:
            return exact
        partial = next(
            (index for index, name in candidates if endpoint_name in name.casefold() or name.casefold() in endpoint_name),
            None,
        )
        if partial is not None:
            return partial
        raise RuntimeError(f"WASAPI playback device not found for endpoint: {endpoint.name}")
