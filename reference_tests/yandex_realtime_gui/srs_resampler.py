"""Stateful PCM16 mono resampling for the SRS/Yandex bridge."""

from __future__ import annotations

from typing import Final

import numpy as np
import samplerate

SRS_RATE: Final = 16_000
YANDEX_RATE: Final = 44_100
RX_RATIO: Final = 441 / 160
TX_RATIO: Final = 160 / 441
# The linear streaming converter has zero filter look-ahead.  That matters for
# discrete radio turns: every input sample is accounted for without borrowing
# a hidden tail from the next transmission.  It is still stateful and is used
# continuously across packet/provider chunk boundaries.
CONVERTER: Final = "linear"


class StreamingPcm16Resampler:
    """One mono streaming libsamplerate state with explicit finalization."""

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
    probe = StreamingPcm16Resampler(SRS_RATE, YANDEX_RATE)
    output = probe.process(bytes(640 * 2), end_of_input=True)
    return {
        "samplerate_version": samplerate.__version__,
        "input_samples": probe.input_samples,
        "output_samples": probe.output_samples,
        "output_bytes": len(output),
    }
