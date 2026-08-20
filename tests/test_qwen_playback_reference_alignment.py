from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import orion.qwen_live_audio_core as core
from orion.qwen_live_diagnostics import QwenLiveDiagnostics


def _diagnostics(tmp_path: Path) -> QwenLiveDiagnostics:
    recorder = QwenLiveDiagnostics(
        model="qwen3.5-omni-flash-realtime",
        region="singapore",
        vad_type="server_vad",
        silence_duration_ms=800,
        qwen_input_rate=core.QWEN_INPUT_RATE,
        qwen_output_rate=core.QWEN_OUTPUT_RATE,
        runtime_dir=tmp_path,
    )
    recorder.update_audio_metadata(
        input_device="Test microphone",
        output_device="Test speakers",
        input_native_rate=48_000,
        output_native_rate=24_000,
        duplex_rate=24_000,
        block_frames=960,
        block_duration_ms=core.CAPTURE_MS,
    )
    return recorder


def test_reference_cadence_writes_provider_deltas_fifo_without_silence(
    tmp_path: Path,
) -> None:
    playback = core._PlaybackFifo()
    diagnostics = _diagnostics(tmp_path)
    stop_event = threading.Event()
    failures: queue.Queue[core._WorkerFailure] = queue.Queue(maxsize=1)
    writes: list[bytes] = []
    write_threads: list[str] = []
    output_open_count = 0
    deltas = [bytes([index, 0]) * 7_680 for index in (1, 2, 3)]

    class FakeOutputStream:
        def __enter__(self) -> FakeOutputStream:
            nonlocal output_open_count
            output_open_count += 1
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def write(self, pcm: bytes) -> bool:
            writes.append(pcm)
            write_threads.append(threading.current_thread().name)
            return False

    sd = SimpleNamespace(
        WasapiSettings=lambda **kwargs: kwargs,
        RawOutputStream=lambda **kwargs: FakeOutputStream(),
    )
    audio = SimpleNamespace(native_rate=24_000, output_index=2)
    worker = threading.Thread(
        target=core.QwenLiveAudioService()._playback_worker,
        args=(
            sd,
            audio,
            stop_event,
            playback,
            diagnostics,
            failures,
        ),
        name="orion-qwen-playback",
    )

    diagnostics.record_provider_event(
        "response.created", t_ns=time.perf_counter_ns()
    )
    playback.mark_response_active(True)
    worker.start()
    time.sleep(0.05)
    assert writes == []

    for index, pcm in enumerate(deltas):
        before_bytes, after_bytes = playback.put(pcm)
        diagnostics.record_playback_enqueue(
            t_ns=time.perf_counter_ns(),
            before_bytes=before_bytes,
            after_bytes=after_bytes,
            sample_rate=24_000,
            added_bytes=len(pcm),
        )
        if index < len(deltas) - 1:
            time.sleep((0.05, 0.15)[index])

    deadline = time.monotonic() + 1.0
    while len(writes) < len(deltas) and time.monotonic() < deadline:
        time.sleep(0.005)
    diagnostics.record_provider_event(
        "response.audio.done", t_ns=time.perf_counter_ns()
    )
    playback.mark_response_active(False)

    stop_event.set()
    playback.stop()
    worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert failures.empty()
    assert writes == deltas
    assert all(len(write) == 15_360 for write in writes)
    assert write_threads == ["orion-qwen-playback"] * 3
    assert output_open_count == 1
    summary = diagnostics.summary()
    assert summary["zero_padded_write_count"] == 0
    assert summary["artificial_zero_padding_count"] == 0
    assert summary["total_inserted_silence_ms"] == 0
    starvation_count = summary["playback_starvation_period_count"]
    assert isinstance(starvation_count, int)
    assert starvation_count >= 1
