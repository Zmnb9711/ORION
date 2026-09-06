import asyncio
import ast
import base64
from dataclasses import FrozenInstanceError
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import aiohttp
import pytest
from aiohttp import web

from orion import yandex_stt_adapter as stt

TURN = UUID(int=37)
PHRASE = "Какой мой текущий курс и координаты?"


@pytest.mark.parametrize("peer", ["local_close", "remote_close", "no_close_ack"])
def test_real_aiohttp_local_close_after_settle_no_receive_poison(monkeypatch, peer):
    """Loopback only: exercise actual aiohttp cancellation/close semantics."""

    async def run():
        release_peer = asyncio.Event()
        if peer == "no_close_ack":
            monkeypatch.setattr(stt, "_CLOSE_TIMEOUT_S", 0.02)
        sockets = []
        clients = []
        original_connect = aiohttp.ClientSession.ws_connect

        async def connect(client, *args, **kwargs):
            socket = await original_connect(client, *args, **kwargs)
            clients.append(client)
            sockets.append(socket)
            return socket

        monkeypatch.setattr(aiohttp.ClientSession, "ws_connect", connect)

        async def handler(request):
            socket = web.WebSocketResponse()
            await socket.prepare(request)
            async for message in socket:
                event = message.json()
                if event["type"] == "session.update":
                    await socket.send_json({"type": "session.updated"})
                elif event["type"] == "input_audio_buffer.append":
                    await socket.send_json(final())
                    if peer == "remote_close":
                        await socket.close(code=1000)
                    elif peer == "no_close_ack":
                        await release_peer.wait()
            return socket

        app = web.Application()
        app.router.add_get("/", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        try:
            adapter = stt.YandexRealtimeSttAdapter("test", "folder")
            adapter._url = f"http://127.0.0.1:{runner.addresses[0][1]}/"
            result = await adapter.transcribe(bytes(2), TURN)
            assert clients[0].closed and sockets[0].closed
            expected_code = 1006 if peer == "no_close_ack" else 1000
            assert sockets[0].close_code == expected_code, (
                f"receive cancellation poisoned close code: {sockets[0].close_code}"
            )
            assert result.transcript is not None and result.session_closed_cleanly
            assert adapter._active is None
            assert await adapter.shutdown()
        finally:
            release_peer.set()
            await runner.cleanup()

    asyncio.run(run())


def final(text: object = PHRASE, item: object = "input-one"):
    return {"type": stt.FINAL_INPUT_EVENT, "transcript": text, "item_id": item}


class Socket:
    def __init__(self, events=(), block_phase=None):
        self.events = asyncio.Queue()
        self.events.put_nowait(
            {"type": "session.updated", "session": {"id": "session"}}
        )
        for event in events:
            self.events.put_nowait(event)
        self.sent = []
        self.closed = False
        self.close_code = None
        self.block_phase = block_phase
        self.entered = asyncio.Event()

    async def send_json(self, event):
        if (self.block_phase == "setup" and event["type"] == "session.update") or (
            self.block_phase == "audio" and event["type"] == "input_audio_buffer.append"
        ):
            self.entered.set()
            await asyncio.Event().wait()
        self.sent.append(event)

    async def receive(self):
        if self.events.empty():
            self.entered.set()
        event = await self.events.get()
        if isinstance(event, Exception):
            raise event
        if isinstance(event, SimpleNamespace):
            self.closed = True
            self.close_code = event.data
            return event
        return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(event))

    async def close(self, code):
        if self.block_phase == "close":
            await asyncio.Event().wait()
        self.closed, self.close_code = True, code


class Client:
    def __init__(self, socket, block_connect=False, error=None):
        self.socket = socket
        self.block_connect = block_connect
        self.error = error
        self.closed = False
        self.connections = []
        self.entered = asyncio.Event()

    async def ws_connect(self, url, **kwargs):
        self.connections.append((url, kwargs))
        self.entered.set()
        if self.error:
            raise self.error
        if self.block_connect:
            await asyncio.Event().wait()
        return self.socket

    async def close(self):
        self.closed = True


def setup(monkeypatch, events=(), *, block=None, deadline=0.5, error=None):
    socket = Socket(events, block)
    client = Client(socket, block == "connection", error)
    creations = []

    def factory(**kwargs):
        creations.append(kwargs)
        return client

    monkeypatch.setattr(aiohttp, "ClientSession", factory)
    return (
        stt.YandexRealtimeSttAdapter("SECRET_API_KEY", "folder", deadline_s=deadline),
        socket,
        client,
        creations,
    )


def test_true_input_final_only_exact_audio_correlation_immutable_private(monkeypatch):
    async def run():
        events = [
            {"type": stt.PARTIAL_INPUT_EVENT, "delta": "partial SECRET"},
            {"type": "response.output_text.done", "text": "assistant SECRET"},
            {"type": "response.output_audio.delta", "delta": "not-even-base64"},
            {"type": "response.function_call_arguments.done", "name": "execute_tool"},
            {
                "type": "conversation.item.created",
                "item": {"role": "assistant", "text": "SECRET"},
            },
            final("  " + PHRASE + "  "),
            final("  " + PHRASE + "  "),
        ]
        adapter, ws, client, creations = setup(monkeypatch, events)
        source = bytearray(bytes(4410))
        result = await adapter.transcribe(source, TURN)
        assert result.failure is None and result.session_closed_cleanly
        transcript = result.transcript
        assert transcript is not None and transcript.text == "  " + PHRASE + "  "
        assert transcript.interaction_id == TURN and transcript.final
        assert (
            transcript.input_language == "ru-RU"
            and transcript.provider_item_id == "input-one"
        )
        with pytest.raises(FrozenInstanceError):
            transcript.text = "rewrite"  # type: ignore[misc]
        assert transcript.started_at <= transcript.finalized_at
        chunks = [e for e in ws.sent if e["type"] == "input_audio_buffer.append"]
        assert b"".join(base64.b64decode(e["audio"]) for e in chunks) == source
        assert len(creations) == len(client.connections) == 1
        config = ws.sent[0]["session"]
        assert config["audio"]["input"]["languages"] == ["ru-RU"]
        assert config["audio"]["input"]["format"]["rate"] == 44100
        assert "tools" not in config and "FlightContext" not in json.dumps(config)
        assert {e["type"] for e in ws.sent} == {
            "session.update",
            "input_audio_buffer.append",
        }
        diagnostics = json.dumps(adapter.diagnostics()) + repr(result)
        assert "SECRET" not in diagnostics and PHRASE not in diagnostics
        assert ws.closed and client.closed
        assert sum(e["category"] == "completed" for e in adapter.diagnostics()) == 1
        assert await adapter.shutdown()

    asyncio.run(run())


@pytest.mark.parametrize(
    "audio,expected",
    [
        (b"", stt.SttFailure.INVALID_AUDIO),
        (b"x", stt.SttFailure.INVALID_AUDIO),
        (bytes(stt.MAX_PCM_BYTES + 2), stt.SttFailure.AUDIO_TOO_LARGE),
        ("not PCM", stt.SttFailure.INVALID_AUDIO),
    ],
    ids=["empty", "odd", "over-limit", "wrong-type"],
)
def test_audio_validation_before_network(monkeypatch, audio, expected):
    async def run():
        adapter, _, _, creations = setup(monkeypatch)
        assert (await adapter.transcribe(audio, TURN)).failure == expected
        assert not creations

    asyncio.run(run())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sample_rate_hz": 48000},
        {"channels": 2},
        {"sample_width_bytes": 4},
        {"input_language": "en-US"},
    ],
)
def test_format_and_language_never_converted(monkeypatch, kwargs):
    async def run():
        adapter, _, _, creations = setup(monkeypatch)
        result = await adapter.transcribe(bytes(100), TURN, **kwargs)
        assert result.failure in {
            stt.SttFailure.INVALID_AUDIO,
            stt.SttFailure.UNSUPPORTED_LANGUAGE,
        }
        assert not creations

    asyncio.run(run())


def test_max_pcm_boundary_and_memoryview_no_truncation(monkeypatch):
    async def run():
        adapter, ws, _, _ = setup(monkeypatch, [final()], deadline=2)
        result = await adapter.transcribe(memoryview(bytes(stt.MAX_PCM_BYTES)), TURN)
        assert result.transcript is not None
        assert (
            sum(len(base64.b64decode(e["audio"])) for e in ws.sent[1:])
            == stt.MAX_PCM_BYTES
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "events,expected",
    [
        ([final("")], stt.SttFailure.EMPTY_FINAL_TRANSCRIPT),
        ([final("  \n ")], stt.SttFailure.EMPTY_FINAL_TRANSCRIPT),
        ([final("x" * 4001)], stt.SttFailure.TRANSCRIPT_TOO_LARGE),
        ([final(), final("conflicting")], stt.SttFailure.CONFLICTING_FINAL_TRANSCRIPT),
        (
            [final(), final(item="second-input")],
            stt.SttFailure.CONFLICTING_FINAL_TRANSCRIPT,
        ),
        ([final(123)], stt.SttFailure.PROVIDER_ERROR),
        (
            [
                {
                    "type": "conversation.item.input_audio_transcription.failed",
                    "error": "SECRET",
                }
            ],
            stt.SttFailure.PROVIDER_ERROR,
        ),
        (
            [{"type": "error", "error": {"code": "unauthorized", "message": "SECRET"}}],
            stt.SttFailure.AUTH_ERROR,
        ),
        (
            [{"type": "error", "error": {"code": "invalid_argument"}}],
            stt.SttFailure.PROVIDER_REJECTED,
        ),
        (
            [{"type": "error", "error": {"message": "SECRET"}}],
            stt.SttFailure.PROVIDER_ERROR,
        ),
    ],
    ids=[
        "empty",
        "whitespace",
        "too-long",
        "conflict",
        "two-items",
        "malformed",
        "failed",
        "auth",
        "rejected",
        "error",
    ],
)
def test_final_and_provider_failures(monkeypatch, events, expected):
    async def run():
        adapter, ws, client, _ = setup(monkeypatch, events)
        result = await adapter.transcribe(bytes(100), TURN)
        assert result.transcript is None and result.failure == expected
        assert ws.closed and client.closed and len(client.connections) == 1
        assert "SECRET" not in repr(result) + json.dumps(adapter.diagnostics())

    asyncio.run(run())


def test_no_final_deadline_never_promotes_partial_or_assistant(monkeypatch):
    async def run():
        adapter, ws, client, _ = setup(
            monkeypatch,
            [
                {"type": stt.PARTIAL_INPUT_EVENT, "delta": PHRASE},
                {"type": "response.output_text.done", "text": PHRASE},
                {"type": "input_audio_buffer.speech_stopped"},
            ],
            deadline=0.02,
        )
        result = await adapter.transcribe(bytes(100), TURN)
        assert result.failure == stt.SttFailure.FINAL_TRANSCRIPT_TIMEOUT
        assert result.transcript is None and ws.closed and client.closed

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["connection", "setup", "audio", "final"])
@pytest.mark.parametrize("signal", ["event", "task"])
def test_cancel_every_phase_and_late_final(monkeypatch, phase, signal):
    async def run():
        adapter, ws, client, _ = setup(monkeypatch, block=phase)
        cancel = asyncio.Event()
        task = asyncio.create_task(
            adapter.transcribe(bytes(100), TURN, cancellation=cancel)
        )
        await (client.entered.wait() if phase == "connection" else ws.entered.wait())
        if signal == "event":
            cancel.set()
        else:
            task.cancel()
        ws.events.put_nowait(final())
        result = await task
        assert result.failure == stt.SttFailure.CANCELLED and result.transcript is None
        assert client.closed
        if phase != "connection":
            assert ws.closed

    asyncio.run(run())


def test_precancel_and_shutdown_never_connect(monkeypatch):
    async def run():
        adapter, _, _, creations = setup(monkeypatch)
        cancel = asyncio.Event()
        cancel.set()
        assert (
            await adapter.transcribe(bytes(2), TURN, cancellation=cancel)
        ).failure == stt.SttFailure.CANCELLED
        assert await adapter.shutdown()
        assert (
            await adapter.transcribe(bytes(2), TURN)
        ).failure == stt.SttFailure.SHUTTING_DOWN
        assert not creations

    asyncio.run(run())


def test_active_shutdown_and_busy(monkeypatch):
    async def run():
        adapter, ws, client, _ = setup(monkeypatch)
        task = asyncio.create_task(adapter.transcribe(bytes(2), TURN))
        await ws.entered.wait()
        assert (await adapter.transcribe(bytes(2), TURN)).failure == stt.SttFailure.BUSY
        assert await adapter.shutdown()
        assert (await task).failure == stt.SttFailure.CANCELLED
        assert client.closed and ws.closed

    asyncio.run(run())


def test_collector_seals_late_events_and_preserves_optional_item():
    collector = stt._FinalCollector()
    assert not collector.accept({"type": stt.PARTIAL_INPUT_EVENT, "delta": PHRASE})
    assert collector.accept(final(item=None))
    assert not collector.accept(final(item=None))
    collector.sealed = True
    assert not collector.accept(final("late conflict"))
    assert collector.text == PHRASE and collector.item is None


def test_close_is_bounded_and_unclean_close_cannot_pass(monkeypatch):
    async def run():
        monkeypatch.setattr(stt, "_CLOSE_TIMEOUT_S", 0.01)
        adapter, _, client, _ = setup(monkeypatch, [final()], block="close")
        result = await adapter.transcribe(bytes(2), TURN)
        assert result.failure == stt.SttFailure.PROVIDER_ERROR
        assert not result.session_closed_cleanly and client.closed

    asyncio.run(run())


@pytest.mark.parametrize(
    "events", [[{"type": "response.output_text.done", "text": "x" * 262144}], [None]]
)
def test_event_bounds_and_shape(monkeypatch, events):
    async def run():
        adapter, _, client, _ = setup(monkeypatch, events)
        result = await adapter.transcribe(bytes(2), TURN)
        assert result.failure == stt.SttFailure.PROVIDER_ERROR and client.closed

    asyncio.run(run())


def test_isolation_import_and_public_api_boundary():
    tree = ast.parse(Path(stt.__file__).read_text(encoding="utf-8"))
    forbidden = {
        "radio_router",
        "srs_radio_adapter",
        "protected_presentation",
        "phraseology_renderer",
        "response_composer",
        "interaction_router",
        "planner",
        "world_model",
        "tool_gateway",
        "yandex_realtime_session",
    }
    imports = [
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ]
    assert not any(name.split(".")[-1] in forbidden for name in imports)
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"eval", "exec", "__import__"}
        for node in ast.walk(tree)
    )
    for method in (
        stt.YandexRealtimeSttAdapter,
        stt.YandexRealtimeSttAdapter.transcribe,
    ):
        assert not any(
            "callback" in name or "output" in name or "tool" in name
            for name in inspect.signature(method).parameters
        )


def test_cancel_preserves_unclean_close(monkeypatch):
    async def run():
        monkeypatch.setattr(stt, "_CLOSE_TIMEOUT_S", 0.01)
        adapter, ws, client, _ = setup(monkeypatch, block="close")
        cancel = asyncio.Event()
        task = asyncio.create_task(
            adapter.transcribe(bytes(2), TURN, cancellation=cancel)
        )
        await ws.entered.wait()
        cancel.set()
        result = await task
        assert result.failure == stt.SttFailure.CANCELLED
        assert not result.session_closed_cleanly and client.closed

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["connection", "setup", "audio"])
def test_overall_deadline_covers_all_phases(monkeypatch, phase):
    async def run():
        adapter, _, client, creations = setup(monkeypatch, block=phase, deadline=0.01)
        result = await adapter.transcribe(bytes(2), TURN)
        assert result.failure == stt.SttFailure.FINAL_TRANSCRIPT_TIMEOUT
        assert client.closed and len(creations) == 1

    asyncio.run(run())


def test_connection_failure_no_retry_private(monkeypatch):
    async def run():
        adapter, _, client, creations = setup(
            monkeypatch, error=aiohttp.ClientConnectionError("SECRET")
        )
        result = await adapter.transcribe(bytes(2), TURN)
        assert result.failure == stt.SttFailure.CONNECTION_ERROR
        assert client.closed and len(creations) == 1
        assert "SECRET" not in repr(result) + repr(adapter.diagnostics())

    asyncio.run(run())


def test_event_count_bound(monkeypatch):
    async def run():
        adapter, _, client, _ = setup(
            monkeypatch, [{"type": "response.created"}] * 1024
        )
        result = await adapter.transcribe(bytes(2), TURN)
        assert result.failure == stt.SttFailure.PROVIDER_ERROR and client.closed
        assert len(adapter.diagnostics()) <= 128

    asyncio.run(run())


def test_transcript_exact_max_boundary(monkeypatch):
    async def run():
        adapter, _, _, _ = setup(monkeypatch, [final("x" * 4000)])
        result = await adapter.transcribe(bytes(2), TURN)
        assert result.transcript is not None and len(result.transcript.text) == 4000

    asyncio.run(run())


@pytest.mark.parametrize(
    "code,expected",
    [(1000, None), (1001, None), (1006, stt.SttFailure.CONNECTION_ERROR)],
)
def test_final_then_remote_close_precedence(monkeypatch, code, expected):
    async def run():
        adapter, ws, client, _ = setup(
            monkeypatch,
            [final(), SimpleNamespace(type=aiohttp.WSMsgType.CLOSE, data=code)],
        )
        result = await adapter.transcribe(bytes(2), TURN)
        assert result.failure == expected
        assert (result.transcript is not None) == (expected is None)
        assert ws.closed and client.closed and adapter._active is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "events,expected",
    [
        (
            [final(), {"type": "error", "error": {"code": "unauthorized"}}],
            stt.SttFailure.AUTH_ERROR,
        ),
        (
            [final(), {"type": "error", "error": {"code": "invalid_argument"}}],
            stt.SttFailure.PROVIDER_REJECTED,
        ),
        (
            [final(), {"type": "error", "error": {"code": "unknown"}}],
            stt.SttFailure.PROVIDER_ERROR,
        ),
        ([final(), {"type": "session.updated"}], None),
    ],
)
def test_post_final_fatal_vs_noncritical(monkeypatch, events, expected):
    async def run():
        adapter, ws, client, _ = setup(monkeypatch, events)
        result = await adapter.transcribe(bytes(2), TURN)
        assert result.failure == expected and ws.closed and client.closed

    asyncio.run(run())


def test_cancel_during_cleanup_drains_all_owned_tasks(monkeypatch):
    async def run():
        baseline_tasks = asyncio.all_tasks()
        adapter, ws, client, _ = setup(monkeypatch, [final()])
        close_started, release = asyncio.Event(), asyncio.Event()

        async def close(code):
            close_started.set()
            await release.wait()
            ws.closed, ws.close_code = True, code

        ws.close = close
        task = asyncio.create_task(adapter.transcribe(bytes(2), TURN))
        await close_started.wait()
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        result = await task
        assert (
            result.failure == stt.SttFailure.CANCELLED and result.session_closed_cleanly
        )
        assert ws.closed and client.closed and adapter._active is None
        assert asyncio.all_tasks() == baseline_tasks

    asyncio.run(run())


@pytest.mark.parametrize("actually_closed", [True, False])
def test_close_timeout_distinguishes_warning_from_resource_failure(
    monkeypatch, actually_closed
):
    async def run():
        baseline_tasks = asyncio.all_tasks()
        monkeypatch.setattr(stt, "_CLOSE_TIMEOUT_S", 0.01)
        adapter, ws, client, _ = setup(monkeypatch, [final()])

        async def close(code):
            ws.closed, ws.close_code = actually_closed, 1006
            await asyncio.Event().wait()

        ws.close = close
        result = await adapter.transcribe(bytes(2), TURN)
        assert result.session_closed_cleanly == actually_closed
        assert (result.transcript is not None) == actually_closed
        assert client.closed and asyncio.all_tasks() == baseline_tasks
        resource = next(
            e for e in adapter.diagnostics() if e["category"] == "resources_closed"
        )
        assert resource["close_warning"] and resource["receive_task_done"]

    asyncio.run(run())


def test_http_resource_not_closed_is_failure(monkeypatch):
    async def run():
        adapter, ws, client, _ = setup(monkeypatch, [final()])

        async def no_close():
            pass

        client.close = no_close
        result = await adapter.transcribe(bytes(2), TURN)
        assert result.failure == stt.SttFailure.PROVIDER_ERROR
        assert not result.session_closed_cleanly and ws.closed

    asyncio.run(run())


def test_latency_math_and_milestones_not_utterance_duration(monkeypatch):
    marks = dict(
        connection_started=10.0,
        connection_ready=10.2,
        first_audio_sent=10.21,
        last_audio_sent=10.25,
        final_transcript_received=10.6,
        cleanup_started=10.7,
        cleanup_completed=10.8,
    )
    assert stt._latencies(marks) == pytest.approx(
        dict(
            connection_setup_latency_ms=200,
            audio_submission_duration_ms=40,
            stt_finalize_latency_ms=350,
            cleanup_latency_ms=100,
            total_operation_latency_ms=800,
        )
    )

    async def run():
        baseline_tasks = asyncio.all_tasks()
        adapter, _, _, _ = setup(monkeypatch, [final()])
        result = await adapter.transcribe(bytes(2), TURN)
        assert result.transcript is not None
        events = adapter.diagnostics()
        observed = {
            str(e["category"]): float(str(e["monotonic_s"]))
            for e in events
            if e["category"] in marks
        }
        assert set(observed) == set(marks)
        assert list(observed.values()) == sorted(observed.values())
        metrics = next(e for e in events if e["category"] == "latency_metrics")
        for key, value in stt._latencies(observed).items():
            assert metrics[key] == value
        assert asyncio.all_tasks() == baseline_tasks and adapter._active is None

    asyncio.run(run())
