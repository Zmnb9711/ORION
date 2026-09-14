"""Normal service: real route/Core/presentation/RadioRouter, fake physical I/O."""
import asyncio
from datetime import datetime
import json
import queue
import threading
from types import SimpleNamespace as NS
import zipfile

import pytest

import orion.full_voice_service as host
from orion.conversational_core import parse_draft
from orion.full_voice_core import FullVoiceCore
from orion.hybrid_aircraft_core import HybridAircraftCore
from orion.informational_presentation import InformationalPresentation
from orion.radio_router import RadioRouter
from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter
from test_general_semantic import SemanticWire
from test_interaction_router import gateway as registered_gateway
from orion.yandex_srs_live_core import YandexSrsStartRequest
from test_conversation_prerequisites import SOCIAL
from test_free_conversation_policy import FIFTH_RAW
from test_full_voice import StreamingFakeRadio
from test_hybrid_aircraft import PURE, MIXED, FREE, NOW, Gateway, utterance
from test_conversation_stt_routing import STT_FINALS


@pytest.mark.parametrize("mode", ["success", "provider_failure", "invalid_candidate", "tts_failure",
    "observer_failure", "inactive", "stop_provider"])
@pytest.mark.parametrize("source", [SOCIAL[0], *STT_FINALS[:5]])
def test_normal_host_conversation_then_core_no_fallback(monkeypatch, tmp_path, mode, source):
    inputs = [utterance(source), utterance(SOCIAL[1]), utterance(PURE)]
    stop, first = threading.Event(), threading.Event()
    adapter = StreamingFakeRadio(first)
    router = RadioRouter(default_transport_id="srs")
    router.register_adapter(adapter)
    router.start()
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    if mode != "inactive": recorder.start(provider="yandex", transport="srs", build_sha="f"*40)
    if mode == "observer_failure":
        def broken(*a, **k): raise PermissionError("fixture")
        monkeypatch.setattr(recorder, "record_conversation_slice", broken)
    gateway = Gateway()
    monkeypatch.setattr(gateway, 'definitions', lambda: registered_gateway().definitions(), raising=False)
    transports, texts, owners, released = [], [], [], []
    answer_text = parse_draft(FIFTH_RAW).text

    class Native:
        owner = future = None
        def __init__(self, *a, **k): pass
        async def open(self, key): pass
        def start(self, identity, at):
            self.owner = identity
            self.future = asyncio.get_running_loop().create_future()
        async def end(self, identity, at):
            self.future.set_result(next(u for u in inputs if u.interaction_id == identity))
        async def result(self): return await self.future
        def release(self, identity): self.owner = self.future = None
        async def close(self): pass

    class Endpoint:
        tx_frames = packet_id = 0
        tx_marks = {}
        def __init__(self, *a):
            self.radio_router = router
            self.turn_events = queue.Queue()
            self.enqueue(inputs[0])
        def enqueue(self, u):
            for kind in (host.RadioTurnEventKind.START, host.RadioTurnEventKind.END):
                self.turn_events.put(NS(kind=kind, identity=u.interaction_id, timestamp=1.0))
        def connect_radio(self): pass
        def start(self): pass
        def arm_physical_capture(self): pass
        def srs_adapter_runtime(self): return NS(bot_name="ORION", coalition=2)
        def failure(self): return None
        def release_turn(self, identity):
            released.append(identity)
            if len(released) < len(inputs): self.enqueue(inputs[len(released)])
            else: stop.set()
        def stop(self): router.shutdown()

    class Configured:
        @classmethod
        def configured(cls, *a, **k):
            def factory():
                body = json.dumps({"kind": "DIALOGUE", "text": answer_text})
                if mode == "invalid_candidate": body = '{"kind":"INVALID_FIXTURE"}'
                class Wire(SemanticWire):
                    async def send(self, value):
                        if value['type'] == 'response.create':
                            if mode == 'provider_failure': raise OSError('fixture_provider')
                            if mode == 'stop_provider':
                                stop.set()
                                return  # Cancellation interrupts the pending receive.
                        await super().send(value)
                fake = Wire(body)
                transports.append(fake)
                return fake
            owner = WarmYandexAircraftInterpreter(factory, **k)
            owners.append(owner)
            return owner

    class Hybrid(HybridAircraftCore):
        def __init__(self, g, _factory, **kw):
            def forbidden(): raise AssertionError("Conversation must never escalate to Planner")
            super().__init__(g, forbidden, clock=lambda: NOW, **kw)
    class Info(InformationalPresentation):
        def __init__(self, *a, **k): super().__init__(*a, clock=lambda: NOW, **k)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return NOW
    async def tts(self, text):
        self._requests(text)
        texts.append(text)
        if mode == "tts_failure" and text == answer_text: raise RuntimeError("fixture")
        yield bytes(48000)

    monkeypatch.setattr(host, "datetime", Clock)
    from orion.interaction_router import InteractionRouter
    monkeypatch.setattr(host, "InteractionRouter", lambda **kw: InteractionRouter(clock=lambda: NOW, **kw))
    import orion.yandex_warm_aircraft_interpreter as warm
    monkeypatch.setattr(warm, "datetime", Clock)
    monkeypatch.setattr(host, "NativeSpeechKitTurns", Native)
    monkeypatch.setattr(host, "GrpcSpeechKitStreamingPort", lambda: None)
    monkeypatch.setattr(host, "SrsTransportDiagnostics", lambda *a, **k: None)
    monkeypatch.setattr(host, "build_tool_gateway", lambda **k: gateway)
    monkeypatch.setattr(host, "FullVoiceCore", lambda g: FullVoiceCore(g, clock=lambda: NOW))
    monkeypatch.setattr(host, "HybridAircraftCore", Hybrid)
    monkeypatch.setattr(host, "InformationalPresentation", Info)
    monkeypatch.setattr(host, "WarmYandexAircraftInterpreter", Configured)
    monkeypatch.setattr(host, "realtime_test_evidence", recorder)
    monkeypatch.setattr(host.ProtectedStreamingTts, "stream", tts)
    service = host.FullVoiceService(endpoint_factory=Endpoint)
    request = YandexSrsStartRequest(api_key="fixture", folder_id="fixture", eam_password="fixture")
    try:
        asyncio.run(asyncio.wait_for(service._voice(request, "conversation-host", stop), 4))
        assert service.status().state != "error"
        assert all(not v.owned and v.state == 'stopped' for v in owners)
        assert all(f.closed == 1 for f in transports)
        if mode == "stop_provider":
            assert not texts and not adapter.transmit_calls and not gateway.calls
            return
        assert released == [u.interaction_id for u in inputs]
        assert len(owners) == 1 and owners[0].operation_count == 2
        assert len(gateway.calls) == 1  # Third turn ONLY, authoritative aircraft.
        assert texts[-1] == "Вы находитесь в F/A-18C Hornet."
        success = mode not in {"provider_failure", "invalid_candidate", "tts_failure"}
        # Existing streaming transport admits a stream before its first PCM.
        # TTS failure must send zero audio, not require different radio admission.
        assert len(adapter.transmit_calls) == 3
        if mode == "tts_failure":
            assert all(r.audio.stream.high_water == 0 for r in adapter.transmit_calls[:2])
        assert len(texts) == 3  # General failure has an existing truthful response.
        if success: assert texts[:2] == [answer_text, answer_text]
        if mode == "inactive": assert not recorder._events
        elif mode not in {"observer_failure"}:
            data = list(recorder._events)
            for u in inputs[:2]:
                turn = [e for e in data if e.get("turn_id") == str(u.interaction_id)]
                route = next(e for e in turn if e.get("route_source") == "GENERAL_SEMANTIC" and "source_text" in e)
                assert route["source_text"] == u.text
                admitted = next(e for e in turn if "semantic_provider_operations" in e)
                assert admitted["planner_operations"] == admitted["core_fact_reads"] == 0
                assert admitted["semantic_provider_operations"] == 1
                assert admitted["separate_conversation_provider_operations"] == 0
                if success:
                    assert next(e["finalized_text"] for e in turn if "finalized_text" in e) == answer_text
                    assert next(e["tts_input"] for e in turn if "tts_input" in e) == answer_text
                    assert any("raw_terminal_text" in e for e in turn)
                    assert any("normalized_candidate" in e for e in turn)
                    assert any(e.get("status") == "completed" and "frames" in e for e in turn)
            core_turn = [e for e in data if e.get("turn_id") == str(inputs[-1].interaction_id)]
            assert not any(e.get("route") == "CONVERSATION" for e in core_turn)
    finally:
        stop.set()
        router.shutdown()


@pytest.mark.parametrize("text", [PURE, MIXED, FREE, "Какой мой текущий курс и координаты?",
    "Как дела? И какой у меня самолёт?", "какой мой текущий вкус или оригинал", "Привет, разрешите взлёт.",
    "Можно взлетать?", "Разрешите посадку.", "Куда мне поворачивать?", "Какую цель атаковать?",
    "Сегодня тяжело летится какой у меня курс?", "Что-то не мой день можно садиться?",
    "Когда впервые полетел F/A-18?", "Что-то сегодня полёт тяжело идёт. Разрешите посадку."])
def test_known_and_unhandled_routes_never_instantiate_conversation(monkeypatch, tmp_path, text):
    from test_hybrid_host import test_gate10_normal_host_coexistence_and_single_owner as run_existing
    def forbidden(*a, **k): raise AssertionError("Conversation entered a known/unsupported route")
    import orion.conversational_presentation as conversation
    monkeypatch.setattr(conversation, "ConversationVoice", forbidden)
    known = text in {PURE, "Какой мой текущий курс и координаты?"}
    # General ingress now truthfully reports its offline provider unavailability;
    # it still must never invoke the old narrow Conversation owner or a tool.
    run_existing(monkeypatch, tmp_path, text, True, 0, "inactive",
        general_kind=None if known else "TRUTHFUL_UNAVAILABLE",
        expected_reads=None if known else 0)


def test_evidence_explicit_bounded_exact_and_existing_export(tmp_path):
    r = RealtimeTestEvidenceRecorder(tmp_path, max_events=3)
    r.record_conversation_slice("terminal_text", realtime_session_id="s", raw_terminal_text=FIFTH_RAW)
    assert not r._events
    r.start(provider="yandex", transport="srs", build_sha="f"*40)
    r.record_conversation_slice("terminal_text", realtime_session_id="s", turn_id="t", raw_terminal_text=FIFTH_RAW,
        headers={"Authorization": "SECRET"}, audio="AUDIO", body={"secret": "SECRET"}, tools=["SECRET"])
    assert r._events[-1]["raw_terminal_text"] == FIFTH_RAW
    assert "SECRET" not in json.dumps(list(r._events)) and "AUDIO" not in json.dumps(list(r._events))
    with pytest.raises(ValueError):
        r.record_conversation_slice("terminal_text", realtime_session_id="s", raw_terminal_text="x"*4097)
    # Existing export lifecycle, no new recorder, no manual timestamp correlation.
    path = r.stop_and_export()
    with zipfile.ZipFile(path) as z:
        merged = b"\n".join(z.read(n) for n in z.namelist() if n.endswith((".json", ".jsonl", ".txt")))
        assert b"conversation_slice.terminal_text" in merged
        assert b"SECRET" not in merged
