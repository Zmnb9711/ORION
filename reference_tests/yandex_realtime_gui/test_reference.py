from __future__ import annotations

import asyncio
import base64
import importlib
import queue
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from typing import Any

import pytest

REFERENCE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(REFERENCE_DIR))

core = importlib.import_module("yandex_reference_core")
gui = importlib.import_module("yandex_realtime_tester")


def device(
    index: int,
    name: str,
    hostapi_index: int = 0,
    hostapi_name: str = "MME",
    max_input: int = 1,
    max_output: int = 1,
) -> Any:
    return core.AudioDevice(
        index=index,
        name=name,
        hostapi_index=hostapi_index,
        hostapi_name=hostapi_name,
        default_samplerate=44_100.0,
        max_input_channels=max_input,
        max_output_channels=max_output,
    )


INPUT = device(1, "Duplicate USB Audio")
OUTPUT = device(6, "Duplicate USB Audio")


def config(api_key: str = "secret-reference-key") -> Any:
    return core.SessionConfig(
        api_key=api_key,
        folder_id="b1gexamplefolder",
        model=core.DEFAULT_MODEL,
        voice=core.DEFAULT_VOICE,
        language=core.DEFAULT_LANGUAGE,
        input_device=INPUT,
        output_device=OUTPUT,
    )


class FakeInputStream:
    def __init__(self, backend: "FakeAudioBackend", kwargs: dict[str, object]) -> None:
        self.backend = backend
        self.kwargs = kwargs

    def __enter__(self) -> "FakeInputStream":
        self.backend.input_open_count += 1
        self.backend.input_stream_args.append(self.kwargs)
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, frames: int) -> tuple[bytes, bool]:
        time.sleep(0.002)
        return self.backend.input_pcm or (b"\x01\x00" * frames), False


class FakeOutputStream:
    def __init__(self, backend: "FakeAudioBackend", kwargs: dict[str, object]) -> None:
        self.backend = backend
        self.kwargs = kwargs

    def __enter__(self) -> "FakeOutputStream":
        self.backend.output_open_count += 1
        self.backend.output_stream_args.append(self.kwargs)
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def write(self, pcm: bytes) -> None:
        self.backend.write_started.set()
        if self.backend.block_output_writes:
            if not self.backend.allow_output_write.wait(2):
                raise TimeoutError("fake output write was not released")
        self.backend.output_writes.append(bytes(pcm))


class FakeAudioBackend:
    def __init__(self, *, fail_input: bool = False, fail_output: bool = False) -> None:
        self.fail_input = fail_input
        self.fail_output = fail_output
        self.input_open_count = 0
        self.output_open_count = 0
        self.input_stream_args: list[dict[str, object]] = []
        self.output_stream_args: list[dict[str, object]] = []
        self.output_writes: list[bytes] = []
        self.block_output_writes = False
        self.write_started = threading.Event()
        self.allow_output_write = threading.Event()
        self.check_input_calls: list[dict[str, object]] = []
        self.check_output_calls: list[dict[str, object]] = []
        self.input_pcm = b""

    @staticmethod
    def query_hostapis() -> list[dict[str, object]]:
        return [{"name": "MME"}, {"name": "Windows WASAPI"}]

    @staticmethod
    def query_devices() -> list[dict[str, object]]:
        return [
            {
                "name": "No channels",
                "hostapi": 0,
                "default_samplerate": 44_100.0,
                "max_input_channels": 0,
                "max_output_channels": 0,
            },
            {
                "name": "Duplicate USB Audio",
                "hostapi": 0,
                "default_samplerate": 44_100.0,
                "max_input_channels": 2,
                "max_output_channels": 0,
            },
            {
                "name": "Input WASAPI",
                "hostapi": 1,
                "default_samplerate": 48_000.0,
                "max_input_channels": 1,
                "max_output_channels": 0,
            },
            {
                "name": "Output WASAPI",
                "hostapi": 1,
                "default_samplerate": 48_000.0,
                "max_input_channels": 0,
                "max_output_channels": 2,
            },
            {
                "name": "Unused",
                "hostapi": 0,
                "default_samplerate": 44_100.0,
                "max_input_channels": 0,
                "max_output_channels": 0,
            },
            {
                "name": "Unused 2",
                "hostapi": 0,
                "default_samplerate": 44_100.0,
                "max_input_channels": 0,
                "max_output_channels": 0,
            },
            {
                "name": "Duplicate USB Audio",
                "hostapi": 0,
                "default_samplerate": 44_100.0,
                "max_input_channels": 0,
                "max_output_channels": 2,
            },
        ]

    def check_input_settings(self, **kwargs: object) -> None:
        self.check_input_calls.append(kwargs)
        if self.fail_input:
            raise RuntimeError("invalid sample rate")

    def check_output_settings(self, **kwargs: object) -> None:
        self.check_output_calls.append(kwargs)
        if self.fail_output:
            raise RuntimeError("invalid sample rate")

    def RawInputStream(self, **kwargs: object) -> FakeInputStream:
        return FakeInputStream(self, kwargs)

    def RawOutputStream(self, **kwargs: object) -> FakeOutputStream:
        return FakeOutputStream(self, kwargs)


class FakeTransport:
    def __init__(self, events: list[dict[str, object]] | None = None) -> None:
        self.events = list(
            events
            or [
                {"type": "session.created", "session": {"id": "sess-fake"}},
                {"type": "session.updated", "session": {"id": "sess-fake"}},
            ]
        )
        self.sent: list[dict[str, object]] = []
        self.url = ""
        self.headers: dict[str, str] = {}
        self.connected = False
        self.closed = False
        self.close_code: int | None = None
        self.close_reason = ""

    async def connect(self, url: str, headers: dict[str, str]) -> None:
        self.connected = True
        self.url = url
        self.headers = dict(headers)

    async def send_json(self, event: dict[str, object]) -> None:
        if self.closed:
            raise ConnectionError("fake transport closed")
        self.sent.append(event)

    async def receive(self) -> Any:
        await asyncio.sleep(0.002)
        if self.events:
            return core.TransportMessage(event=self.events.pop(0))
        if self.closed:
            return core.TransportMessage(
                close_code=self.close_code, close_reason=self.close_reason
            )
        return core.TransportMessage()

    async def close(self) -> None:
        self.closed = True
        self.close_code = 1000
        self.close_reason = "normal local stop"


def wait_until(predicate: Any, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached before timeout")


def audio_delta(response_id: str, pcm: bytes) -> dict[str, object]:
    return {
        "type": "response.output_audio.delta",
        "response_id": response_id,
        "delta": base64.b64encode(pcm).decode("ascii"),
    }


def queued_slices(session: Any) -> list[Any]:
    result = []
    while True:
        try:
            item = session.playback_queue.get_nowait()
        except queue.Empty:
            return result
        if item is session._playback_sentinel:
            session.playback_queue.put(item)
            return result
        result.append(item)


def new_tk() -> tk.Tk:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.fail(f"Tkinter GUI cannot be created: {exc}")
    root.withdraw()
    return root


def test_modules_import_and_current_constants() -> None:
    assert core.APP_NAME == "Yandex Realtime Reference Tester"
    assert core.APP_VERSION == "1.1.0"
    assert core.ENDPOINT == "wss://ai.api.cloud.yandex.net/v1/realtime"
    assert core.DEFAULT_MODEL == "speech-realtime-260528"
    assert core.INPUT_RATE == core.OUTPUT_RATE == 44_100
    assert core.CHANNELS == 1
    assert core.SAMPLE_BYTES == 2
    assert core.PLAYBACK_SLICE_MS == 20
    assert core.PLAYBACK_SLICE_FRAMES == 882
    assert core.PLAYBACK_SLICE_BYTES == 1764
    assert gui.LANGUAGE_LABEL == "Russian (ru-RU)"


def test_model_url_uses_folder_model_uri_and_no_legacy_model() -> None:
    assert core.build_model_uri("folder", core.DEFAULT_MODEL) == (
        "gpt://folder/speech-realtime-260528"
    )
    assert core.build_url("folder", core.DEFAULT_MODEL) == (
        "wss://ai.api.cloud.yandex.net/v1/realtime"
        "?model=gpt://folder/speech-realtime-260528"
    )
    with pytest.raises(ValueError, match="model name only"):
        core.build_model_uri("folder", "gpt://folder/speech-realtime-260528")


def test_documented_session_update_schema_is_exact() -> None:
    payload = core.build_session_update(config())
    assert payload == {
        "type": "session.update",
        "session": {
            "instructions": core.DEFAULT_INSTRUCTIONS,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": 44_100},
                    "languages": ["ru-RU"],
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "silence_duration_ms": 400,
                    },
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": 44_100},
                    "voice": "dasha",
                },
            },
        },
    }
    assert "tools" not in payload["session"]


def test_input_base64_event_and_strict_output_decode_preserve_pcm() -> None:
    pcm = bytes(range(64))
    encoded = core.encode_input_audio_event(pcm)
    assert encoded["type"] == "input_audio_buffer.append"
    assert isinstance(encoded["audio"], str)
    assert base64.b64decode(encoded["audio"], validate=True) == pcm
    assert core.decode_output_audio(
        {"type": "response.output_audio.delta", "delta": encoded["audio"]}
    ) == pcm
    with pytest.raises(Exception):
        core.decode_output_audio({"delta": "not base64!!!"})


def test_portaudio_enumeration_filters_direction_and_keeps_host_identity() -> None:
    inputs, outputs = core.list_audio_devices(FakeAudioBackend())
    assert [(item.index, item.hostapi_name) for item in inputs] == [
        (1, "MME"),
        (2, "Windows WASAPI"),
    ]
    assert [(item.index, item.hostapi_name) for item in outputs] == [
        (3, "Windows WASAPI"),
        (6, "MME"),
    ]
    assert inputs[0].label == "1 — Duplicate USB Audio — MME"
    assert outputs[1].label == "6 — Duplicate USB Audio — MME"
    assert inputs[0].name == outputs[1].name
    assert inputs[0].index != outputs[1].index


def test_actual_portaudio_enumeration_is_read_only_and_returns_typed_lists() -> None:
    inputs, outputs = core.list_audio_devices()
    assert isinstance(inputs, list)
    assert isinstance(outputs, list)
    assert all(isinstance(item, core.AudioDevice) for item in inputs + outputs)


def test_validate_audio_format_uses_exact_selected_numeric_indices() -> None:
    backend = FakeAudioBackend()
    core.validate_audio_format(config(), backend)
    assert backend.check_input_calls[0]["device"] == 1
    assert backend.check_output_calls[0]["device"] == 6
    assert backend.check_input_calls[0]["samplerate"] == 44_100
    assert backend.check_output_calls[0]["samplerate"] == 44_100


def test_stale_exact_identity_is_rejected_even_when_index_still_exists() -> None:
    selected = device(1, "Old identity")
    current = [device(1, "New identity")]
    with pytest.raises(ValueError, match="selection is stale"):
        core.find_exact_device(selected, current, "Input")


def test_gui_creation_destruction_and_qwen_companion_layout() -> None:
    root = new_tk()
    app = gui.TesterApp(root, device_lister=lambda: ([INPUT], [OUTPUT]), poll_events=False)
    assert root.title() == core.APP_NAME
    assert app.api_key.cget("show") == "•"
    assert app.model.get() == "speech-realtime-260528"
    assert app.voice.get() == "dasha"
    assert app.language.get() == "Russian (ru-RU)"
    assert set(app.metric_vars) == {
        "first_audio_latency_ms",
        "delta_count",
        "total_audio_duration_ms",
        "max_delta_gap_ms",
        "average_delta_gap_ms",
        "response_completed",
        "websocket_close",
    }
    app.close()


def test_main_exposes_non_live_packaged_smoke_modes(monkeypatch: Any) -> None:
    assert "--smoke-test" in gui.main.__code__.co_consts
    assert "--gui-smoke-test" in gui.main.__code__.co_consts


def test_gui_refresh_invalidates_stale_selection_without_rebinding_by_name() -> None:
    root = new_tk()
    rounds = [
        ([device(1, "Same name")], [device(6, "Output")]),
        ([device(1, "Same name", hostapi_index=1, hostapi_name="Windows WASAPI")], [OUTPUT]),
    ]

    def lister() -> tuple[list[Any], list[Any]]:
        return rounds.pop(0)

    app = gui.TesterApp(root, device_lister=lister, poll_events=False)
    assert app.input_device.current() == 0
    app.refresh_devices()
    assert app.input_device.current() == -1
    text = app.events.get("1.0", "end")
    assert "audio.device.selection_invalidated" in text
    root.destroy()


def test_gui_duplicate_names_preserve_concrete_index_across_reordered_refresh() -> None:
    root = new_tk()
    first = [device(1, "Duplicate"), device(9, "Duplicate")]
    second = [device(9, "Duplicate"), device(1, "Duplicate")]
    rounds = [(first, [OUTPUT]), (second, [OUTPUT])]
    app = gui.TesterApp(root, device_lister=lambda: rounds.pop(0), poll_events=False)
    app.input_device.current(1)
    app.refresh_devices()
    selected = app._selected_device(app.input_device, app.inputs)
    assert selected is not None
    assert selected.index == 9
    root.destroy()


def test_fake_transport_lifecycle_uses_exact_stream_indices_and_clean_close() -> None:
    backend = FakeAudioBackend()
    transport = FakeTransport()
    received: list[tuple[str, dict[str, object]]] = []
    session = core.YandexReferenceSession(
        config(),
        lambda event, fields: received.append((event, fields)),
        audio_backend=backend,
        transport_factory=lambda: transport,
    )
    session.start()
    wait_until(lambda: any(event == "session.updated" for event, _ in received))
    wait_until(lambda: backend.input_open_count == 1 and backend.output_open_count == 1)
    session.stop(wait=True)
    assert not session.thread.is_alive()
    assert backend.input_stream_args[0]["device"] == 1
    assert backend.output_stream_args[0]["device"] == 6
    assert transport.sent[0]["type"] == "session.update"
    assert transport.headers == {"Authorization": "Api-Key secret-reference-key"}
    assert session.websocket_close["code"] == 1000
    assert session.websocket_close["clean"] is True


def test_start_stop_start_stop_with_fresh_fake_sessions() -> None:
    sessions: list[Any] = []
    for _ in range(2):
        backend = FakeAudioBackend()
        transport = FakeTransport()
        received: list[str] = []
        session = core.YandexReferenceSession(
            config(),
            lambda event, _fields: received.append(event),
            audio_backend=backend,
            transport_factory=lambda transport=transport: transport,
        )
        sessions.append(session)
        session.start()
        wait_until(lambda: "session.updated" in received)
        session.stop(wait=True)
    assert all(not session.thread.is_alive() for session in sessions)
    assert all(session.websocket_close["code"] == 1000 for session in sessions)


def test_single_exact_size_delta_creates_one_exact_slice() -> None:
    session = core.YandexReferenceSession(config(), lambda *_args: None)
    session.handle_event({"type": "response.created", "response": {"id": "r1"}})
    pcm = bytes(range(252)) * 7
    assert len(pcm) == 1764
    session.handle_event(audio_delta("r1", pcm))
    slices = queued_slices(session)
    assert len(slices) == 1
    assert slices[0].pcm == pcm
    assert slices[0].response_id == "r1"
    assert slices[0].sequence == 1


def test_two_slice_delta_preserves_exact_concatenation() -> None:
    session = core.YandexReferenceSession(config(), lambda *_args: None)
    session.handle_event({"type": "response.created", "response": {"id": "r1"}})
    pcm = bytes(range(252)) * 14
    session.handle_event(audio_delta("r1", pcm))
    slices = queued_slices(session)
    assert [len(item.pcm) for item in slices] == [1764, 1764]
    assert b"".join(item.pcm for item in slices) == pcm


def test_short_final_slice_is_exact_frame_aligned_and_never_padded() -> None:
    session = core.YandexReferenceSession(config(), lambda *_args: None)
    session.handle_event({"type": "response.created", "response": {"id": "r1"}})
    pcm = (bytes(range(252)) * 7) + b"\x01\x02" * 50
    session.handle_event(audio_delta("r1", pcm))
    slices = queued_slices(session)
    assert [len(item.pcm) for item in slices] == [1764, 100]
    assert slices[-1].pcm == pcm[-100:]
    assert b"".join(item.pcm for item in slices) == pcm
    assert not slices[-1].pcm.endswith(b"\x00\x00")


def test_multiple_provider_deltas_keep_unbounded_global_provider_order() -> None:
    session = core.YandexReferenceSession(config(), lambda *_args: None)
    session.handle_event({"type": "response.created", "response": {"id": "r1"}})
    deltas = [b"\x01\x02" * 1000, b"\x03\x04" * 10, b"\x05\x06" * 900]
    for pcm in deltas:
        session.handle_event(audio_delta("r1", pcm))
    slices = queued_slices(session)
    assert session.playback_queue.maxsize == 0
    assert b"".join(item.pcm for item in slices) == b"".join(deltas)
    assert [item.sequence for item in slices] == list(range(1, len(slices) + 1))
    assert all(item.pcm for item in slices)
    assert all(len(item.pcm) <= 1764 for item in slices)


def test_documented_barge_in_clears_only_interrupted_response_queue() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    session = core.YandexReferenceSession(
        config(), lambda event, fields: events.append((event, fields))
    )
    session.handle_event({"type": "response.created", "response": {"id": "old"}})
    old = b"\x01\x02" * 2000
    session.handle_event(audio_delta("old", old))
    session.handle_event(
        {
            "type": "input_audio_buffer.speech_started",
            "item_id": "user-2",
            "audio_start_ms": 20,
        }
    )
    assert session.playback_queue.empty()
    session.handle_event(audio_delta("old", old))
    assert session.playback_queue.empty()
    session.handle_event({"type": "response.created", "response": {"id": "new"}})
    new = b"\x03\x04" * 10
    session.handle_event(audio_delta("new", new))
    queued = session.playback_queue.get_nowait()
    assert queued.pcm == new
    assert queued.response_id == "new"
    assert queued.epoch != session.response_playback["old"].epoch
    assert session.playback_interruption_count == 1
    assert session.queued_slices_removed_count == 3
    assert session.queued_bytes_removed == len(old)
    assert session.stale_bytes_discarded == len(old)


def test_uninterrupted_worker_writes_every_slice_exactly_once_in_order() -> None:
    backend = FakeAudioBackend()
    session = core.YandexReferenceSession(
        config(), lambda *_args: None, audio_backend=backend
    )
    session.session_ready.set()
    session.handle_event({"type": "response.created", "response": {"id": "r1"}})
    deltas = [b"\x01\x02" * 1200, b"\x03\x04" * 950]
    for pcm in deltas:
        session.handle_event(audio_delta("r1", pcm))
    session.handle_event(
        {"type": "response.done", "response": {"id": "r1", "status": "completed"}}
    )
    worker = threading.Thread(target=session._playback)
    worker.start()
    expected_slices = session.response_playback["r1"].slices_created
    wait_until(lambda: len(backend.output_writes) == expected_slices)
    session.stop_event.set()
    session.playback_queue.put(session._playback_sentinel)
    worker.join(2)
    assert not worker.is_alive()
    assert b"".join(backend.output_writes) == b"".join(deltas)
    assert session.total_slices_written == expected_slices
    assert session.playback_bytes == sum(map(len, deltas))
    assert backend.output_open_count == 1


def test_barge_in_during_committed_short_write_allows_only_that_write_to_finish() -> None:
    backend = FakeAudioBackend()
    backend.block_output_writes = True
    session = core.YandexReferenceSession(
        config(), lambda *_args: None, audio_backend=backend
    )
    session.session_ready.set()
    session.handle_event({"type": "response.created", "response": {"id": "old"}})
    pcm = b"\x01\x02" * (core.PLAYBACK_SLICE_FRAMES * 3)
    session.handle_event(audio_delta("old", pcm))
    worker = threading.Thread(target=session._playback)
    worker.start()
    assert backend.write_started.wait(2)
    session.handle_event(
        {
            "type": "input_audio_buffer.speech_started",
            "item_id": "user-2",
            "audio_start_ms": 20,
        }
    )
    assert session.current_write_response_id == "old"
    assert session.current_write_bytes == core.PLAYBACK_SLICE_BYTES
    assert session.current_write_active_at_interrupt_count == 1
    assert session.queued_slices_removed_count == 2
    backend.allow_output_write.set()
    wait_until(lambda: session.current_write_completed_after_interrupt_count == 1)
    session.stop_event.set()
    session.playback_queue.put(session._playback_sentinel)
    worker.join(2)
    assert backend.output_writes == [pcm[: core.PLAYBACK_SLICE_BYTES]]
    assert session.total_slices_written == 1
    assert session.current_write_completed_after_interrupt is True
    assert session.current_write_started_at is not None
    assert session.current_write_completed_at is not None
    assert session.application_stop_latency_estimate_ms is not None
    assert backend.output_open_count == 1


def test_late_old_delta_after_new_response_is_stale_and_never_inherits_new_epoch() -> None:
    session = core.YandexReferenceSession(config(), lambda *_args: None)
    session.handle_event({"type": "response.created", "response": {"id": "old"}})
    session.handle_event(audio_delta("old", b"\x01\x02" * 100))
    session.handle_event({"type": "input_audio_buffer.speech_started"})
    session.handle_event({"type": "response.created", "response": {"id": "new"}})
    old_epoch = session.response_playback["old"].epoch
    new_epoch = session.response_playback["new"].epoch
    session.handle_event(audio_delta("old", b"\x03\x04" * 1000))
    session.handle_event(audio_delta("new", b"\x05\x06" * 20))
    slices = queued_slices(session)
    assert old_epoch != new_epoch
    assert {item.response_id for item in slices} == {"new"}
    assert all(item.epoch == new_epoch for item in slices)
    assert session.response_playback["old"].slices_discarded_stale == 2


def test_old_response_done_cannot_change_new_response_playback_state() -> None:
    session = core.YandexReferenceSession(config(), lambda *_args: None)
    session.handle_event({"type": "response.created", "response": {"id": "old"}})
    session.handle_event({"type": "response.created", "response": {"id": "new"}})
    new_epoch = session.response_playback["new"].epoch
    session.handle_event(
        {"type": "response.done", "response": {"id": "old", "status": "cancelled"}}
    )
    assert session.active_playback_response_id == "new"
    assert session.response_playback["new"].epoch == new_epoch
    assert session.response_playback["new"].provider_done is False


def test_provider_done_before_local_completion_keeps_valid_slices_playable() -> None:
    session = core.YandexReferenceSession(config(), lambda *_args: None)
    session.handle_event({"type": "response.created", "response": {"id": "r1"}})
    pcm = b"\x01\x02" * 1000
    session.handle_event(audio_delta("r1", pcm))
    session.handle_event(
        {"type": "response.done", "response": {"id": "r1", "status": "completed"}}
    )
    slices = queued_slices(session)
    assert b"".join(item.pcm for item in slices) == pcm
    state = session.response_playback["r1"]
    assert state.provider_done is True
    assert state.local_completion_state(None) == "queued"


def test_repeated_and_empty_interruptions_have_separate_metric_meanings() -> None:
    session = core.YandexReferenceSession(config(), lambda *_args: None)
    session.handle_event({"type": "input_audio_buffer.speech_started"})
    assert session.speech_started_seen_count == 1
    assert session.playback_invalidation_request_count == 1
    assert session.active_response_invalidation_count == 0
    assert session.playback_interruption_count == 0

    session.handle_event({"type": "response.created", "response": {"id": "r1"}})
    session.handle_event(audio_delta("r1", b"\x01\x02" * 100))
    session.handle_event({"type": "input_audio_buffer.speech_started"})
    session.handle_event({"type": "input_audio_buffer.speech_started"})
    assert session.speech_started_seen_count == 3
    assert session.playback_invalidation_request_count == 3
    assert session.active_response_invalidation_count == 1
    assert session.playback_interruption_count == 1


def test_metrics_duration_delta_gaps_and_preferred_first_audio_latency() -> None:
    values = iter([10.0, 10.25, 10.30, 10.42])
    session = core.YandexReferenceSession(config(), lambda *_args: None, clock=lambda: next(values))
    session.handle_event(
        {"type": "input_audio_buffer.speech_stopped", "item_id": "u1", "audio_end_ms": 500}
    )
    session.handle_event({"type": "response.created", "response": {"id": "r1"}})
    chunk = b"\x00\x00" * 4410  # 100 ms at mono PCM16/44.1 kHz
    encoded = base64.b64encode(chunk).decode("ascii")
    session.handle_event(
        {"type": "response.output_audio.delta", "response_id": "r1", "delta": encoded}
    )
    session.handle_event(
        {"type": "response.output_audio.delta", "response_id": "r1", "delta": encoded}
    )
    summary = session.latest_response_summary()
    assert summary["first_audio_latency_ms"] == 300.0
    assert summary["latency_basis"].startswith("input_audio_buffer.speech_stopped")
    assert summary["delta_count"] == 2
    assert summary["total_audio_duration_ms"] == 200.0
    assert summary["max_delta_gap_ms"] == 120.0
    assert summary["average_delta_gap_ms"] == 120.0


def test_transcription_output_text_and_response_completion_parsing() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    session = core.YandexReferenceSession(
        config(), lambda event, fields: events.append((event, fields))
    )
    session.handle_event(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "u1",
            "content_index": 0,
            "transcript": "Привет. Как дела?",
        }
    )
    session.handle_event({"type": "response.created", "response": {"id": "r1"}})
    session.handle_event(
        {"type": "response.output_text.delta", "response_id": "r1", "delta": "Хорошо"}
    )
    session.handle_event(
        {"type": "response.done", "response": {"id": "r1", "status": "cancelled"}}
    )
    assert session.transcription_count == 1
    assert session.latest_response_summary()["response_completed"] is False
    session.handle_event({"type": "response.created", "response": {"id": "r2"}})
    session.handle_event(
        {"type": "response.done", "response": {"id": "r2", "status": "completed"}}
    )
    assert session.latest_response_summary()["response_completed"] is True
    assert any(fields.get("transcript") == "Привет. Как дела?" for _, fields in events)


def test_server_error_event_settles_session_into_terminal_state() -> None:
    statuses: list[str] = []
    session = core.YandexReferenceSession(
        config(),
        lambda event, fields: statuses.append(str(fields.get("value")))
        if event == "status"
        else None,
    )
    session.handle_event(
        {
            "type": "error",
            "event_id": "evt-error",
            "error": {
                "type": "invalid_request_error",
                "code": "invalid_value",
                "message": "invalid session configuration",
                "param": "audio.input.format.rate",
            },
        }
    )
    assert session.stop_event.is_set()
    assert session.server_errors == ["invalid session configuration"]
    assert statuses == ["SERVER ERROR"]


def test_input_signal_aggregate_has_no_pcm_storage() -> None:
    session = core.YandexReferenceSession(config(), lambda *_args: None)
    session._record_input_signal(b"\x00\x00\xff\x7f\x00\x80")
    report = session.report()
    signal = report["INPUT SIGNAL"]
    assert signal["captured_blocks"] == 1
    assert signal["captured_bytes"] == 6
    assert signal["peak_pcm16"] == 32768
    assert signal["rms_pcm16"] > 0
    assert "pcm" not in {key.casefold() for key in signal}


def test_diagnostic_report_redacts_all_credentials_and_never_contains_audio_payload() -> None:
    key = "highly-secret-api-key"
    session = core.YandexReferenceSession(config(key), lambda *_args: None)
    raw_pcm = b"RAW_PCM_SENTINEL"
    audio_b64 = base64.b64encode(raw_pcm).decode("ascii")
    session.transport_errors.extend(
        [
            f"Authorization: Api-Key {key}",
            f"Bearer {key}",
            f"https://example.invalid/?api_key={key}",
        ]
    )
    session.handle_event({"type": "response.created", "response": {"id": "r1"}})
    session.handle_event(
        {"type": "response.output_audio.delta", "response_id": "r1", "delta": audio_b64}
    )
    text = session.diagnostic_text()
    assert key not in text
    assert f"Api-Key {key}" not in text
    assert f"Bearer {key}" not in text
    assert audio_b64 not in text
    assert raw_pcm.decode("ascii") not in text
    assert "[REDACTED]" in text
    assert "response.output_audio.delta" in text
    assert '"bytes":16' in text
    assert "[PLAYBACK SLICING]" in text
    assert "slice_duration_target_ms: 20" in text
    assert "slice_target_bytes: 1764" in text
    assert "[INTERRUPTION]" in text
    assert "[RESPONSE-SCOPED PLAYBACK]" in text

    report = session.report()
    playback = report["RESPONSE-SCOPED PLAYBACK"]["responses"][0]
    assert playback["response_id"] == "r1"
    assert playback["provider_audio_bytes"] == len(raw_pcm)
    assert playback["slices_created"] == 1
    assert all("pcm" not in key.casefold() for key in playback)


def test_diagnostic_metrics_distinguish_queue_removal_from_current_write() -> None:
    session = core.YandexReferenceSession(config(), lambda *_args: None)
    session.handle_event({"type": "response.created", "response": {"id": "r1"}})
    pcm = b"\x01\x02" * (core.PLAYBACK_SLICE_FRAMES * 2)
    session.handle_event(audio_delta("r1", pcm))
    session.handle_event({"type": "input_audio_buffer.speech_started"})
    report = session.report()
    interruption = report["INTERRUPTION"]
    slicing = report["PLAYBACK SLICING"]
    assert interruption["speech_started_seen_count"] == 1
    assert interruption["playback_invalidation_request_count"] == 1
    assert interruption["active_response_invalidation_count"] == 1
    assert interruption["queued_slices_removed_count"] == 2
    assert interruption["queued_bytes_removed"] == len(pcm)
    assert interruption["current_write_active_at_interrupt_count"] == 0
    assert interruption["application_stop_latency_estimate_ms"] == 0.0
    assert slicing["total_slices_created"] == 2
    assert slicing["total_slices_written"] == 0
    assert slicing["max_slice_bytes"] == 1764
    assert slicing["max_slice_duration_ms"] == 20.0


def test_export_after_stopped_and_failed_session_opens_no_device_or_network(tmp_path: Path) -> None:
    backend = FakeAudioBackend()
    factory_calls = 0

    def transport_factory() -> FakeTransport:
        nonlocal factory_calls
        factory_calls += 1
        return FakeTransport()

    session = core.YandexReferenceSession(
        config(), lambda *_args: None, audio_backend=backend, transport_factory=transport_factory
    )
    session._terminal_error("SESSION CONFIG ERROR", RuntimeError("synthetic failure"))
    before = (backend.input_open_count, backend.output_open_count, factory_calls)
    target = tmp_path / "yandex-realtime-diagnostic.txt"
    core.write_diagnostic_report(target, session.diagnostic_text())
    after = (backend.input_open_count, backend.output_open_count, factory_calls)
    assert target.read_text(encoding="utf-8").startswith(core.APP_NAME)
    assert before == after == (0, 0, 0)


def test_export_after_clean_stop_opens_no_additional_device_or_network(tmp_path: Path) -> None:
    backend = FakeAudioBackend()
    transport = FakeTransport()
    session = core.YandexReferenceSession(
        config(),
        lambda *_args: None,
        audio_backend=backend,
        transport_factory=lambda: transport,
    )
    session.start()
    wait_until(lambda: session.session_ready.is_set())
    wait_until(lambda: backend.input_open_count == backend.output_open_count == 1)
    session.stop(wait=True)
    before = (backend.input_open_count, backend.output_open_count, len(transport.sent))
    target = tmp_path / "stopped-yandex-diagnostic.txt"
    core.write_diagnostic_report(target, session.diagnostic_text())
    after = (backend.input_open_count, backend.output_open_count, len(transport.sent))
    assert target.exists()
    assert before == after


@pytest.mark.parametrize("direction", ["input", "output"])
def test_unsupported_audio_format_fails_before_network_and_opens_no_stream(
    direction: str,
) -> None:
    backend = FakeAudioBackend(
        fail_input=direction == "input", fail_output=direction == "output"
    )
    factory_calls = 0
    statuses: list[str] = []

    def transport_factory() -> FakeTransport:
        nonlocal factory_calls
        factory_calls += 1
        return FakeTransport()

    session = core.YandexReferenceSession(
        config(),
        lambda event, fields: statuses.append(str(fields.get("value")))
        if event == "status"
        else None,
        audio_backend=backend,
        transport_factory=transport_factory,
    )
    session.start()
    session.thread.join(2)
    assert not session.thread.is_alive()
    assert "UNSUPPORTED AUDIO FORMAT" in statuses
    assert factory_calls == 0
    assert backend.input_open_count == backend.output_open_count == 0


def test_clean_app_shutdown_stops_active_session_with_bounded_destroy() -> None:
    root = new_tk()

    class FakeGuiSession:
        def __init__(self, _config: Any, _callback: Any) -> None:
            self.thread = None
            self.stop_calls = 0

        def start(self) -> None:
            return None

        def stop(self) -> None:
            self.stop_calls += 1

    app = gui.TesterApp(
        root,
        device_lister=lambda: ([INPUT], [OUTPUT]),
        session_factory=FakeGuiSession,
        poll_events=False,
    )
    app.api_key.insert(0, "key")
    app.folder_id.insert(0, "folder")
    app.start()
    fake = app.session
    app.close()
    assert fake.stop_calls == 1
