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


def test_short_deltas_are_concatenated_without_partial_zero_padding() -> None:
    playback = core._BoundedPlaybackBuffer(max_bytes=16)
    first = b"\x01\x00"
    second = b"\x02\x00"
    playback.mark_response_active(True)

    assert playback.append(first) == (0, 2, 0)
    waiting = playback.take_block(2)
    assert waiting.pcm == b"\x00" * 4
    assert waiting.response_audio_frames == 0
    assert waiting.buffer_after_bytes == 2

    assert playback.append(second) == (2, 4, 0)
    complete = playback.take_block(2)
    assert complete.pcm == first + second
    assert complete.response_audio_frames == 2
    assert complete.zero_frames == 0


def test_capture_queue_and_playback_buffer_are_bounded_drop_oldest() -> None:
    capture: queue.Queue[bytes] = queue.Queue(maxsize=2)
    assert core._put_drop_oldest(capture, b"aa") == (1, 0)
    assert core._put_drop_oldest(capture, b"bb") == (2, 0)
    assert core._put_drop_oldest(capture, b"cc") == (2, 2)
    assert capture.get_nowait() == b"bb"
    assert capture.get_nowait() == b"cc"

    playback = core._BoundedPlaybackBuffer(max_bytes=8)
    assert playback.append(b"00112233") == (0, 8, 0)
    assert playback.append(b"4455") == (8, 8, 4)
    playback.mark_response_active(False)
    assert playback.take_block(4).pcm == b"22334455"


def test_audio_capture_send_and_playback_continue_while_recv_is_blocked(
    tmp_path: Path,
) -> None:
    stop_event = threading.Event()
    recv_release = threading.Event()
    recv_entered = threading.Event()
    five_sends = threading.Event()
    sent_messages: list[str] = []

    class BlockingProvider:
        def _receive_json(self, _ws: object) -> dict[str, str]:
            recv_entered.set()
            recv_release.wait(timeout=2.0)
            raise FakeWebSocketTimeoutException()

    class FakeWebSocket:
        def send(self, message: str) -> None:
            sent_messages.append(message)
            if len(sent_messages) >= 5:
                five_sends.set()

        def abort(self) -> None:
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
            return b"\x01\x00" * frames, False

        def write(self, pcm: bytes) -> bool:
            assert len(pcm) == 3_840
            self.writes += 1
            if self.writes == 5:
                assert five_sends.wait(timeout=1.0)
                stop_event.set()
            return False

    stream = RealtimeStream()
    fake_sd = SimpleNamespace(
        WasapiSettings=lambda **kwargs: kwargs,
        RawStream=lambda **kwargs: stream,
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

    assert stream.reads == 5
    assert stream.writes == 5
    assert len(sent_messages) == 5
    assert all(
        json.loads(message)["type"] == "input_audio_buffer.append"
        for message in sent_messages
    )
    assert diagnostics.summary()["recv_call_count"] == 1
    assert not any(
        thread.name in {"orion-qwen-send", "orion-qwen-receive"}
        for thread in threading.enumerate()
    )


def test_receive_drains_multiple_deltas_before_microphone_cycle(
    tmp_path: Path,
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
    ] + [{"type": "response.audio.done"}]

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
            stop_event.set()
            return False

    stream = OneCycleStream()
    service = core.QwenLiveAudioService()
    diagnostics = _diagnostics(tmp_path)
    service._run_transport(
        sd=SimpleNamespace(
            WasapiSettings=lambda **kwargs: kwargs,
            RawStream=lambda **kwargs: stream,
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

    expected = b"".join(
        core._resample_pcm16_mono(delta, core.QWEN_OUTPUT_RATE, 48_000)
        for delta in source_deltas
    )
    assert stream.written == [expected]
    summary = diagnostics.summary()
    assert summary["audio_delta_count"] == 3
    assert summary["partial_zero_padded_write_count"] == 0
    assert summary["playback_buffer_overflow_count"] == 0


def test_receive_worker_error_propagates_to_service_error_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    receive_failed = threading.Event()

    class FakeWebSocket:
        def settimeout(self, _timeout: float) -> None:
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
            RawStream=lambda **kwargs: FakeRawStream(),
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


@pytest.mark.parametrize("failure_stage", ["capture", "playback"])
def test_audio_io_failure_propagates_and_stops_network_workers(
    failure_stage: str, tmp_path: Path
) -> None:
    recv_release = threading.Event()

    class BlockingProvider:
        def _receive_json(self, _ws: object) -> dict[str, str]:
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
    with pytest.raises(OSError, match=f"controlled {failure_stage} failure"):
        service._run_transport(
            sd=SimpleNamespace(
                WasapiSettings=lambda **kwargs: kwargs,
                RawStream=lambda **kwargs: FailingStream(),
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
        thread.name in {"orion-qwen-send", "orion-qwen-receive"}
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
