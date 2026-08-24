"""Stateful PCM16 mono conversion for production SRS transport."""

from __future__ import annotations

from typing import Final

import numpy as np
import samplerate

SRS_RATE: Final = 16_000
YANDEX_RATE: Final = 44_100
RX_RATIO: Final = 441 / 160
TX_RATIO: Final = 160 / 441
CONVERTER: Final = "linear"


class StreamingPcm16Resampler:
    def __init__(self, input_rate: int, output_rate: int) -> None:
        if input_rate <= 0 or output_rate <= 0:
            raise ValueError("Sample rates must be positive.")
        self.input_rate = input_rate
        self.output_rate = output_rate
        self.ratio = output_rate / input_rate
        self._resampler = samplerate.Resampler(CONVERTER, channels=1)
        self.input_samples = 0
        self.output_samples = 0
        self._finalized = False

    def process(self, pcm16le: bytes, *, end_of_input: bool = False) -> bytes:
        if self._finalized:
            raise RuntimeError("Resampler stream is finalized; reset before reuse.")
        if len(pcm16le) % 2:
            raise ValueError("PCM16 input must contain complete little-endian samples.")
        samples = np.frombuffer(pcm16le, dtype="<i2")
        self.input_samples += int(samples.size)
        normalized = samples.astype(np.float32) / 32768.0
        converted = self._resampler.process(normalized, self.ratio, end_of_input)
        self._finalized = end_of_input
        if converted.size == 0:
            return b""
        quantized = np.rint(np.clip(converted, -1.0, 32767 / 32768) * 32768.0).astype("<i2")
        self.output_samples += int(quantized.size)
        return quantized.tobytes()

    def reset(self) -> None:
        self._resampler.reset()
        self.input_samples = 0
        self.output_samples = 0
        self._finalized = False

    @property
    def finalized(self) -> bool:
        return self._finalized


def make_rx_resampler() -> StreamingPcm16Resampler:
    return StreamingPcm16Resampler(SRS_RATE, YANDEX_RATE)


def make_tx_resampler() -> StreamingPcm16Resampler:
    return StreamingPcm16Resampler(YANDEX_RATE, SRS_RATE)


def offline_smoke() -> dict[str, object]:
    rx = make_rx_resampler()
    pcm44 = rx.process(bytes(640 * 2), end_of_input=True)
    tx = make_tx_resampler()
    pcm16 = tx.process(pcm44, end_of_input=True)
    return {
        "samplerate_version": samplerate.__version__,
        "rx_input_samples": rx.input_samples,
        "rx_output_samples": rx.output_samples,
        "tx_output_samples": tx.output_samples,
        "roundtrip_bytes": len(pcm16),
    }
