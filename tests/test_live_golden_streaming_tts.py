from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import orion.live_golden_conversation as live_module
import pytest

from orion.communication_contracts import CommunicationDomain, CommunicationPriority
from orion.live_golden_conversation import (
    LIVE_GOLDEN_CORPUS,
    STREAM_MAX_BUFFER_MS,
    STREAM_PREBUFFER_MS,
    LiveGoldenRuntimeContext,
)
from orion.radio_streaming import StreamingPcmEvent, StreamingPcmState
from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder


class _MeasuredProfileStreamingClient:
    def __init__(self, endpoint: "_StreamingEndpoint") -> None:
        self.endpoint = endpoint
        self.tx_started_before_eos = False
        self.eos_emitted = False
        self.first = bytes((index % 251 for index in range(65_761)))
        self.second = bytes((index % 239 for index in range(126_239)))

    async def stream(
        self,
        _text: str,
        _api_key: str,
        *,
        response_id: str,
        cancelled,
    ):  # noqa: ANN001, ANN202
        assert not cancelled()
        yield _event(response_id, 0, self.first)
        assert not self.endpoint.started.is_set(), "685 ms must not pass 1000 ms prebuffer"
        yield _event(response_id, 1, self.second)
        assert await asyncio.to_thread(self.endpoint.started.wait, 1.0)
        self.tx_started_before_eos = True
        self.eos_emitted = True
        yield StreamingPcmEvent(
            response_id=response_id,
            pcm=b"",
            sample_rate_hz=48_000,
            channels=1,
            sample_width_bytes=2,
            chunk_index=2,
            end_of_stream=True,
        )


class _StreamingEndpoint:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.lifecycle_count = 0
        self.output = bytearray()
        self.started_state: StreamingPcmState | None = None
        self.started_buffer_bytes = 0

    def transmit_streaming_audio(
        self,
        _response_id: str,
        source,
        _timeout_s: float,
        **_fields,
    ) -> dict[str, float | int]:  # noqa: ANN001, ANN003
        self.lifecycle_count += 1
        snapshot = source.snapshot()
        self.started_state = snapshot.state
        self.started_buffer_bytes = snapshot.buffered_bytes
        self.started.set()
        while True:
            read = source.read(8_820, timeout_s=0.2)
            self.output.extend(read.data)
            if read.state is StreamingPcmState.END_OF_STREAM and not read.data:
                break
            if read.state in {StreamingPcmState.FAILED, StreamingPcmState.CANCELLED}:
                raise RuntimeError(read.error or read.state.value)
        frames = max(1, (len(self.output) + 1_279) // 1_280)
        return {
            "queue_to_first_tx_ms": 3.0,
            "queue_to_complete_ms": frames * 40.0,
            "frame_count": frames,
            "duration_ms": frames * 40.0,
            "underrun_count": 0,
            "underrun_silence_inserted_ms": 0.0,
            "max_buffered_bytes": source.snapshot().max_buffered_bytes,
        }


class _TerminalClient:
    def __init__(self, endpoint: _StreamingEndpoint, terminal: str) -> None:
        self.endpoint = endpoint
        self.terminal = terminal

    async def stream(
        self,
        _text: str,
        _api_key: str,
        *,
        response_id: str,
        cancelled,
    ):  # noqa: ANN001, ANN202
        if self.terminal == "before_failure":
            yield _terminal_event(response_id, error="provider unavailable")
            return
        yield _event(response_id, 0, b"\x01\x00" * 48_000)
        assert await asyncio.to_thread(self.endpoint.started.wait, 1.0)
        if self.terminal == "after_failure":
            yield _terminal_event(response_id, error="provider interrupted")
        else:
            assert self.terminal == "cancel"
            yield _terminal_event(response_id, cancelled=True)


def _event(response_id: str, index: int, pcm: bytes) -> StreamingPcmEvent:
    return StreamingPcmEvent(
        response_id=response_id,
        pcm=pcm,
        sample_rate_hz=48_000,
        channels=1,
        sample_width_bytes=2,
        chunk_index=index,
    )


def _terminal_event(
    response_id: str,
    *,
    error: str | None = None,
    cancelled: bool = False,
) -> StreamingPcmEvent:
    return StreamingPcmEvent(
        response_id=response_id,
        pcm=b"",
        sample_rate_hz=48_000,
        channels=1,
        sample_width_bytes=2,
        chunk_index=1,
        error=error,
        cancelled=cancelled,
    )


def _run_terminal_case(
    tmp_path: Path,
    monkeypatch,
    terminal: str,
) -> _StreamingEndpoint:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(provider="yandex", transport="srs")
    monkeypatch.setattr(live_module, "realtime_test_evidence", recorder)
    endpoint = _StreamingEndpoint()
    client = _TerminalClient(endpoint, terminal)
    runner = live_module.LiveGoldenCaseRunner(
        streaming_speechkit_factory=lambda: client
    )
    context = LiveGoldenRuntimeContext(
        api_key="memory-only-secret",
        folder_id="folder",
        endpoint=endpoint,
        main_session_id="session",
        tts_output_mode=live_module.SpeechKitTtsOutputMode.STREAMING_V3,
    )
    with pytest.raises(
        (
            live_module._StreamingBeforeTxFailure
            if terminal == "before_failure"
            else live_module.LiveGoldenCaseFailure
        )
    ):
        asyncio.run(
            runner._stream_to_radio(
                context=context,
                run_id=f"run-{terminal}",
                case=LIVE_GOLDEN_CORPUS[0],
                response_id=f"response-{terminal}",
                final_text="Добрый день! Viper 2-1, взлёт разрешён.",
                source_domain=CommunicationDomain.ATC,
                priority=CommunicationPriority.IMPORTANT,
                cancelled=lambda: terminal == "cancel" and endpoint.started.is_set(),
                capture_audio=False,
                semantic_ready_at=time.monotonic(),
            )
        )
    recorder.stop_and_export()
    return endpoint


def test_measured_685ms_then_975ms_profile_starts_before_eos_without_underrun(
    tmp_path: Path,
    monkeypatch,
) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(provider="yandex", transport="srs")
    monkeypatch.setattr(live_module, "realtime_test_evidence", recorder)
    endpoint = _StreamingEndpoint()
    client = _MeasuredProfileStreamingClient(endpoint)
    runner = live_module.LiveGoldenCaseRunner(
        streaming_speechkit_factory=lambda: client
    )
    context = LiveGoldenRuntimeContext(
        api_key="memory-only-secret",
        folder_id="folder",
        endpoint=endpoint,
        main_session_id="session",
        tts_output_mode=live_module.SpeechKitTtsOutputMode.STREAMING_V3,
    )
    semantic_ready_at = time.monotonic()
    outcome = asyncio.run(
        runner._stream_to_radio(
            context=context,
            run_id="stream-run",
            case=LIVE_GOLDEN_CORPUS[0],
            response_id="stream-response",
            final_text="Добрый день! Viper 2-1, взлёт разрешён.",
            source_domain=CommunicationDomain.ATC,
            priority=CommunicationPriority.IMPORTANT,
            cancelled=lambda: False,
            capture_audio=True,
            semantic_ready_at=semantic_ready_at,
        )
    )

    assert STREAM_PREBUFFER_MS == 1_000
    assert STREAM_MAX_BUFFER_MS == 2_000
    assert endpoint.started_state is StreamingPcmState.OPEN
    assert endpoint.started_buffer_bytes >= 44_100 * 2
    assert client.tx_started_before_eos
    assert client.eos_emitted
    assert endpoint.lifecycle_count == 1
    assert bytes(endpoint.output) == outcome.snapshot.captured_pcm
    assert outcome.snapshot.buffered_bytes == 0
    assert outcome.snapshot.max_buffered_bytes <= 44_100 * 2 * 2
    assert outcome.tx["underrun_count"] == 0
    recorder.stop_and_export()


def test_stream_failure_before_tx_is_explicitly_safe_for_rest_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:  # noqa: ANN001
    endpoint = _run_terminal_case(tmp_path, monkeypatch, "before_failure")
    assert endpoint.lifecycle_count == 0


def test_stream_failure_after_tx_aborts_without_starting_a_second_lifecycle(
    tmp_path: Path,
    monkeypatch,
) -> None:  # noqa: ANN001
    endpoint = _run_terminal_case(tmp_path, monkeypatch, "after_failure")
    assert endpoint.lifecycle_count == 1


def test_stream_cancellation_discards_unsent_pcm_and_stops_one_lifecycle(
    tmp_path: Path,
    monkeypatch,
) -> None:  # noqa: ANN001
    endpoint = _run_terminal_case(tmp_path, monkeypatch, "cancel")
    assert endpoint.lifecycle_count == 1
