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


class FakeTransportBoundaryWebSocket:
    """Provider-compatible fake: client commit is ignored; VAD consumes silence."""

    def __init__(
        self,
        transcript: str | tuple[str, ...],
        *,
        stop: threading.Event | None = None,
        output_pcm: bytes = b"\x07\x08" * 100,
        respond_to_vad: bool = True,
        internal_output_pcm: bool = False,
    ) -> None:
        self.closed = False
        self.close_code: int | None = None
        self.sent: list[dict[str, object]] = []
        self.transcripts = (transcript,) if isinstance(transcript, str) else transcript
        self.stop = stop
        self.output_pcm = output_pcm
        self.respond_to_vad = respond_to_vad
        self.internal_output_pcm = internal_output_pcm
        self._segment_index = 0
        self._speech_active = False
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
            # This is the behavior observed from the real Yandex backend: the
            # documented client commit receives no acknowledgement or transcript.
            return
        if event["type"] == "input_audio_buffer.append":
            audio = base64.b64decode(str(event.get("audio") or ""))
            is_silence = bool(audio) and not any(audio)
            if not is_silence:
                if not self._speech_active:
                    self._speech_active = True
                    self._enqueue({"type": "input_audio_buffer.speech_started"})
                return
            if not self.respond_to_vad:
                return
            if not self._speech_active or self._segment_index >= len(self.transcripts):
                return
            self._speech_active = False
            self._enqueue({"type": "input_audio_buffer.speech_stopped"})
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
                    "event_id": f"transcript-event-{self._segment_index + 1}",
                    "item_id": f"ptt-item-{self._segment_index + 1}",
                    "transcript": self.transcripts[self._segment_index],
                }
            )
            self._segment_index += 1
            self._response_sequence += 1
            response_id = f"manual-r{self._response_sequence}"
            self._enqueue(
                {"type": "response.created", "response": {"id": response_id}}
            )
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
            # The real provider can continue producing media after cancellation.
            # Its already queued response remains deliberately intact here.
            if self.stop is not None and self._segment_index >= len(self.transcripts):
                asyncio.get_running_loop().call_later(0.05, self.stop.set)

    async def receive(self) -> object:
        return await self.messages.get()

    async def close(self, *, code: int = 1000) -> None:
        self.closed = True
        self.close_code = code

    def exception(self) -> None:
        return None


class FakeManualClientSession(FakeClientSession):
    websocket: FakeTransportBoundaryWebSocket

    async def ws_connect(self, *_: object, **__: object) -> FakeTransportBoundaryWebSocket:
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

    def accept(*values: object) -> None:
        received.append(values)
        asyncio.get_running_loop().call_later(0.01, stop.set)

    asyncio.run(
        YandexRealtimeSession(
            "memory-only-secret",
            "folder",
            endpoint,
            stop,
            FakeDiagnostics(),
            on_final_user_transcript=accept,
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
    websocket = FakeTransportBoundaryWebSocket(
        ("Добрый день!", "Разрешите взлёт."), stop=stop
    )
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
        "transcript-event-2",
        "ptt-item-2",
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
    assert audio["input"]["turn_detection"] == {
        "type": "server_vad",
        "threshold": 0.5,
        "silence_duration_ms": 400,
    }
    assert [event["type"] for event in websocket.sent].count(
        "input_audio_buffer.commit"
    ) == 0
    input_events = [
        event
        for event in websocket.sent
        if event["type"] == "input_audio_buffer.append"
    ]
    assert len(input_events) >= 4
    assert not any(base64.b64decode(str(input_events[-1]["audio"])))
    creates = [event for event in websocket.sent if event["type"] == "response.create"]
    assert creates == []
    assert [event["type"] for event in websocket.sent].count("response.cancel") == 2
    assert not any(event == "audio" for event, _ in endpoint.events)
    assert not any(event == "response_started" for event, _ in endpoint.events)
    diagnostic_names = [event for event, _ in diagnostics.events]
    assert "provider_vad_flush_requested" in diagnostic_names
    assert "input_audio_buffer.committed" in diagnostic_names
    assert diagnostic_names.count("transcription_segment_completed") == 2
    assert "transcription_completed" in diagnostic_names
    assert diagnostic_names.count("provider_response_suppressed") == 2
    assert "provider_suppressed_text_ignored" in diagnostic_names
    assert "provider_suppressed_response_done" in diagnostic_names


def test_manual_ptt_commit_preserves_ordinary_yandex_response_creation(
    monkeypatch,
) -> None:  # noqa: ANN001
    stop = threading.Event()
    output_pcm = b"\x09\x0a" * 120
    websocket = FakeTransportBoundaryWebSocket(
        "Обычный запрос", stop=stop, output_pcm=output_pcm
    )
    monkeypatch.setattr(
        aiohttp,
        "ClientSession",
        lambda **_: FakeManualClientSession(websocket),
    )
    endpoint = FakeEndpoint(stop, b"\x01\x02" * 882)
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
    assert creates == []
    assert endpoint.events.count(("audio", ("manual-r1", output_pcm))) == 1
    assert ("response_done", ("manual-r1", "completed")) in endpoint.events


def test_provider_compatibility_fake_ignores_client_commit_and_uses_vad_tail() -> None:
    async def exercise() -> None:
        websocket = FakeTransportBoundaryWebSocket("Полная фраза")
        await websocket.messages.get()  # session.updated
        await websocket.send_json(
            {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(b"\x01\x02" * 100).decode("ascii"),
            }
        )
        assert (await websocket.messages.get()).json()["type"] == (
            "input_audio_buffer.speech_started"
        )
        await websocket.send_json({"type": "input_audio_buffer.commit"})
        assert websocket.messages.empty()
        await websocket.send_json({"type": "response.create"})
        assert websocket.messages.empty()
        await websocket.send_json(
            {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(bytes(1764)).decode("ascii"),
            }
        )
        first = (await websocket.messages.get()).json()
        second = (await websocket.messages.get()).json()
        third = (await websocket.messages.get()).json()
        assert first["type"] == "input_audio_buffer.speech_stopped"
        assert second["type"] == "input_audio_buffer.committed"
        assert third["type"] == "conversation.item.input_audio_transcription.completed"

    asyncio.run(exercise())


def test_live_golden_server_vad_response_pcm_is_fail_closed_before_srs(
    monkeypatch,
) -> None:  # noqa: ANN001
    stop = threading.Event()
    output_pcm = b"\x0b\x0c" * 80
    websocket = FakeTransportBoundaryWebSocket(
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
    endpoint = FakeEndpoint(stop, b"\x01\x02" * 882)
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
        if event == "provider_suppressed_pcm_generated"
    ]
    assert generated == [
        {
            "response_id": "manual-r1",
            "byte_count": len(output_pcm),
            "provider_media_generated": True,
            "provider_media_reached_transport": False,
        }
    ]


def test_ptt_transcript_finalization_timeout_fails_closed(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        yandex_session_module,
        "_PTT_TRANSCRIPTION_TIMEOUT_SECONDS",
        0.01,
    )
    stop = threading.Event()
    websocket = FakeTransportBoundaryWebSocket(
        "Не будет получено",
        stop=stop,
        respond_to_vad=False,
    )
    monkeypatch.setattr(
        aiohttp,
        "ClientSession",
        lambda **_: FakeManualClientSession(websocket),
    )
    endpoint = FakeEndpoint(stop, b"\x01\x02" * 882)
    endpoint.inputs.append(RealtimeInputCommit())

    with pytest.raises(
        TimeoutError,
        match="Timed out waiting for Yandex PTT transcript finalization",
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
