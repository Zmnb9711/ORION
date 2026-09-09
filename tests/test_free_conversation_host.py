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
import orion.conversational_presentation as conversation
from orion.conversational_core import parse_draft
from orion.full_voice_core import FullVoiceCore
from orion.hybrid_aircraft_core import HybridAircraftCore
from orion.informational_presentation import InformationalPresentation
from orion.radio_router import RadioRouter
from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
from orion.yandex_realtime_text_conversation import TextConversationProvider
from orion.yandex_srs_live_core import YandexSrsStartRequest
from test_conversation_prerequisites import Fake, SOCIAL
from test_free_conversation_policy import FIFTH_RAW
from test_full_voice import StreamingFakeRadio
from test_hybrid_aircraft import PURE, MIXED, FREE, NOW, Gateway, utterance
from test_level0_event_contract import sequence


@pytest.mark.parametrize("mode", ["success", "provider_failure", "invalid_candidate", "tts_failure",
    "observer_failure", "inactive", "stop_provider"])
def test_normal_host_conversation_then_core_no_fallback(monkeypatch, tmp_path, mode):
    inputs = [utterance(SOCIAL[0]), utterance(SOCIAL[1]), utterance(PURE)]
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

    class Voice(conversation.ConversationVoice):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            owners.append(self)
            def factory():
                seq = sequence(answer_text if mode != "invalid_candidate" else "Привет\x00")
                fake = Fake([] if mode == "provider_failure" else seq, echo_submitted=True)
                if mode == "stop_provider":
                    async def stopped_receive():
                        stop.set()
                        await asyncio.Event().wait()
                    fake.receive = stopped_receive
                transports.append(fake)
                return fake
            self.provider = TextConversationProvider(factory, observe=self.emit)

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
    monkeypatch.setattr(host, "NativeSpeechKitTurns", Native)
    monkeypatch.setattr(host, "GrpcSpeechKitStreamingPort", lambda: None)
    monkeypatch.setattr(host, "SrsTransportDiagnostics", lambda *a, **k: None)
    monkeypatch.setattr(host, "build_tool_gateway", lambda **k: gateway)
    monkeypatch.setattr(host, "FullVoiceCore", lambda g: FullVoiceCore(g, clock=lambda: NOW))
    monkeypatch.setattr(host, "HybridAircraftCore", Hybrid)
    monkeypatch.setattr(host, "InformationalPresentation", Info)
    monkeypatch.setattr(host, "ConversationVoice", Voice)
    monkeypatch.setattr(host, "realtime_test_evidence", recorder)
    monkeypatch.setattr(host.ProtectedStreamingTts, "stream", tts)
    service = host.FullVoiceService(endpoint_factory=Endpoint)
    request = YandexSrsStartRequest(api_key="fixture", folder_id="fixture", eam_password="fixture")
    try:
        asyncio.run(asyncio.wait_for(service._voice(request, "conversation-host", stop), 4))
        assert service.status().state != "error"
        assert all(not v.provider.owned and not v.provider.busy for v in owners)
        assert all(f.closed == 1 for f in transports)
        if mode == "stop_provider":
            assert not texts and not adapter.transmit_calls and not gateway.calls
            return
        assert released == [u.interaction_id for u in inputs]
        assert len(transports) == len(owners) == 2
        assert len(gateway.calls) == 1  # Third turn ONLY, authoritative aircraft.
        assert texts[-1] == "Вы находитесь в F/A-18C Hornet."
        success = mode not in {"provider_failure", "invalid_candidate", "tts_failure"}
        # Existing streaming transport admits a stream before its first PCM.
        # TTS failure must send zero audio, not require different radio admission.
        assert len(adapter.transmit_calls) == (3 if success or mode == "tts_failure" else 1)
        if mode == "tts_failure":
            assert all(r.audio.stream.high_water == 0 for r in adapter.transmit_calls[:2])
        assert len(texts) == (3 if success or mode == "tts_failure" else 1)
        if success: assert texts[:2] == [answer_text, answer_text]
        if mode == "inactive": assert not recorder._events
        elif mode not in {"observer_failure"}:
            data = list(recorder._events)
            for u in inputs[:2]:
                turn = [e for e in data if e.get("turn_id") == str(u.interaction_id)]
                route = next(e for e in turn if e.get("route") == "CONVERSATION")
                assert route["source_text"] == u.text
                assert route["planner_call_count"] == route["tool_gateway_call_count"] == 0
                assert any(e.get("conversation_provider_call_count") == 1 for e in turn)
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
    "Когда впервые полетел F/A-18?", "Что-то сегодня полёт тяжело идёт. Разрешите посадку."])
def test_known_and_unhandled_routes_never_instantiate_conversation(monkeypatch, tmp_path, text):
    from test_hybrid_host import test_gate10_normal_host_coexistence_and_single_owner as run_existing
    def forbidden(*a, **k): raise AssertionError("Conversation entered a known/unsupported route")
    monkeypatch.setattr(host, "ConversationVoice", forbidden)
    run_existing(monkeypatch, tmp_path, text, text in {PURE, MIXED, FREE, "Какой мой текущий курс и координаты?"}, 0, "inactive")


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
