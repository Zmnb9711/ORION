from __future__ import annotations

import base64
import json
import queue
import sys
import threading
from array import array
from pathlib import Path
from types import SimpleNamespace

import pytest

import orion.qwen_live_audio_core as core
from orion.qwen_live_diagnostics import QwenLiveDiagnostics
from orion.windows_wasapi_backend import WasapiDirection, WasapiEndpoint


class FakeWebSocketTimeoutException(Exception):
    pass


def _resolved_audio() -> core._ResolvedAudio:
    return core._ResolvedAudio(
        WasapiEndpoint(
            device_id="test-input",
            name="Test microphone",
            direction=WasapiDirection.INPUT,
        ),
        WasapiEndpoint(
            device_id="test-output",
            name="Test speakers",
            direction=WasapiDirection.OUTPUT,
        ),
        1,
        2,
        48_000,
        48_000,
    )


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
        output_native_rate=48_000,
        duplex_rate=48_000,
        block_frames=1_920,
        block_duration_ms=core.CAPTURE_MS,
    )
    return recorder


def test_provider_deltas_use_unbounded_fifo_without_zero_padding() -> None:
    playback = core._PlaybackFifo()
    first = b"\x01\x00"
    second = b"\x02\x00"
    playback.mark_response_active(True)

    assert playback.put(first) == (0, 2)
    assert playback.put(second) == (2, 4)
    assert playback.get() == (first, 4, 2, True)
    assert playback.get() == (second, 2, 0, True)


def test_capture_queue_remains_bounded_but_playback_fifo_never_drops() -> None:
    capture: queue.Queue[bytes] = queue.Queue(maxsize=2)
    assert core._put_drop_oldest(capture, b"aa") == (1, 0)
    assert core._put_drop_oldest(capture, b"bb") == (2, 0)
    assert core._put_drop_oldest(capture, b"cc") == (2, 2)
    assert capture.get_nowait() == b"bb"
    assert capture.get_nowait() == b"cc"

    playback = core._PlaybackFifo()
    assert playback.put(b"00112233") == (0, 8)
    assert playback.put(b"4455") == (8, 12)
    assert playback.get()[0] == b"00112233"
    assert playback.get()[0] == b"4455"


def test_audio_capture_send_and_playback_continue_while_recv_is_blocked(
    tmp_path: Path,
) -> None:
    stop_event = threading.Event()
    recv_release = threading.Event()
    recv_entered = threading.Event()
    five_sends = threading.Event()
    sent_messages: list[str] = []
    abort_calls = 0

    class BlockingProvider:
        def _receive_json(self, _ws: object) -> dict[str, object]:
            recv_entered.set()
            recv_release.wait(timeout=2.0)
            raise FakeWebSocketTimeoutException()

    class FakeWebSocket:
        def send(self, message: str) -> None:
            sent_messages.append(message)
            if len(sent_messages) >= 5:
                five_sends.set()

        def abort(self) -> None:
            nonlocal abort_calls
            abort_calls += 1
            recv_release.set()

        def close(self) -> None:
            recv_release.set()

    class RealtimeStream:
        reads = 0
        writes = 0

        def __enter__(self) -> RealtimeStream:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, frames: int) -> tuple[bytes, bool]:
            assert recv_entered.wait(timeout=1.0)
            self.reads += 1
            if self.reads == 6:
                assert five_sends.wait(timeout=1.0)
                stop_event.set()
            return b"\x01\x00" * frames, False

        def write(self, pcm: bytes) -> bool:
            self.writes += 1
            raise AssertionError(f"Artificial playback write: {len(pcm)} bytes")

    stream = RealtimeStream()
    fake_sd = SimpleNamespace(
        WasapiSettings=lambda **kwargs: kwargs,
        RawInputStream=lambda **kwargs: stream,
        RawOutputStream=lambda **kwargs: stream,
    )
    service = core.QwenLiveAudioService()
    diagnostics = _diagnostics(tmp_path)
    service._run_transport(
        sd=fake_sd,
        websocket=SimpleNamespace(
            WebSocketTimeoutException=FakeWebSocketTimeoutException
        ),
        ws=FakeWebSocket(),
        provider=BlockingProvider(),  # type: ignore[arg-type]
        audio=_resolved_audio(),
        frames=1_920,
        stop_event=stop_event,
        diagnostics=diagnostics,
    )

    assert stream.reads == 6
    assert stream.writes == 0
    assert len(sent_messages) >= 5
    assert abort_calls == 0
    assert all(
        json.loads(message)["type"] == "input_audio_buffer.append"
        for message in sent_messages
    )
    assert diagnostics.summary()["recv_call_count"] == 1
    lifecycle = diagnostics.websocket_forensics()
    send_thread_ids = lifecycle["send_thread_ids"]
    recv_thread_ids = lifecycle["recv_thread_ids"]
    close_thread_ids = lifecycle["close_thread_ids"]
    recent_events = lifecycle["recent_events"]
    assert isinstance(send_thread_ids, list)
    assert isinstance(recv_thread_ids, list)
    assert isinstance(close_thread_ids, list)
    assert isinstance(recent_events, list)
    assert len(send_thread_ids) == 1
    assert len(recv_thread_ids) == 1
    assert len(close_thread_ids) == 1
    lifecycle_events = [event["event"] for event in recent_events]
    assert "AUDIO_SEND_START" in lifecycle_events
    assert "RECV_EVENT_START" in lifecycle_events
    assert "NORMAL_CLOSE_START" in lifecycle_events
    assert "NORMAL_CLOSE_END" in lifecycle_events
    assert "EMERGENCY_ABORT_START" not in lifecycle_events
    assert lifecycle["normal_close_called"] is True
    assert lifecycle["emergency_abort_called"] is False
    assert "PING_SENT" not in lifecycle_events
    assert not any(
        thread.name
        in {"orion-qwen-send", "orion-qwen-receive", "orion-qwen-heartbeat"}
        for thread in threading.enumerate()
    )


@pytest.mark.parametrize("completion_event", ["response.audio.done", "response.done"])
def test_receive_completion_does_not_discard_queued_deltas(
    completion_event: str, tmp_path: Path,
) -> None:
    stop_event = threading.Event()
    recv_release = threading.Event()
    deltas_drained = threading.Event()
    source_deltas = [
        array("h", range(offset, offset + 320)).tobytes()
        for offset in (0, 320, 640)
    ]
    events = [
        {
            "type": "response.audio.delta",
            "delta": base64.b64encode(delta).decode("ascii"),
        }
        for delta in source_deltas
    ] + [{"type": completion_event}]

    class BurstProvider:
        def _receive_json(self, _ws: object) -> dict[str, str]:
            if events:
                event = events.pop(0)
                if not events:
                    deltas_drained.set()
                return event
            recv_release.wait(timeout=2.0)
            raise FakeWebSocketTimeoutException()

    class FakeWebSocket:
        def send(self, _message: str) -> None:
            return None

        def abort(self) -> None:
            recv_release.set()

        def close(self) -> None:
            recv_release.set()

    class OneCycleStream:
        written: list[bytes] = []

        def __enter__(self) -> OneCycleStream:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, frames: int) -> tuple[bytes, bool]:
            assert deltas_drained.wait(timeout=1.0)
            return b"\x00\x00" * frames, False

        def write(self, pcm: bytes) -> bool:
            self.written.append(pcm)
            if len(self.written) == 3:
                stop_event.set()
            return False

    stream = OneCycleStream()
    service = core.QwenLiveAudioService()
    diagnostics = _diagnostics(tmp_path)
    service._run_transport(
        sd=SimpleNamespace(
            WasapiSettings=lambda **kwargs: kwargs,
            RawInputStream=lambda **kwargs: stream,
            RawOutputStream=lambda **kwargs: stream,
        ),
        websocket=SimpleNamespace(
            WebSocketTimeoutException=FakeWebSocketTimeoutException
        ),
        ws=FakeWebSocket(),
        provider=BurstProvider(),  # type: ignore[arg-type]
        audio=_resolved_audio(),
        frames=1_920,
        stop_event=stop_event,
        diagnostics=diagnostics,
    )

    assert stream.written == [
        core._resample_pcm16_mono(delta, core.QWEN_OUTPUT_RATE, 48_000)
        for delta in source_deltas
    ]
    summary = diagnostics.summary()
    assert summary["audio_delta_count"] == 3
    assert summary["partial_zero_padded_write_count"] == 0
    assert summary["playback_buffer_overflow_count"] == 0


def test_emergency_abort_is_only_used_after_normal_close_cannot_unblock_recv(
    tmp_path: Path,
) -> None:
    stop_event = threading.Event()
    recv_release = threading.Event()
    recv_entered = threading.Event()
    operations: list[str] = []

    class BlockingProvider:
        def _receive_json(self, _ws: object) -> dict[str, str]:
            recv_entered.set()
            recv_release.wait(timeout=3.0)
            raise FakeWebSocketTimeoutException()

    class StuckWebSocket:
        def send(self, _message: str) -> None:
            return None

        def close(self) -> None:
            operations.append("close")

        def abort(self) -> None:
            operations.append("abort")
            recv_release.set()

    class StopStream:
        def __enter__(self) -> StopStream:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, frames: int) -> tuple[bytes, bool]:
            assert recv_entered.wait(timeout=1.0)
            stop_event.set()
            return b"\x00\x00" * frames, False

        def write(self, _pcm: bytes) -> bool:
            return False

    diagnostics = _diagnostics(tmp_path)
    core.QwenLiveAudioService()._run_transport(
        sd=SimpleNamespace(
            WasapiSettings=lambda **kwargs: kwargs,
            RawInputStream=lambda **kwargs: StopStream(),
            RawOutputStream=lambda **kwargs: StopStream(),
        ),
        websocket=SimpleNamespace(
            WebSocketTimeoutException=FakeWebSocketTimeoutException
        ),
        ws=StuckWebSocket(),
        provider=BlockingProvider(),  # type: ignore[arg-type]
        audio=_resolved_audio(),
        frames=1_920,
        stop_event=stop_event,
        diagnostics=diagnostics,
    )

    lifecycle = diagnostics.websocket_forensics()
    recent_events = lifecycle["recent_events"]
    assert isinstance(recent_events, list)
    events = [event["event"] for event in recent_events]
    assert operations == ["close", "abort"]
    assert events.index("NORMAL_CLOSE_END") < events.index(
        "EMERGENCY_ABORT_START"
    )
    assert lifecycle["normal_close_called"] is True
    assert lifecycle["emergency_abort_called"] is True


def test_receive_worker_error_propagates_to_service_error_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    receive_failed = threading.Event()

    class FakeWebSocket:
        def settimeout(self, _timeout: float | None) -> None:
            return None

        def send(self, _message: str) -> None:
            return None

        def abort(self) -> None:
            return None

        def close(self) -> None:
            return None

    class FailingProvider:
        def __init__(self, _config: object) -> None:
            self.receive_count = 0

        def _connect(self) -> FakeWebSocket:
            return FakeWebSocket()

        def _receive_json(self, _ws: FakeWebSocket) -> dict[str, str]:
            self.receive_count += 1
            if self.receive_count == 1:
                return {"type": "session.updated"}
            receive_failed.set()
            raise OSError("controlled receive failure")

    class FakeRawStream:
        def __enter__(self) -> FakeRawStream:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, frames: int) -> tuple[bytes, bool]:
            receive_failed.wait(timeout=1.0)
            return b"\x00\x00" * frames, False

        def write(self, _pcm: bytes) -> bool:
            return False

    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(
            WasapiSettings=lambda **kwargs: kwargs,
            RawInputStream=lambda **kwargs: FakeRawStream(),
            RawOutputStream=lambda **kwargs: FakeRawStream(),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "websocket",
        SimpleNamespace(
            WebSocketTimeoutException=FakeWebSocketTimeoutException
        ),
    )
    monkeypatch.setattr(core, "QwenRealtimeProvider", FailingProvider)
    monkeypatch.setenv("ORION_RUNTIME_DIR", str(tmp_path))
    service = core.QwenLiveAudioService()
    monkeypatch.setattr(service, "_resolve_audio", lambda _sd: _resolved_audio())

    service._run(
        core.QwenLiveStartRequest(
            api_key="not-recorded",
            workspace_id="test-workspace",
        ),
        threading.Event(),
    )

    status = service.status()
    assert status.state is core.QwenLiveState.ERROR
    assert "websocket receive" in status.message
    assert "controlled receive failure" in status.message
    diagnostic_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "qwen-live").iterdir()
    )
    assert "not-recorded" not in diagnostic_text
    jsonl_path = next((tmp_path / "qwen-live").glob("*.jsonl"))
    records = [
        json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    lifecycle = next(
        record for record in records if record["kind"] == "websocket_forensics"
    )
    exception = lifecycle["exception"]
    assert exception["exception_type"] == "OSError"
    assert exception["exception_message"] == "controlled receive failure"
    assert "OSError: controlled receive failure" in exception["full_traceback"]
    assert lifecycle["disconnect_origin"] == "recv_exception"
    assert lifecycle["close_frame_received"] is False
    events = [event["event"] for event in lifecycle["recent_events"]]
    assert events.index("WEBSOCKET_EXCEPTION") < events.index(
        "WORKER_FAILURE_REPORTED"
    )
    assert events.index("WORKER_FAILURE_REPORTED") < events.index("STOP_EVENT_SET")
    assert events.index("STOP_EVENT_SET") < events.index(
        "AUDIO_COORDINATOR_CLEANUP_START"
    )
    assert events.index("AUDIO_COORDINATOR_CLEANUP_START") < events.index(
        "NORMAL_CLOSE_START"
    )
    assert "EMERGENCY_ABORT_START" not in events


def test_control_frame_observer_records_close_ping_and_pong_without_consuming(
    tmp_path: Path,
) -> None:
    diagnostics = _diagnostics(tmp_path)

    class FakeABNF:
        OPCODE_CLOSE = 8
        OPCODE_PING = 9
        OPCODE_PONG = 10

    frames = [
        SimpleNamespace(opcode=FakeABNF.OPCODE_PING, data=b"provider-ping"),
        SimpleNamespace(opcode=FakeABNF.OPCODE_PONG, data=b"provider-pong"),
        SimpleNamespace(
            opcode=FakeABNF.OPCODE_CLOSE,
            data=(1001).to_bytes(2, "big") + b"provider shutdown",
        ),
    ]

    class FakeWebSocket:
        ping_calls = 0
        pong_calls = 0

        def recv_frame(self) -> SimpleNamespace:
            return frames.pop(0)

        def ping(self, _payload: bytes = b"") -> None:
            self.ping_calls += 1

        def pong(self, _payload: bytes = b"") -> None:
            self.pong_calls += 1

    ws = FakeWebSocket()
    core._install_websocket_frame_telemetry(
        ws,
        SimpleNamespace(ABNF=FakeABNF),
        diagnostics,
    )

    assert ws.recv_frame().opcode == FakeABNF.OPCODE_PING
    assert ws.recv_frame().opcode == FakeABNF.OPCODE_PONG
    assert ws.recv_frame().opcode == FakeABNF.OPCODE_CLOSE
    ws.ping(b"client-ping")
    ws.pong(b"client-pong")

    lifecycle = diagnostics.websocket_forensics()
    assert lifecycle["close_frame_received"] is True
    assert lifecycle["close_code"] == 1001
    assert lifecycle["close_reason"] == "provider shutdown"
    assert lifecycle["clean_close"] is True
    assert ws.ping_calls == 1
    assert ws.pong_calls == 1
    recent_events = lifecycle["recent_events"]
    assert isinstance(recent_events, list)
    events = [event["event"] for event in recent_events]
    assert events == [
        "PING_RECEIVED",
        "PONG_RECEIVED",
        "WEBSOCKET_CLOSE_RECEIVED",
        "PING_SENT",
        "PONG_SENT",
    ]


@pytest.mark.parametrize("failure_stage", ["capture", "playback"])
def test_audio_io_failure_propagates_and_stops_network_workers(
    failure_stage: str, tmp_path: Path
) -> None:
    recv_release = threading.Event()

    class BlockingProvider:
        def __init__(self) -> None:
            self.receive_count = 0

        def _receive_json(self, _ws: object) -> dict[str, object]:
            if failure_stage == "playback":
                self.receive_count += 1
                if self.receive_count == 1:
                    return {"type": "response.created", "response": {"id": "r1"}}
                if self.receive_count == 2:
                    return {
                        "type": "response.audio.delta",
                        "delta": base64.b64encode(b"\x01\x00" * 320).decode("ascii"),
                    }
            recv_release.wait(timeout=2.0)
            raise FakeWebSocketTimeoutException()

    class FakeWebSocket:
        def send(self, _message: str) -> None:
            return None

        def abort(self) -> None:
            recv_release.set()

        def close(self) -> None:
            recv_release.set()

    class FailingStream:
        def __enter__(self) -> FailingStream:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, frames: int) -> tuple[bytes, bool]:
            if failure_stage == "capture":
                raise OSError("controlled capture failure")
            return b"\x00\x00" * frames, False

        def write(self, _pcm: bytes) -> bool:
            raise OSError("controlled playback failure")

    service = core.QwenLiveAudioService()
    with pytest.raises(Exception, match=f"controlled {failure_stage} failure"):
        service._run_transport(
            sd=SimpleNamespace(
                WasapiSettings=lambda **kwargs: kwargs,
                RawInputStream=lambda **kwargs: FailingStream(),
                RawOutputStream=lambda **kwargs: FailingStream(),
            ),
            websocket=SimpleNamespace(
                WebSocketTimeoutException=FakeWebSocketTimeoutException
            ),
            ws=FakeWebSocket(),
            provider=BlockingProvider(),  # type: ignore[arg-type]
            audio=_resolved_audio(),
            frames=1_920,
            stop_event=threading.Event(),
            diagnostics=_diagnostics(tmp_path),
        )

    assert not any(
        thread.name
        in {"orion-qwen-send", "orion-qwen-receive", "orion-qwen-playback"}
        for thread in threading.enumerate()
    )


def test_queue_overflow_diagnostics_are_summarized(tmp_path: Path) -> None:
    diagnostics = _diagnostics(tmp_path)
    diagnostics.record_queue_overflow(
        channel="capture_queue",
        dropped_bytes=1_280,
        sample_rate=16_000,
        depth=25,
        capacity=25,
    )
    diagnostics.record_queue_overflow(
        channel="playback_buffer",
        dropped_bytes=1_920,
        sample_rate=48_000,
        depth=192_000,
        capacity=192_000,
    )

    summary = diagnostics.summary()
    assert summary["capture_queue_overflow_count"] == 1
    assert summary["capture_queue_dropped_audio_ms"] == 40.0
    assert summary["playback_buffer_overflow_count"] == 1
    assert summary["playback_buffer_dropped_audio_ms"] == 20.0
