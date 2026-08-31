from __future__ import annotations

import threading
import time

import pytest

from orion.radio_streaming import (
    BoundedPcmStream,
    Pcm16ChunkAligner,
    StreamingPcmEvent,
    StreamingPcmState,
)


def _stream(
    response_id: str = "stream-response",
    *,
    prebuffer_ms: int = 100,
    max_buffer_ms: int = 200,
    capture: bool = True,
) -> BoundedPcmStream:
    return BoundedPcmStream(
        response_id,
        sample_rate_hz=8_000,
        prebuffer_ms=prebuffer_ms,
        max_buffer_ms=max_buffer_ms,
        max_total_bytes=20_000,
        capture=capture,
    )


def test_provider_neutral_event_and_odd_chunk_alignment() -> None:
    first = StreamingPcmEvent(
        response_id="response-1",
        pcm=b"\x01\x02\x03",
        sample_rate_hz=48_000,
        channels=1,
        sample_width_bytes=2,
        chunk_index=0,
    )
    aligner = Pcm16ChunkAligner()
    assert aligner.push(first.pcm) == b"\x01\x02"
    assert aligner.push(b"\x04\x05\x06") == b"\x03\x04\x05\x06"
    assert aligner.finish() == b""

    aligner.push(b"\x01")
    with pytest.raises(ValueError, match="incomplete PCM16"):
        aligner.finish()


def test_prebuffer_is_bounded_and_eos_drains_in_exact_order() -> None:
    source = _stream()
    first = bytes(range(100)) * 16
    second = bytes(reversed(range(100))) * 16
    source.feed(first)
    snapshot = source.wait_for_prebuffer(0.1)
    assert snapshot.buffered_bytes == 1_600
    assert snapshot.state is StreamingPcmState.OPEN
    source.feed(second)
    source.finish()

    output = bytearray()
    while True:
        read = source.read(74, timeout_s=0.01)
        output.extend(read.data)
        if read.state is StreamingPcmState.END_OF_STREAM and not read.data:
            break
    snapshot = source.snapshot()
    assert bytes(output) == first + second
    assert snapshot.total_pcm_bytes == len(first + second)
    assert snapshot.max_buffered_bytes <= source.max_buffer_bytes
    assert snapshot.buffered_bytes == 0
    assert snapshot.captured_pcm == first + second


def test_faster_than_realtime_producer_applies_backpressure_without_loss() -> None:
    source = _stream(prebuffer_ms=50, max_buffer_ms=100)
    first = b"\x01\x00" * 800
    second = b"\x02\x00" * 800
    source.feed(first)
    producer_done = threading.Event()

    def produce() -> None:
        source.feed(second, timeout_s=1.0)
        source.finish()
        producer_done.set()

    producer = threading.Thread(target=produce)
    producer.start()
    time.sleep(0.03)
    assert not producer_done.is_set()
    assert source.snapshot().buffered_bytes == source.max_buffer_bytes
    first_read = source.read(len(first), timeout_s=0.1)
    assert first_read.data == first
    assert producer_done.wait(1.0)
    second_read = source.read(len(second), timeout_s=0.1)
    assert second_read.data == second
    terminal = source.read(2, timeout_s=0.1)
    assert terminal.state is StreamingPcmState.END_OF_STREAM
    assert source.snapshot().max_buffered_bytes <= source.max_buffer_bytes
    producer.join(1.0)


def test_failure_and_cancellation_discard_unsent_pcm_without_cross_response_leak() -> None:
    failed = _stream("failed")
    failed.feed(b"\x01\x00" * 800)
    failed.fail("bounded provider failure")
    read = failed.read(1_600)
    assert read.state is StreamingPcmState.FAILED
    assert read.data == b""
    assert read.error == "bounded provider failure"

    cancelled = _stream("cancelled")
    cancelled.feed(b"\x02\x00" * 800)
    cancelled.cancel()
    assert cancelled.read(1_600).state is StreamingPcmState.CANCELLED

    next_response = _stream("next")
    next_response.feed(b"\x03\x00" * 800)
    next_response.finish()
    assert next_response.read(1_600).data == b"\x03\x00" * 800
