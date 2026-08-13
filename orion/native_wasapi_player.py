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
        except (ImportError, OSError):
            return False

    def play(self, path: Path, endpoint: WasapiEndpoint, volume: float = 1.0) -> None:
        if not path.exists():
            raise FileNotFoundError(path)
        if not 0.0 <= volume <= 1.0:
            raise ValueError("volume must be between 0.0 and 1.0")
        sd = self._sounddevice()
        device_index = self._resolve_device(sd, endpoint)
        self._stop_event.clear()

        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            source_rate = wav.getframerate()
            dtype = {1: "uint8", 2: "int16", 3: "int24", 4: "int32"}.get(sample_width)
            if dtype is None:
                raise RuntimeError(f"Unsupported WAV sample width: {sample_width}")

            target_rate = self._native_samplerate(sd, device_index, fallback=source_rate)
            extra_settings = sd.WasapiSettings(exclusive=False)
            with sd.RawOutputStream(
                samplerate=target_rate,
                blocksize=self._chunk_frames,
                device=device_index,
                channels=channels,
                dtype=dtype,
                extra_settings=extra_settings,
            ) as stream:
                with self._lock:
                    self._stream = stream
                try:
                    if target_rate == source_rate:
                        while not self._stop_event.is_set():
                            data = wav.readframes(self._chunk_frames)
                            if not data:
                                break
                            if volume != 1.0:
                                data = self._scale_pcm(data, sample_width=sample_width, volume=volume)
                            stream.write(data)
                    else:
                        source = wav.readframes(wav.getnframes())
                        converted = self._resample_pcm(
                            source,
                            sample_width=sample_width,
                            channels=channels,
                            source_rate=source_rate,
                            target_rate=target_rate,
                        )
                        frame_bytes = sample_width * channels
                        chunk_bytes = self._chunk_frames * frame_bytes
                        for offset in range(0, len(converted), chunk_bytes):
                            if self._stop_event.is_set():
                                break
                            data = converted[offset : offset + chunk_bytes]
                            if volume != 1.0:
                                data = self._scale_pcm(data, sample_width=sample_width, volume=volume)
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
            except (OSError, RuntimeError):
                pass

    def _sounddevice(self):
        if self._sd is None:
            self._sd = importlib.import_module("sounddevice")
        return self._sd

    @staticmethod
    def _native_samplerate(sd, device_index: int, fallback: int) -> int:
        info = sd.query_devices(device_index)
        try:
            samplerate = int(round(float(info.get("default_samplerate", fallback))))
        except (TypeError, ValueError):
            samplerate = fallback
        return samplerate if samplerate > 0 else fallback

    @staticmethod
    def _scale_pcm(data: bytes, *, sample_width: int, volume: float) -> bytes:
        if volume == 1.0 or not data:
            return data
        if sample_width == 1:
            return bytes(max(0, min(255, round((sample - 128) * volume + 128))) for sample in data)

        bits = sample_width * 8
        minimum = -(1 << (bits - 1))
        maximum = (1 << (bits - 1)) - 1
        output = bytearray(len(data))
        for offset in range(0, len(data), sample_width):
            sample = int.from_bytes(data[offset : offset + sample_width], "little", signed=True)
            scaled = max(minimum, min(maximum, round(sample * volume)))
            output[offset : offset + sample_width] = scaled.to_bytes(sample_width, "little", signed=True)
        return bytes(output)

    @classmethod
    def _resample_pcm(
        cls,
        data: bytes,
        *,
        sample_width: int,
        channels: int,
        source_rate: int,
        target_rate: int,
    ) -> bytes:
        if source_rate <= 0 or target_rate <= 0:
            raise ValueError("PCM sample rates must be positive")
        if channels <= 0:
            raise ValueError("PCM channel count must be positive")
        if source_rate == target_rate or not data:
            return data
        frame_bytes = sample_width * channels
        if len(data) % frame_bytes:
            raise ValueError("PCM byte stream is not aligned to complete frames")
        source_frames = len(data) // frame_bytes
        if source_frames < 2:
            return data
        output_frames = max(1, round(source_frames * target_rate / source_rate))
        scale = 0.0 if output_frames == 1 else (source_frames - 1) / (output_frames - 1)
        output = bytearray(output_frames * frame_bytes)

        for frame_index in range(output_frames):
            position = frame_index * scale
            left = int(position)
            right = min(left + 1, source_frames - 1)
            fraction = position - left
            for channel in range(channels):
                left_offset = (left * channels + channel) * sample_width
                right_offset = (right * channels + channel) * sample_width
                left_sample = cls._decode_sample(data[left_offset : left_offset + sample_width], sample_width)
                right_sample = cls._decode_sample(data[right_offset : right_offset + sample_width], sample_width)
                value = round(left_sample * (1.0 - fraction) + right_sample * fraction)
                target_offset = (frame_index * channels + channel) * sample_width
                output[target_offset : target_offset + sample_width] = cls._encode_sample(value, sample_width)
        return bytes(output)

    @staticmethod
    def _decode_sample(raw: bytes, sample_width: int) -> int:
        if sample_width == 1:
            return raw[0] - 128
        return int.from_bytes(raw, "little", signed=True)

    @staticmethod
    def _encode_sample(sample: int, sample_width: int) -> bytes:
        bits = sample_width * 8
        minimum = -(1 << (bits - 1))
        maximum = (1 << (bits - 1)) - 1
        sample = max(minimum, min(maximum, sample))
        if sample_width == 1:
            return bytes((sample + 128,))
        return sample.to_bytes(sample_width, "little", signed=True)

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
