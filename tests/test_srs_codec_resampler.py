from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path

import numpy as np
import pytest

from orion.srs_opus import (
    OPUS_FRAME_BYTES,
    OPUS_FRAME_SAMPLES,
    OpusDecoder,
    OpusEncoder,
    OpusError,
    OpusLibrary,
    opus_dll_path,
)
from orion.srs_resampler import StreamingPcm16Resampler, make_rx_resampler, make_tx_resampler


def tone(samples: int, rate: int, frequency: float = 440.0) -> bytes:
    positions = np.arange(samples, dtype=np.float64)
    signal = np.rint(np.sin(2 * math.pi * frequency * positions / rate) * 12_000).astype("<i2")
    return signal.tobytes()


@pytest.mark.skipif(sys.platform != "win32", reason="Pinned production DLL is Windows-only")
def test_pinned_opus_load_create_roundtrip_repeat_destroy_and_hash() -> None:
    path = Path(opus_dll_path())
    assert path.is_file()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "82b454192834e0afce0d5ce3c46f2deba653ac437f369d847ab8043a93157808"
    )
    assert OpusLibrary().version == "libopus 1.6.1"
    pcm = tone(OPUS_FRAME_SAMPLES, 16_000)
    encoder = OpusEncoder()
    decoder = OpusDecoder()
    try:
        for _ in range(20):
            encoded = encoder.encode(pcm)
            assert 0 < len(encoded) < OPUS_FRAME_BYTES
            assert len(decoder.decode(encoded)) == OPUS_FRAME_BYTES
    finally:
        encoder.close()
        decoder.close()
    with pytest.raises(OpusError, match="closed"):
        encoder.encode(pcm)


@pytest.mark.skipif(sys.platform != "win32", reason="Pinned production DLL is Windows-only")
def test_opus_rejects_wrong_pcm_size_and_invalid_packet() -> None:
    with OpusEncoder() as encoder:
        with pytest.raises(ValueError, match="exactly"):
            encoder.encode(bytes(OPUS_FRAME_BYTES - 2))
    with OpusDecoder() as decoder:
        with pytest.raises((OpusError, ValueError)):
            decoder.decode(b"not opus")


@pytest.mark.parametrize("input_rate,output_rate", [(16_000, 44_100), (44_100, 16_000)])
def test_streaming_resampler_chunk_invariance_and_long_run_accounting(
    input_rate: int,
    output_rate: int,
) -> None:
    pcm = tone(input_rate * 3, input_rate, 317.0)
    one = StreamingPcm16Resampler(input_rate, output_rate)
    one_output = one.process(pcm, end_of_input=True)
    many = StreamingPcm16Resampler(input_rate, output_rate)
    pieces: list[bytes] = []
    counts = [137, 509, 41, 1000, 333, 77]
    cursor = 0
    total = len(pcm) // 2
    index = 0
    while cursor < total:
        count = min(counts[index % len(counts)], total - cursor)
        pieces.append(
            many.process(
                pcm[cursor * 2 : (cursor + count) * 2],
                end_of_input=cursor + count == total,
            )
        )
        cursor += count
        index += 1
    many_output = b"".join(pieces)
    expected = round(total * output_rate / input_rate)
    assert abs(len(one_output) // 2 - expected) <= 1
    assert abs(len(many_output) // 2 - expected) <= 1
    a = np.frombuffer(one_output, dtype="<i2").astype(np.int32)
    b = np.frombuffer(many_output, dtype="<i2").astype(np.int32)
    common = min(a.size, b.size)
    assert common > 0
    assert np.max(np.abs(a[:common] - b[:common])) <= 2


def test_rx_tx_states_are_independent_reset_is_explicit_and_odd_pcm_rejected() -> None:
    rx = make_rx_resampler()
    tx = make_tx_resampler()
    assert rx.process(tone(640, 16_000))
    assert tx.process(tone(1764, 44_100))
    assert rx.input_samples == 640 and tx.input_samples == 1764
    rx.process(b"", end_of_input=True)
    with pytest.raises(RuntimeError, match="finalized"):
        rx.process(bytes(2))
    rx.reset()
    assert rx.input_samples == rx.output_samples == 0
    with pytest.raises(ValueError, match="complete"):
        rx.process(b"\0")
