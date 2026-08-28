from __future__ import annotations

import asyncio
import base64
import inspect
import json
import threading
import zipfile
from collections import deque
from types import SimpleNamespace

import aiohttp
import orion.yandex_realtime_session as yandex_session_module
import pytest

from orion.realtime_audio_transport import RealtimeInputCommit, RealtimePcmFormat
from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
from orion.yandex_realtime_session import YandexRealtimeSession


class FakeDiagnostics:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def record(self, event: str, **fields: object) -> None:
        self.events.append((event, fields))


class FakeEndpoint:
    transport_id = "fake"
    pcm_format = RealtimePcmFormat()

    def __init__(self, stop: threading.Event, pcm: bytes) -> None:
        self.stop_event = stop
        self.inputs: deque[bytes | RealtimeInputCommit] = deque([pcm])
        self.started = 0
        self.stopped = 0
        self.events: list[tuple[str, object]] = []

    def start(self) -> None:
        self.started += 1

    def read_input(
        self, timeout: float = 0.1
    ) -> bytes | RealtimeInputCommit | None:
        return self.inputs.popleft() if self.inputs else None

    def failure(self) -> BaseException | None:
        return None

    def input_speech_started(self) -> None:
        self.events.append(("speech_started", None))

    def response_started(self, response_id: str) -> None:
        self.events.append(("response_started", response_id))

    def response_audio(self, response_id: str, pcm16le: bytes) -> None:
        self.events.append(("audio", (response_id, pcm16le)))

    def response_audio_done(self, response_id: str) -> None:
        self.events.append(("audio_done", response_id))

    def response_done(self, response_id: str, status: str) -> None:
        self.events.append(("response_done", (response_id, status)))
        self.stop_event.set()

    def stop(self) -> None:
        self.stopped += 1


class FakeWebSocket:
    def __init__(self, output_pcm: bytes, status: str = "completed") -> None:
        self.closed = False
        self.close_code: int | None = None
        self.sent: list[dict[str, object]] = []
        self.messages: asyncio.Queue[object] = asyncio.Queue()
        events = [
            {"type": "session.updated", "session": {"id": "session"}},
            {"type": "input_audio_buffer.speech_started"},
            {"type": "input_audio_buffer.speech_stopped"},
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "event_id": "event-user",
                "item_id": "item-user",
                "transcript": "Какая у меня скорость?",
            },
            {"type": "response.created", "response": {"id": "r1"}},
            {
                "type": "response.output_audio.delta",
                "response_id": "r1",
                "delta": base64.b64encode(output_pcm).decode("ascii"),
            },
            {"type": "response.output_audio.done", "response_id": "r1"},
            {
                "type": "response.output_audio_transcript.done",
                "event_id": "event-assistant",
                "item_id": "item-assistant",
                "response_id": "r1",
                "transcript": "Скорость отображается в узлах.",
            },
            {"type": "response.done", "response": {"id": "r1", "status": status}},
        ]
        for event in events:
            self.messages.put_nowait(
                SimpleNamespace(type=aiohttp.WSMsgType.TEXT, json=lambda event=event: event)
            )

    async def send_json(self, event: dict[str, object]) -> None:
        self.sent.append(event)

    async def receive(self) -> object:
        return await self.messages.get()

    async def close(self, *, code: int = 1000) -> None:
        self.closed = True
        self.close_code = code

    def exception(self) -> None:
        return None


class FakeClientSession:
    def __init__(self, websocket: FakeWebSocket) -> None:
        self.websocket = websocket

    async def __aenter__(self) -> "FakeClientSession":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def ws_connect(self, *_: object, **__: object) -> FakeWebSocket:
        return self.websocket


class FakeManualCommitWebSocket:
    """Provider-compatible fake: commit is processed only after response.create."""

    def __init__(
        self,
        transcript: str,
        *,
        stop: threading.Event | None = None,
        output_pcm: bytes = b"\x07\x08" * 100,
        respond_to_wakeup: bool = True,
        internal_output_pcm: bool = False,
    ) -> None:
        self.closed = False
        self.close_code: int | None = None
        self.sent: list[dict[str, object]] = []
        self.transcript = transcript
        self.stop = stop
        self.output_pcm = output_pcm
        self.respond_to_wakeup = respond_to_wakeup
        self.internal_output_pcm = internal_output_pcm
        self._commit_pending = False
        self._response_sequence = 0
        self.messages: asyncio.Queue[object] = asyncio.Queue()
        self._enqueue({"type": "session.updated", "session": {"id": "manual"}})

    def _enqueue(self, event: dict[str, object]) -> None:
        self.messages.put_nowait(
            SimpleNamespace(type=aiohttp.WSMsgType.TEXT, json=lambda: event)
        )

    async def send_json(self, event: dict[str, object]) -> None:
        self.sent.append(event)
        if event["type"] == "input_audio_buffer.commit":
            self._commit_pending = True
            return
        if event["type"] == "response.create" and self._commit_pending:
            if not self.respond_to_wakeup:
                return
            self._commit_pending = False
            self._enqueue(
                {
                    "type": "input_audio_buffer.committed",
                    "event_id": "commit-event",
                    "item_id": "complete-ptt-item",
                }
            )
            self._enqueue(
                {
                    "type": "conversation.item.input_audio_transcription.completed",
                    "event_id": "transcript-event",
                    "item_id": "complete-ptt-item",
                    "transcript": self.transcript,
                }
            )
            self._response_sequence += 1
            response_id = f"manual-r{self._response_sequence}"
            self._enqueue(
                {"type": "response.created", "response": {"id": response_id}}
            )
            response = event.get("response")
            if isinstance(response, dict) and response.get("output_modalities") == [
                "text"
            ]:
                if self.internal_output_pcm:
                    self._enqueue(
                        {
                            "type": "response.output_audio.delta",
                            "response_id": response_id,
                            "delta": base64.b64encode(self.output_pcm).decode("ascii"),
                        }
                    )
                    self._enqueue(
                        {
                            "type": "response.output_audio.done",
                            "response_id": response_id,
                        }
                    )
                self._enqueue(
                    {
                        "type": "response.output_text.done",
                        "response_id": response_id,
                        "text": "INTERNAL WAKEUP",
                    }
                )
                return
            self._enqueue(
                {
                    "type": "response.output_audio.delta",
                    "response_id": response_id,
                    "delta": base64.b64encode(self.output_pcm).decode("ascii"),
                }
            )
            self._enqueue(
                {"type": "response.output_audio.done", "response_id": response_id}
            )
            self._enqueue(
                {
                    "type": "response.output_audio_transcript.done",
                    "event_id": "visible-assistant-event",
                    "item_id": "visible-assistant-item",
                    "response_id": response_id,
                    "transcript": "Видимый ответ.",
                }
            )
            self._enqueue(
                {
                    "type": "response.done",
                    "response": {"id": response_id, "status": "completed"},
                }
            )
        elif event["type"] == "response.cancel":
            response_id = str(event.get("response_id") or "manual-r1")
            self._enqueue(
                {
                    "type": "response.done",
                    "response": {"id": response_id, "status": "cancelled"},
                }
            )
            if self.stop is not None:
                asyncio.get_running_loop().call_later(0.01, self.stop.set)

    async def receive(self) -> object:
        return await self.messages.get()

    async def close(self, *, code: int = 1000) -> None:
        self.closed = True
        self.close_code = code

    def exception(self) -> None:
        return None


class FakeManualClientSession(FakeClientSession):
    websocket: FakeManualCommitWebSocket

    async def ws_connect(self, *_: object, **__: object) -> FakeManualCommitWebSocket:
        return self.websocket


def test_provider_session_is_portaudio_free_and_preserves_pcm_and_response_lifecycle(
    monkeypatch,
) -> None:  # noqa: ANN001
    input_pcm = b"\x01\x02" * 882
    output_pcm = b"\x03\x04" * 882
    websocket = FakeWebSocket(output_pcm)
    monkeypatch.setattr(aiohttp, "ClientSession", lambda **_: FakeClientSession(websocket))
    stop = threading.Event()
    endpoint = FakeEndpoint(stop, input_pcm)
    diagnostics = FakeDiagnostics()
    result = asyncio.run(
        YandexRealtimeSession(
            "memory-only-api-key",
            "folder",
            endpoint,
            stop,
            diagnostics,
        ).run()
    )
    assert endpoint.started == endpoint.stopped == 1
    assert endpoint.events == [
        ("speech_started", None),
        ("response_started", "r1"),
        ("audio", ("r1", output_pcm)),
        ("audio_done", "r1"),
        ("response_done", ("r1", "completed")),
    ]
    assert websocket.sent[0]["type"] == "session.update"
    appended = [item for item in websocket.sent if item["type"] == "input_audio_buffer.append"]
    assert appended and base64.b64decode(str(appended[0]["audio"])) == input_pcm
    assert result.clean_close and result.close_code == 1000
    first_audio = [fields for event, fields in diagnostics.events if event == "response_first_audio"]
    assert len(first_audio) == 1
    assert first_audio[0]["turn_id"] == "turn_001"
    assert first_audio[0]["response_id"] == "r1"
    source = inspect.getsource(__import__("orion.yandex_realtime_session", fromlist=["*"]))
    assert "import sounddevice" not in source
    assert "orion.portaudio" not in source


def test_cancelled_response_status_is_preserved_and_start_stop_start_is_clean(monkeypatch) -> None:  # noqa: ANN001
    for _ in range(2):
        websocket = FakeWebSocket(b"\0\0", status="cancelled")
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_: FakeClientSession(websocket))
        stop = threading.Event()
        endpoint = FakeEndpoint(stop, bytes(1764))
        asyncio.run(
            YandexRealtimeSession("secret", "folder", endpoint, stop, FakeDiagnostics()).run()
        )
        assert ("response_done", ("r1", "cancelled")) in endpoint.events
        assert websocket.close_code == 1000


def test_yandex_final_provider_transcripts_enter_only_active_test_evidence(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    monkeypatch.setattr(yandex_session_module, "realtime_test_evidence", recorder)
    recorder.start(provider="yandex", transport="srs")
    websocket = FakeWebSocket(b"\0\0")
    monkeypatch.setattr(aiohttp, "ClientSession", lambda **_: FakeClientSession(websocket))
    stop = threading.Event()
    asyncio.run(
        YandexRealtimeSession(
            "memory-only-secret",
            "folder",
            FakeEndpoint(stop, bytes(1764)),
            stop,
            FakeDiagnostics(),
        ).run()
    )
    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        events = [
            json.loads(line)
            for line in archive.read("events.jsonl").decode("utf-8").splitlines()
        ]
    assert [(event["event"], event["transcript"]) for event in events] == [
        ("user_transcript", "Какая у меня скорость?"),
        ("assistant_transcript", "Скорость отображается в узлах."),
    ]
    assert events[0]["turn_id"] == events[1]["turn_id"] == "turn_001"
    assert events[0]["event_id"] == "event-user"
    assert events[1]["response_id"] == "r1"


def test_live_golden_hook_cancels_provider_response_and_forwards_final_transcript(
    monkeypatch,
) -> None:  # noqa: ANN001
    websocket = FakeWebSocket(b"\x05\x06" * 100)
    monkeypatch.setattr(aiohttp, "ClientSession", lambda **_: FakeClientSession(websocket))
    stop = threading.Event()
    endpoint = FakeEndpoint(stop, bytes(1764))
    received: list[tuple[object, ...]] = []
    asyncio.run(
        YandexRealtimeSession(
            "memory-only-secret",
            "folder",
            endpoint,
            stop,
            FakeDiagnostics(),
            on_final_user_transcript=lambda *values: received.append(values),
            suppress_provider_responses=lambda: True,
        ).run()
    )
    assert received and received[0][:4] == (
        "Какая у меня скорость?",
        "turn_001",
        "event-user",
        "item-user",
    )
    cancellations = [item for item in websocket.sent if item["type"] == "response.cancel"]
    assert cancellations == [{"type": "response.cancel", "response_id": "r1"}]


def test_live_golden_manual_ptt_commit_delivers_one_complete_utterance(
    monkeypatch,
) -> None:  # noqa: ANN001
    expected = "Добрый день! Разрешите взлёт."
    stop = threading.Event()
    websocket = FakeManualCommitWebSocket(expected, stop=stop)
    monkeypatch.setattr(
        aiohttp,
        "ClientSession",
        lambda **_: FakeManualClientSession(websocket),
    )
    endpoint = FakeEndpoint(stop, b"\x01\x02" * 400)
    endpoint.inputs.extend(
        (
            bytes(1764 * 25),  # A natural 500 ms pause inside the held PTT.
            b"\x03\x04" * 800,
            RealtimeInputCommit(),
        )
    )
    received: list[tuple[object, ...]] = []

    def accept(*values: object) -> None:
        received.append(values)

    diagnostics = FakeDiagnostics()
    asyncio.run(
        YandexRealtimeSession(
            "memory-only-secret",
            "folder",
            endpoint,
            stop,
            diagnostics,
            on_final_user_transcript=accept,
            suppress_provider_responses=lambda: True,
            manual_input_commit=True,
        ).run()
    )

    assert len(received) == 1
    assert received[0][:4] == (
        expected,
        "turn_001",
        "transcript-event",
        "complete-ptt-item",
    )
    assert received[0][4] is not None
    session_updates = [
        event for event in websocket.sent if event["type"] == "session.update"
    ]
    assert session_updates
    session = session_updates[0]["session"]
    assert isinstance(session, dict)
    audio = session["audio"]
    assert isinstance(audio, dict)
    assert audio["input"]["turn_detection"] is None
    assert [event["type"] for event in websocket.sent].count(
        "input_audio_buffer.commit"
    ) == 1
    input_events = [
        event
        for event in websocket.sent
        if event["type"]
        in {"input_audio_buffer.append", "input_audio_buffer.commit"}
    ]
    assert [event["type"] for event in input_events] == [
        "input_audio_buffer.append",
        "input_audio_buffer.append",
        "input_audio_buffer.append",
        "input_audio_buffer.commit",
    ]
    creates = [event for event in websocket.sent if event["type"] == "response.create"]
    assert len(creates) == 1
    wakeup = creates[0]["response"]
    assert isinstance(wakeup, dict)
    assert wakeup["output_modalities"] == ["text"]
    assert wakeup["max_output_tokens"] == 1
    assert [event["type"] for event in websocket.sent].count("response.cancel") == 1
    assert not any(event == "audio" for event, _ in endpoint.events)
    assert not any(event == "response_started" for event, _ in endpoint.events)
    diagnostic_names = [event for event, _ in diagnostics.events]
    assert "provider_wakeup_create_requested" in diagnostic_names
    assert "input_audio_buffer.committed" in diagnostic_names
    assert "transcription_completed" in diagnostic_names
    assert "provider_wakeup_response_created" in diagnostic_names
    assert "provider_wakeup_cancel_requested" in diagnostic_names
    assert "provider_wakeup_response_ignored" in diagnostic_names
    assert "provider_wakeup_text_ignored" in diagnostic_names
    assert "provider_wakeup_response_done" in diagnostic_names


def test_manual_ptt_commit_preserves_ordinary_yandex_response_creation(
    monkeypatch,
) -> None:  # noqa: ANN001
    stop = threading.Event()
    output_pcm = b"\x09\x0a" * 120
    websocket = FakeManualCommitWebSocket(
        "Обычный запрос", stop=stop, output_pcm=output_pcm
    )
    monkeypatch.setattr(
        aiohttp,
        "ClientSession",
        lambda **_: FakeManualClientSession(websocket),
    )
    endpoint = FakeEndpoint(stop, bytes(1764))
    endpoint.inputs.append(RealtimeInputCommit())

    asyncio.run(
        YandexRealtimeSession(
            "memory-only-secret",
            "folder",
            endpoint,
            stop,
            FakeDiagnostics(),
            manual_input_commit=True,
        ).run()
    )

    creates = [event for event in websocket.sent if event["type"] == "response.create"]
    assert creates == [{"type": "response.create"}]
    assert endpoint.events.count(("audio", ("manual-r1", output_pcm))) == 1
    assert ("response_done", ("manual-r1", "completed")) in endpoint.events


def test_provider_compatibility_fake_requires_response_create_after_commit() -> None:
    async def exercise() -> None:
        websocket = FakeManualCommitWebSocket("Полная фраза")
        await websocket.messages.get()  # session.updated
        await websocket.send_json({"type": "input_audio_buffer.commit"})
        assert websocket.messages.empty()
        await websocket.send_json(
            {
                "type": "response.create",
                "response": {"output_modalities": ["text"]},
            }
        )
        first = (await websocket.messages.get()).json()
        second = (await websocket.messages.get()).json()
        assert first["type"] == "input_audio_buffer.committed"
        assert second["type"] == "conversation.item.input_audio_transcription.completed"

    asyncio.run(exercise())


def test_live_golden_wakeup_provider_pcm_is_fail_closed_before_srs(
    monkeypatch,
) -> None:  # noqa: ANN001
    stop = threading.Event()
    output_pcm = b"\x0b\x0c" * 80
    websocket = FakeManualCommitWebSocket(
        "Добрый день! Разрешите взлёт.",
        stop=stop,
        output_pcm=output_pcm,
        internal_output_pcm=True,
    )
    monkeypatch.setattr(
        aiohttp,
        "ClientSession",
        lambda **_: FakeManualClientSession(websocket),
    )
    endpoint = FakeEndpoint(stop, bytes(1764))
    endpoint.inputs.append(RealtimeInputCommit())
    diagnostics = FakeDiagnostics()

    asyncio.run(
        YandexRealtimeSession(
            "memory-only-secret",
            "folder",
            endpoint,
            stop,
            diagnostics,
            suppress_provider_responses=lambda: True,
            manual_input_commit=True,
        ).run()
    )

    assert not any(event == "audio" for event, _ in endpoint.events)
    generated = [
        fields
        for event, fields in diagnostics.events
        if event == "provider_wakeup_pcm_generated"
    ]
    assert generated == [
        {
            "response_id": "manual-r1",
            "byte_count": len(output_pcm),
            "provider_media_generated": True,
            "provider_media_reached_transport": False,
        }
    ]


def test_manual_commit_wakeup_timeout_fails_closed(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        yandex_session_module,
        "_MANUAL_COMMIT_WAKEUP_TIMEOUT_SECONDS",
        0.01,
    )
    stop = threading.Event()
    websocket = FakeManualCommitWebSocket(
        "Не будет получено",
        stop=stop,
        respond_to_wakeup=False,
    )
    monkeypatch.setattr(
        aiohttp,
        "ClientSession",
        lambda **_: FakeManualClientSession(websocket),
    )
    endpoint = FakeEndpoint(stop, bytes(1764))
    endpoint.inputs.append(RealtimeInputCommit())

    with pytest.raises(
        TimeoutError,
        match="Timed out waiting for Yandex manual input transcription",
    ):
        asyncio.run(
            YandexRealtimeSession(
                "memory-only-secret",
                "folder",
                endpoint,
                stop,
                FakeDiagnostics(),
                manual_input_commit=True,
            ).run()
        )
