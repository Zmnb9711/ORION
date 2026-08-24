"""Minimal ctypes binding for the pinned libopus used by SRS Radio mode."""

from __future__ import annotations

import ctypes
import sys
import threading
from pathlib import Path

OPUS_VERSION = "1.6.1"
OPUS_SAMPLE_RATE = 16_000
OPUS_CHANNELS = 1
OPUS_FRAME_SAMPLES = 640
OPUS_FRAME_BYTES = OPUS_FRAME_SAMPLES * 2
OPUS_APPLICATION_VOIP = 2048
OPUS_OK = 0
OPUS_MAX_PACKET_BYTES = 4_000


class OpusError(RuntimeError):
    pass


def opus_dll_path() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    root = Path(frozen_root) if frozen_root else Path(__file__).resolve().parent
    path = root / "native" / "win_amd64" / "opus.dll"
    if not path.is_file():
        raise OpusError(f"Pinned libopus DLL is missing: {path}")
    return path


class OpusLibrary:
    _instance: "OpusLibrary | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "OpusLibrary":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self) -> None:
        self.dll_path = opus_dll_path()
        self.dll = ctypes.CDLL(str(self.dll_path))
        self.dll.opus_get_version_string.restype = ctypes.c_char_p
        self.dll.opus_strerror.argtypes = [ctypes.c_int]
        self.dll.opus_strerror.restype = ctypes.c_char_p
        self.dll.opus_encoder_create.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        self.dll.opus_encoder_create.restype = ctypes.c_void_p
        self.dll.opus_encoder_destroy.argtypes = [ctypes.c_void_p]
        self.dll.opus_encode.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int16),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_int32,
        ]
        self.dll.opus_encode.restype = ctypes.c_int32
        self.dll.opus_decoder_create.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        self.dll.opus_decoder_create.restype = ctypes.c_void_p
        self.dll.opus_decoder_destroy.argtypes = [ctypes.c_void_p]
        self.dll.opus_decode.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_int32,
            ctypes.POINTER(ctypes.c_int16),
            ctypes.c_int,
            ctypes.c_int,
        ]
        self.dll.opus_decode.restype = ctypes.c_int
        version = self.dll.opus_get_version_string().decode("ascii", errors="replace")
        if version != f"libopus {OPUS_VERSION}":
            raise OpusError(
                f"Unexpected libopus runtime {version!r}; expected libopus {OPUS_VERSION}."
            )
        self.version = version

    def error(self, code: int) -> OpusError:
        raw = self.dll.opus_strerror(code)
        message = raw.decode("ascii", errors="replace") if raw else "unknown error"
        return OpusError(f"libopus error {code}: {message}")


class OpusEncoder:
    def __init__(self) -> None:
        self._state: int | None = None
        self.library = OpusLibrary()
        error = ctypes.c_int()
        self._state = self.library.dll.opus_encoder_create(
            OPUS_SAMPLE_RATE, OPUS_CHANNELS, OPUS_APPLICATION_VOIP, ctypes.byref(error)
        )
        if not self._state or error.value != OPUS_OK:
            self._state = None
            raise self.library.error(error.value)

    def encode(self, pcm16le: bytes) -> bytes:
        if self._state is None:
            raise OpusError("Opus encoder is closed.")
        if len(pcm16le) != OPUS_FRAME_BYTES:
            raise ValueError(f"Opus requires exactly {OPUS_FRAME_BYTES} PCM bytes per 40-ms frame.")
        pcm = (ctypes.c_int16 * OPUS_FRAME_SAMPLES).from_buffer_copy(pcm16le)
        output = (ctypes.c_ubyte * OPUS_MAX_PACKET_BYTES)()
        result = self.library.dll.opus_encode(
            self._state, pcm, OPUS_FRAME_SAMPLES, output, OPUS_MAX_PACKET_BYTES
        )
        if result < 0:
            raise self.library.error(result)
        return bytes(output[:result])

    def close(self) -> None:
        if self._state is not None:
            self.library.dll.opus_encoder_destroy(self._state)
            self._state = None

    def __enter__(self) -> "OpusEncoder":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()


class OpusDecoder:
    def __init__(self) -> None:
        self._state: int | None = None
        self.library = OpusLibrary()
        error = ctypes.c_int()
        self._state = self.library.dll.opus_decoder_create(
            OPUS_SAMPLE_RATE, OPUS_CHANNELS, ctypes.byref(error)
        )
        if not self._state or error.value != OPUS_OK:
            self._state = None
            raise self.library.error(error.value)

    def decode(self, packet: bytes) -> bytes:
        if self._state is None:
            raise OpusError("Opus decoder is closed.")
        if not packet:
            raise ValueError("Empty Opus packets are not decoded in SRS Radio v0.1.")
        encoded = (ctypes.c_ubyte * len(packet)).from_buffer_copy(packet)
        output = (ctypes.c_int16 * OPUS_FRAME_SAMPLES)()
        samples = self.library.dll.opus_decode(
            self._state, encoded, len(packet), output, OPUS_FRAME_SAMPLES, 0
        )
        if samples < 0:
            raise self.library.error(samples)
        return bytes(memoryview(output).cast("B")[: samples * 2])

    def close(self) -> None:
        if self._state is not None:
            self.library.dll.opus_decoder_destroy(self._state)
            self._state = None

    def __enter__(self) -> "OpusDecoder":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()
