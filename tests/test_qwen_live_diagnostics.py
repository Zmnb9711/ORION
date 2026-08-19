from __future__ import annotations

import base64
import json
import sys
import threading
from array import array
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import orion.qwen_live_audio_core as core
from orion.app import app
from orion.qwen_live_diagnostics import QwenLiveDiagnostics
from orion.windows_wasapi_backend import WasapiDirection, WasapiEndpoint


START_NS = 1_000_000_000


def _recorder(tmp_path: Path, *, max_events: int = 20_000) -> QwenLiveDiagnostics:
    recorder = QwenLiveDiagnostics(
        model="qwen3.5-omni-flash-realtime",
        region="singapore",
        vad_type="server_vad",
        silence_duration_ms=800,
        qwen_input_rate=16_000,
        qwen_output_rate=24_000,
        runtime_dir=tmp_path,
        max_events=max_events,
        start_ns=START_NS,
        start_utc=datetime(2026, 8, 19, tzinfo=UTC),
        session_id="test-session",
    )
    recorder.update_audio_metadata(
        input_device="Test microphone",
        output_device="Test speakers",
        input_native_rate=48_000,
        output_native_rate=44_100,
        duplex_rate=48_000,
        block_frames=1_920,
        block_duration_ms=40,
    )
    return recorder


def test_capture_and_send_realtime_ratios_use_represented_audio_time(
    tmp_path: Path,
) -> None:
    recorder = _recorder(tmp_path)

    recorder.record_capture(
        read_start_ns=START_NS,
        read_end_ns=START_NS + 250_000_000,
        frames_requested=1_920,
        frames_returned=1_920,
        overflow=True,
    )
    recorder.record_send(
        send_start_ns=START_NS,
        send_end_ns=START_NS + 250_000_000,
        pcm_frames=640,
    )

    summary = recorder.summary(end_ns=START_NS + 250_000_000)
    assert summary["captured_audio_ms"] == pytest.approx(40)
    assert summary["sent_audio_ms"] == pytest.approx(40)
    assert summary["capture_realtime_ratio"] == pytest.approx(0.16)
    assert summary["send_realtime_ratio"] == pytest.approx(0.16)
    assert summary["input_overflow_count"] == 1


def test_recv_backlog_and_zero_padding_telemetry(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path)
    recorder.record_recv(
        recv_start_ns=START_NS,
        recv_end_ns=START_NS + 250_000_000,
        timeout=True,
    )
    recorder.record_provider_event(
        "response.created", t_ns=START_NS + 260_000_000
    )
    recorder.record_audio_delta(
        receive_ns=START_NS + 270_000_000,
        encoded_chars=2_560,
        decoded_bytes=960,
        source_rate=24_000,
        resample_start_ns=START_NS + 271_000_000,
        resample_end_ns=START_NS + 272_000_000,
        resampled_bytes=1_920,
        target_rate=48_000,
    )
    recorder.record_playback_enqueue(
        t_ns=START_NS + 272_000_000,
        before_bytes=0,
        after_bytes=1_920,
        sample_rate=48_000,
    )
    recorder.record_write(
        write_start_ns=START_NS + 273_000_000,
        write_end_ns=START_NS + 313_000_000,
        buffer_before_bytes=1_920,
        buffer_after_bytes=0,
        response_audio_frames=960,
        zero_frames=960,
        frames_written=1_920,
        sample_rate=48_000,
        underflow=True,
        response_active=True,
    )

    summary = recorder.summary(end_ns=START_NS + 313_000_000)
    assert summary["recv_call_count"] == 1
    assert summary["recv_timeout_count"] == 1
    assert summary["recv_average_wait_ms"] == pytest.approx(250)
    assert summary["recv_max_wait_ms"] == pytest.approx(250)
    assert summary["maximum_playback_backlog_ms"] == pytest.approx(20)
    assert summary["minimum_playback_backlog_active_ms"] == pytest.approx(0)
    assert summary["insufficient_audio_cycle_count"] == 1
    assert summary["zero_padded_write_count"] == 1
    assert summary["partial_zero_padded_write_count"] == 1
    assert summary["fully_silent_active_write_count"] == 0
    assert summary["total_inserted_silence_ms"] == pytest.approx(20)
    assert summary["output_underflow_count"] == 1
    assert summary["first_audio_delta_ns"] == START_NS + 270_000_000
    assert summary["first_non_silent_write_ns"] == START_NS + 273_000_000
    assert summary["speech_stopped_to_first_audio_delta_ms"] is None
    assert summary["first_audio_delta_to_first_non_silent_write_ms"] == pytest.approx(
        3
    )
    assert summary["playback_buffer_zero_while_active_count"] == 1
    assert summary["PLAYBACK_DUTY_CYCLE"] == pytest.approx(20 / 53)


def test_delta_cadence_write_gaps_starvation_and_duty_cycle(
    tmp_path: Path,
) -> None:
    recorder = _recorder(tmp_path)
    recorder.record_provider_event(
        "response.created", t_ns=START_NS + 90_000_000
    )

    for receive_offset_ms in (100, 350, 600):
        receive_ns = START_NS + receive_offset_ms * 1_000_000
        recorder.record_recv(
            recv_start_ns=receive_ns - 2_000_000,
            recv_end_ns=receive_ns,
            timeout=False,
            event_type="response.audio.delta",
        )
        recorder.record_audio_delta(
            receive_ns=receive_ns,
            encoded_chars=2_560,
            decoded_bytes=1_920,
            source_rate=24_000,
            resample_start_ns=receive_ns + 100_000,
            resample_end_ns=receive_ns + 200_000,
            resampled_bytes=3_840,
            target_rate=48_000,
        )

    recorder.record_write(
        write_start_ns=START_NS + 110_000_000,
        write_end_ns=START_NS + 150_000_000,
        buffer_before_bytes=3_840,
        buffer_after_bytes=0,
        response_audio_frames=1_920,
        zero_frames=0,
        frames_written=1_920,
        sample_rate=48_000,
        underflow=False,
        response_active=True,
    )
    recorder.record_write(
        write_start_ns=START_NS + 400_000_000,
        write_end_ns=START_NS + 440_000_000,
        buffer_before_bytes=0,
        buffer_after_bytes=0,
        response_audio_frames=0,
        zero_frames=1_920,
        frames_written=1_920,
        sample_rate=48_000,
        underflow=False,
        response_active=True,
        preceding_recv_timeout=True,
        preceding_recv_wait_ms=250,
    )
    recorder.record_write(
        write_start_ns=START_NS + 650_000_000,
        write_end_ns=START_NS + 690_000_000,
        buffer_before_bytes=3_840,
        buffer_after_bytes=0,
        response_audio_frames=1_920,
        zero_frames=0,
        frames_written=1_920,
        sample_rate=48_000,
        underflow=False,
        response_active=True,
    )
    recorder.record_write(
        write_start_ns=START_NS + 940_000_000,
        write_end_ns=START_NS + 980_000_000,
        buffer_before_bytes=3_840,
        buffer_after_bytes=0,
        response_audio_frames=1_920,
        zero_frames=0,
        frames_written=1_920,
        sample_rate=48_000,
        underflow=False,
        response_active=True,
    )
    recorder.record_provider_event(
        "response.done", t_ns=START_NS + 990_000_000
    )
    recorder.record_write(
        write_start_ns=START_NS + 1_000_000_000,
        write_end_ns=START_NS + 1_040_000_000,
        buffer_before_bytes=0,
        buffer_after_bytes=0,
        response_audio_frames=0,
        zero_frames=1_920,
        frames_written=1_920,
        sample_rate=48_000,
        underflow=False,
        response_active=False,
    )

    summary = recorder.summary(end_ns=START_NS + 1_040_000_000)
    delta_gaps = summary["audio_delta_gap_ms"]
    write_gaps = summary["NON_SILENT_WRITE_GAP_MS"]
    assert isinstance(delta_gaps, dict)
    assert isinstance(write_gaps, dict)
    assert delta_gaps["mean_ms"] == pytest.approx(250)
    assert delta_gaps["median_ms"] == pytest.approx(250)
    assert delta_gaps["p95_ms"] == pytest.approx(250)
    assert delta_gaps["max_ms"] == pytest.approx(250)
    assert write_gaps["mean_ms"] == pytest.approx(415)
    assert write_gaps["median_ms"] == pytest.approx(415)
    assert write_gaps["p95_ms"] == pytest.approx(540)
    assert write_gaps["max_ms"] == pytest.approx(540)
    assert summary["maximum_consecutive_audio_delta_events"] == 3
    assert summary["near_zero_wait_audio_delta_count"] == 3
    assert summary["playback_starvation_period_count"] == 1
    assert summary["playback_starvation_total_ms"] == pytest.approx(250)
    assert summary["playback_starvation_max_ms"] == pytest.approx(250)
    assert summary["playback_buffer_zero_while_active_count"] == 4
    assert summary["zero_padded_after_recv_timeout_count"] == 1
    assert summary["starved_after_recv_timeout_count"] == 1
    assert summary["PLAYBACK_DUTY_CYCLE"] == pytest.approx(120 / 910)
    assert isinstance(summary["latency_timeline"], dict)
    assert isinstance(summary["playback_timeline"], dict)


def test_diagnostics_are_bounded_and_exclude_sensitive_fields(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path, max_events=3)
    for index in range(5):
        recorder.record(
            "safety_probe",
            index=index,
            api_key="super-secret-key",
            authorization="Bearer super-secret-token",
            raw=b"raw microphone bytes",
            audio="base64-response-audio",
            base64="base64-microphone-audio",
            payload="sensitive-payload",
        )

    assert recorder.event_count == 3
    assert recorder.dropped_event_count == 4
    paths = recorder.finish(end_ns=START_NS + 1_000_000)
    assert paths is not None
    jsonl_path, summary_path = paths
    diagnostic_text = jsonl_path.read_text(encoding="utf-8")
    summary_text = summary_path.read_text(encoding="utf-8")
    assert "LATENCY TIMELINE:" in summary_text
    assert "PLAYBACK TIMELINE:" in summary_text
    assert "super-secret" not in diagnostic_text
    assert "raw microphone bytes" not in diagnostic_text
    assert "base64-response-audio" not in diagnostic_text
    assert "base64-microphone-audio" not in diagnostic_text
    assert "sensitive-payload" not in diagnostic_text
    assert len(jsonl_path.read_text(encoding="utf-8").splitlines()) == 5


def test_instrumented_transport_preserves_pcm_and_sync_operation_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    operations: list[str] = []
    sent_messages: list[str] = []
    written_chunks: list[bytes] = []
    stop_event = threading.Event()
    microphone_pcm = array("h", range(1_920)).tobytes()
    response_pcm = array("h", range(240)).tobytes()

    class FakeWebSocket:
        def settimeout(self, timeout: float) -> None:
            operations.append(f"timeout:{timeout}")

        def send(self, message: str) -> None:
            operations.append("send")
            sent_messages.append(message)

        def close(self) -> None:
            operations.append("close")

    class FakeProvider:
        def __init__(self, _config: object) -> None:
            self.receive_count = 0

        def _connect(self) -> FakeWebSocket:
            operations.append("connect")
            return FakeWebSocket()

        def _receive_json(self, _ws: FakeWebSocket) -> dict[str, str]:
            self.receive_count += 1
            operations.append("recv")
            if self.receive_count == 1:
                return {"type": "session.updated"}
            return {
                "type": "response.audio.delta",
                "delta": base64.b64encode(response_pcm).decode("ascii"),
            }

    class FakeRawStream:
        def __enter__(self) -> FakeRawStream:
            operations.append("stream_enter")
            return self

        def __exit__(self, *_args: object) -> None:
            operations.append("stream_exit")

        def read(self, frames: int) -> tuple[bytes, bool]:
            operations.append("read")
            assert frames == 1_920
            stop_event.set()
            return microphone_pcm, False

        def write(self, chunk: bytes) -> bool:
            operations.append("write")
            written_chunks.append(chunk)
            return False

    microphone = WasapiEndpoint(
        device_id="test-input",
        name="Test microphone",
        direction=WasapiDirection.INPUT,
    )
    speakers = WasapiEndpoint(
        device_id="test-output",
        name="Test speakers",
        direction=WasapiDirection.OUTPUT,
    )
    resolved = core._ResolvedAudio(
        microphone,
        speakers,
        1,
        2,
        48_000,
        48_000,
        48_000,
    )
    fake_sounddevice = SimpleNamespace(
        WasapiSettings=lambda **kwargs: kwargs,
        RawStream=lambda **kwargs: FakeRawStream(),
    )
    fake_websocket = SimpleNamespace(
        WebSocketTimeoutException=type(
            "FakeWebSocketTimeoutException", (Exception,), {}
        )
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sounddevice)
    monkeypatch.setitem(sys.modules, "websocket", fake_websocket)
    monkeypatch.setattr(core, "QwenRealtimeProvider", FakeProvider)
    monkeypatch.setenv("ORION_RUNTIME_DIR", str(tmp_path))
    service = core.QwenLiveAudioService()
    monkeypatch.setattr(service, "_resolve_audio", lambda _sd: resolved)

    service._run(
        core.QwenLiveStartRequest(
            api_key="do-not-log-this-key",
            workspace_id="test-workspace",
        ),
        stop_event,
    )

    assert service.status().state is core.QwenLiveState.STOPPED
    assert operations == [
        "connect",
        "timeout:0.25",
        "send",
        "recv",
        "stream_enter",
        "read",
        "send",
        "recv",
        "write",
        "stream_exit",
        "close",
    ]
    assert len(sent_messages) == 2
    input_append = json.loads(sent_messages[1])
    assert input_append["type"] == "input_audio_buffer.append"
    assert base64.b64decode(input_append["audio"]) == core._resample_pcm16_mono(
        microphone_pcm, 48_000, core.QWEN_INPUT_RATE
    )
    expected_response = core._resample_pcm16_mono(
        response_pcm, core.QWEN_OUTPUT_RATE, 48_000
    )
    assert written_chunks == [expected_response + b"\x00" * (3_840 - len(expected_response))]
    diagnostic_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "qwen-live").iterdir()
    )
    assert "do-not-log-this-key" not in diagnostic_text
    assert base64.b64encode(microphone_pcm).decode("ascii") not in diagnostic_text
    assert base64.b64encode(response_pcm).decode("ascii") not in diagnostic_text


def test_qwen_live_status_api_does_not_start_audio_session() -> None:
    client = TestClient(app)
    response = client.get("/v1/realtime/qwen/live")

    assert response.status_code == 200
    assert response.json()["state"] == "stopped"


def test_source_keeps_build_389_synchronous_architecture_and_configuration() -> None:
    source = Path(core.__file__).read_text(encoding="utf-8")
    diagnostics_source = Path(QwenLiveDiagnostics.__module__.replace(".", "/") + ".py")
    diagnostics_text = diagnostics_source.read_text(encoding="utf-8")
    read_position = source.index("stream.read(frames)")
    send_position = source.index('"type": "input_audio_buffer.append"')
    recv_position = source.index("provider._receive_json(ws)", read_position)
    write_position = source.index("stream.write(chunk)")

    assert read_position < send_position < recv_position < write_position
    assert source.count("stream.read(frames)") == 1
    assert source.count("stream.write(chunk)") == 1
    assert source.count("sd.RawStream(") == 1
    assert "ws.settimeout(0.25)" in source
    assert "CAPTURE_MS = 40" in source
    assert "QWEN_INPUT_RATE = 16_000" in source
    assert "QWEN_OUTPUT_RATE = 24_000" in source
    for forbidden in (
        "RawInputStream",
        "RawOutputStream",
        "capture_thread",
        "playback_thread",
        "Queue(",
        "asyncio",
        "callback=",
    ):
        assert forbidden not in source
    assert "threading" not in diagnostics_text
    assert "import queue" not in diagnostics_text
    assert "from queue import" not in diagnostics_text
    assert "Queue(" not in diagnostics_text

    session = core._audio_session_update(
        "qwen3.5-omni-flash-realtime", "Tina"
    )["session"]
    assert session["turn_detection"] == {
        "type": "server_vad",
        "threshold": 0.5,
        "silence_duration_ms": 800,
    }
    assert session["input_audio_format"] == "pcm"
    assert session["output_audio_format"] == "pcm"
    assert session["instructions"] == (
        "You are ORION's realtime conversational voice. "
        "Talk naturally in the language used by the user."
    )
    assert "tools" not in session
