from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import orion.qwen_live_audio_core as core
from orion.qwen_live_diagnostics import QwenLiveDiagnostics


def _diagnostics(tmp_path: Path) -> QwenLiveDiagnostics:
    return QwenLiveDiagnostics(
        model="qwen3.5-omni-flash-realtime",
        region="singapore",
        vad_type="server_vad",
        silence_duration_ms=800,
        qwen_input_rate=core.QWEN_INPUT_RATE,
        qwen_output_rate=core.QWEN_OUTPUT_RATE,
        runtime_dir=tmp_path,
    )


def test_periodic_ping_is_emitted_and_missing_pong_times_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(core, "PING_INTERVAL_SEC", 0.01)
    monkeypatch.setattr(core, "PONG_TIMEOUT_SEC", 0.01)
    stop_event = threading.Event()
    ping_sent = threading.Event()
    diagnostics = _diagnostics(tmp_path)
    failures: core.queue.Queue[core._WorkerFailure] = core.queue.Queue(maxsize=1)
    monitor = core._SessionMonitor(connected_ns=time.perf_counter_ns())

    class FakeWebSocket:
        def ping(self) -> None:
            ping_sent.set()

    worker = threading.Thread(
        target=core.QwenLiveAudioService()._heartbeat_worker,
        args=(
            FakeWebSocket(),
            stop_event,
            diagnostics,
            failures,
            threading.Lock(),
            monitor,
        ),
    )
    worker.start()
    assert ping_sent.wait(timeout=1.0)
    worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert stop_event.is_set()
    assert isinstance(failures.get_nowait().error, core._HeartbeatTimeoutError)
    recent_events = diagnostics.websocket_forensics()["recent_events"]
    assert isinstance(recent_events, list)
    events = [event["event"] for event in recent_events]
    assert "PONG_TIMEOUT" in events


def test_pong_updates_last_pong_and_clears_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core, "PONG_TIMEOUT_SEC", 10.0)
    monitor = core._SessionMonitor(connected_ns=1_000)
    monitor.record_ping(2_000)
    assert monitor.heartbeat_expired(10_000_002_000)

    monitor.record_pong(3_000)

    assert not monitor.heartbeat_expired(20_000_000_000)
    assert monitor.ages_ms(4_000)["last_pong_age_ms"] == pytest.approx(0.001)


def test_ordinary_receive_timeout_is_not_a_heartbeat_failure() -> None:
    monitor = core._SessionMonitor(connected_ns=0)

    assert not monitor.heartbeat_expired(250_000_000)
    assert not monitor.heartbeat_expired(60_000_000_000)


def test_audio_transmit_activity_does_not_suppress_periodic_ping() -> None:
    monitor = core._SessionMonitor(connected_ns=0)
    monitor.record_tx(14_900_000_000)

    assert monitor.ping_due(15_000_000_000)


@pytest.mark.parametrize(
    ("setup", "elapsed_sec", "expected_event"),
    [
        ("created", 20.1, "RESPONSE_FIRST_AUDIO_TIMEOUT"),
        ("delta", 5.1, "RESPONSE_INTER_DELTA_TIMEOUT"),
        ("created", 30.1, "RESPONSE_COMPLETION_TIMEOUT"),
    ],
)
def test_response_watchdog_deadlines(
    setup: str, elapsed_sec: float, expected_event: str
) -> None:
    start_ns = 1_000_000_000
    monitor = core._SessionMonitor(connected_ns=start_ns)
    monitor.response_created({"response": {"id": "response-7"}}, start_ns)
    reference_ns = start_ns
    if setup == "delta":
        reference_ns += 1_000_000_000
        monitor.audio_delta(reference_ns)

    timeout = monitor.response_timeout(
        reference_ns + int(elapsed_sec * 1_000_000_000)
    )

    assert timeout is not None
    assert timeout.event == expected_event
    assert timeout.response_id == "response-7"
    assert monitor.response_timeout(reference_ns + 60_000_000_000) is None


def test_response_watchdog_stops_unbounded_silent_padding() -> None:
    playback = core._BoundedPlaybackBuffer(max_bytes=16)
    monitor = core._SessionMonitor(connected_ns=0)
    monitor.response_created({"response": {"id": "response-1"}}, 0)
    playback.mark_response_active(True)
    playback.append(b"\x01\x00")

    active = playback.take_block(2)
    assert active.response_active is True
    assert active.response_audio_frames == 0

    assert monitor.response_timeout(20_100_000_000) is not None
    playback.mark_response_active(False)
    drained = playback.take_block(2)
    idle = playback.take_block(2)

    assert drained.response_audio_frames == 1
    assert idle.response_active is False
    assert idle.zero_frames == 2


def test_audio_done_stops_padding_but_completion_deadline_remains() -> None:
    monitor = core._SessionMonitor(connected_ns=0)
    monitor.response_created({"response": {"id": "response-2"}}, 0)
    assert monitor.audio_delta(1_000_000_000)

    monitor.response_audio_done(2_000_000_000)

    timeout = monitor.response_timeout(30_100_000_000)
    assert timeout is not None
    assert timeout.event == "RESPONSE_COMPLETION_TIMEOUT"


def test_late_audio_is_ignored_until_next_response_created() -> None:
    monitor = core._SessionMonitor(connected_ns=0)
    monitor.response_created({"response": {"id": "response-1"}}, 0)
    assert monitor.response_timeout(20_100_000_000) is not None
    assert not monitor.audio_delta(21_000_000_000)

    monitor.response_created({"response": {"id": "response-2"}}, 22_000_000_000)
    assert monitor.audio_delta(23_000_000_000)


def test_error_stop_stopped_then_start_uses_fresh_stop_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = core.QwenLiveAudioService()
    service._set(state=core.QwenLiveState.ERROR, message="controlled failure")

    assert service.stop().state is core.QwenLiveState.STOPPED
    first_stop_event = service._stop
    observed_stop_events: list[threading.Event] = []

    def fake_run(
        _request: core.QwenLiveStartRequest, stop_event: threading.Event
    ) -> None:
        observed_stop_events.append(stop_event)

    monkeypatch.setattr(service, "_run", fake_run)
    status = service.start(
        core.QwenLiveStartRequest(api_key="secret", workspace_id="workspace")
    )
    assert status.state is core.QwenLiveState.STARTING
    assert service._thread is not None
    service._thread.join(timeout=1.0)

    assert observed_stop_events == [service._stop]
    assert service._stop is not first_stop_event


def test_clean_remote_close_is_classified_without_worker_failure(
    tmp_path: Path,
) -> None:
    stop_event = threading.Event()
    diagnostics = _diagnostics(tmp_path)
    diagnostics.record_websocket_close_frame(
        (1000).to_bytes(2, "big") + b"normal", t_ns=time.perf_counter_ns()
    )
    failures: core.queue.Queue[core._WorkerFailure] = core.queue.Queue(maxsize=1)

    class ClosingProvider:
        def _receive_json(self, _ws: object) -> dict[str, str]:
            raise ValueError("close payload consumed")

    service = core.QwenLiveAudioService()
    service._receive_worker(
        ws=object(),
        websocket=SimpleNamespace(WebSocketTimeoutException=TimeoutError),
        provider=ClosingProvider(),  # type: ignore[arg-type]
        audio=SimpleNamespace(native_rate=48_000),  # type: ignore[arg-type]
        stop_event=stop_event,
        playback=core._BoundedPlaybackBuffer(max_bytes=16),
        diagnostics=diagnostics,
        failures=failures,
        monitor=core._SessionMonitor(connected_ns=time.perf_counter_ns()),
    )

    assert stop_event.is_set()
    assert failures.empty()
    recent_events = diagnostics.websocket_forensics()["recent_events"]
    assert isinstance(recent_events, list)
    events = [event["event"] for event in recent_events]
    assert "CLEAN_REMOTE_CLOSE" in events


def test_abrupt_eof_is_classified_as_connection_loss(tmp_path: Path) -> None:
    class WebSocketConnectionClosedException(Exception):
        pass

    class FailingProvider:
        def _receive_json(self, _ws: object) -> dict[str, str]:
            raise WebSocketConnectionClosedException("remote host was lost")

    stop_event = threading.Event()
    diagnostics = _diagnostics(tmp_path)
    failures: core.queue.Queue[core._WorkerFailure] = core.queue.Queue(maxsize=1)
    core.QwenLiveAudioService()._receive_worker(
        ws=object(),
        websocket=SimpleNamespace(WebSocketTimeoutException=TimeoutError),
        provider=FailingProvider(),  # type: ignore[arg-type]
        audio=SimpleNamespace(native_rate=48_000),  # type: ignore[arg-type]
        stop_event=stop_event,
        playback=core._BoundedPlaybackBuffer(max_bytes=16),
        diagnostics=diagnostics,
        failures=failures,
        monitor=core._SessionMonitor(connected_ns=time.perf_counter_ns()),
    )

    assert stop_event.is_set()
    recent_events = diagnostics.websocket_forensics()["recent_events"]
    assert isinstance(recent_events, list)
    classifications = [
        event.get("classification")
        for event in recent_events
        if event["event"] == "CONNECTION_CLASSIFIED"
    ]
    assert classifications == ["ABRUPT_EOF"]


def test_transport_architecture_remains_blocking_single_raw_stream() -> None:
    import inspect

    source = inspect.getsource(core.QwenLiveAudioService._run_transport)
    assert source.count("sd.RawStream(") == 1
    assert "RawInputStream" not in source
    assert "RawOutputStream" not in source
    assert "callback=" not in source
    assert 'name="orion-qwen-send"' in source
    assert 'name="orion-qwen-receive"' in source
