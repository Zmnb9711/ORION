"""Isolated pre-live integration harness; frozen host is not wired yet."""
import asyncio
from dataclasses import replace
import inspect
from pathlib import Path
import subprocess
import threading
import time
from types import SimpleNamespace as NS

import pytest

from orion.conversational_contracts import *
from orion.communication_contracts import CommunicationDomain, CommunicationPriority
from orion.conversational_core import ConversationalCore
from orion.conversational_presentation import ConversationVoice, ConversationalPresentation
from orion.full_voice_core import FullVoiceCore
from orion.hybrid_aircraft_core import HybridAircraftCore
from orion.informational_presentation import InformationalStreamingTts
from orion.planner import PlannerCancellationToken
from orion.protected_presentation import tx_correlation
from orion.radio_contracts import RadioContext, RadioEntityRef, RadioModulation, RadioReadiness
from orion.radio_router import RadioRouter
from orion.yandex_realtime_text_conversation import TextConversationProvider
from test_conversation_prerequisites import SOCIAL, SAFE, UNSAFE, Fake, events, setup
from test_full_voice import StreamingFakeRadio, FakeStreamingTts
from test_hybrid_aircraft import utterance, Gateway, NOW, MIXED, FREE


def rig(fake, *, tts=None, observe=None):
    first = threading.Event()
    adapter = StreamingFakeRadio(first)
    router = RadioRouter(default_transport_id="srs")
    router.register_adapter(adapter); router.start()
    tts = tts or FakeStreamingTts(first)
    endpoint = NS(radio_router=router, tx_marks={}, packet_id=0)
    entity = RadioEntityRef(entity_id="controlled", operational_callsign="ORION")
    observed = []
    observe = observe or (lambda event, **fields: observed.append((event,fields)))
    provider = TextConversationProvider(lambda:fake, observe=observe)
    voice = ConversationVoice("fixture", "fixture", endpoint, entity, provider=provider, tts=tts, observe=observe)
    return voice, router, adapter, tts, observed


@pytest.mark.parametrize("text", SOCIAL[:3])
def test_fake_complete_exact_candidate_to_tts_once(text):
    async def run():
        voice, router, radio, tts, observed = rig(Fake(events(SAFE[SOCIAL.index(text)])))
        u = utterance(text)
        try:
            assert await voice.run(u, PlannerCancellationToken())
            assert len(tts.texts) == len(radio.transmit_calls) == 1
            final = voice.core._finalized[u.interaction_id]
            assert final.text == tts.texts[0] == SAFE[SOCIAL.index(text)]
            assert any(e == "response_terminal" and f["status"] == "completed" for e,f in observed)
            assert await voice.run(u, PlannerCancellationToken())
            assert len(tts.texts) == len(radio.transmit_calls) == 1
            assert not voice.provider.owned
        finally:
            await voice.shutdown(); router.shutdown()
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["provider_closed", "unsafe", "radio_reject", "tts_fail", "observer_fail"])
def test_failures_no_factual_or_planner_fallback(mode):
    async def run():
        class Tts:
            texts=[]
            async def stream(self, text):
                self.texts.append(text)
                raise RuntimeError("secret provider body")
                yield b""
            async def aclose(self): pass
        fake = Fake([] if mode == "provider_closed" else events(UNSAFE[0] if mode == "unsafe" else SAFE[0]))
        def broken(*args, **kwargs): raise PermissionError("evidence unavailable")
        voice, router, radio, tts, observed = rig(fake, tts=Tts() if mode == "tts_fail" else None,
            observe=broken if mode == "observer_fail" else None)
        if mode == "radio_reject": radio.readiness = RadioReadiness.UNAVAILABLE
        try:
            assert await voice.run(utterance(SOCIAL[0]), PlannerCancellationToken())
            assert len(tts.texts) == int(mode in {"tts_fail", "observer_fail"})
            assert len(radio.transmit_calls) <= 1
            assert "secret provider body" not in str(observed)
        finally:
            await voice.shutdown(); router.shutdown()
    asyncio.run(run())


@pytest.mark.parametrize("phase", ["connect", "request", "receive", "first_token", "tts"])
def test_stop_new_owner_within_frozen_envelope(phase):
    async def run():
        token = PlannerCancellationToken()
        class Tts:
            texts = []
            async def stream(self, text):
                self.texts.append(text); token.cancel()
                await asyncio.Event().wait()
                yield b""
            async def aclose(self): pass
        fake = Fake(stall=phase, cancel=token)
        voice, router, radio, tts, observed = rig(fake, tts=Tts() if phase == "tts" else None)
        began = time.monotonic()
        try:
            assert await voice.run(utterance(SOCIAL[0]), token)
            await voice.shutdown()
            assert time.monotonic()-began < 1
            assert not voice.provider.owned
            assert all(op.task.done() for op in voice.presentation._operations.values())
            assert len(tts.texts) == int(phase == "tts")
            assert len(radio.transmit_calls) <= 1
        finally:
            await voice.shutdown(); router.shutdown()
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["raw", "candidate", "protected", "informational", "changed", "other_turn", "radio", "authority"])
def test_new_presentation_rejects_wrong_ingress_before_tts(mode):
    async def run():
        voice, router, radio, tts, _ = rig(Fake())
        u = utterance(SOCIAL[0])
        request = voice.core.request(u)
        candidate = ConversationalCandidate(request=request, draft=SocialDraft(kind="social_support",text=SAFE[0]),
            provider_response_id="one",terminal="completed")
        final = voice.core.admit(candidate)
        value = final
        context = RadioContext(tx_correlation_id=tx_correlation(u.interaction_id), interaction_id=u.interaction_id,
            turn_id=str(u.interaction_id), session_id="recovery-full-voice", radio_entity=voice.entity,
            source_domain=CommunicationDomain.GENERAL, communication_priority=CommunicationPriority.ROUTINE,
            target_frequency_hz=251000000, modulation=RadioModulation.AM)
        if mode == "raw": value = final.text
        if mode == "candidate": value = candidate
        if mode == "protected":
            value = FullVoiceCore(Gateway(), clock=lambda:NOW).run(utterance("какой мой текущий курс и координаты"), PlannerCancellationToken()).finalized
        if mode == "informational":
            value = HybridAircraftCore(Gateway(), lambda:pytest.fail(), clock=lambda:NOW).run(utterance(MIXED),PlannerCancellationToken()).finalized
        if mode == "changed": value = final.model_copy(update={"text": SAFE[1]})
        if mode == "other_turn": context = context.model_copy(update={"turn_id":"other"})
        if mode == "radio": context = context.model_copy(update={"tx_correlation_id":"other"})
        if mode == "authority": context = context.model_copy(update={"provenance":("dcs_export",)})
        try:
            result = await voice.presentation.present(value, context)
            assert result.failure.value == "invalid_finalized_text"
            assert not radio.transmit_calls and not tts.texts
        finally:
            await voice.shutdown(); router.shutdown()
    asyncio.run(run())


@pytest.mark.parametrize("text,expected", [("какой мой текущий курс и координаты","frozen"),
    (MIXED,"hybrid"), ("Как дела?","hybrid"), (FREE,"hybrid"),
    (SOCIAL[0],"conversation"), ("Как дела? И какой у меня самолёт?","unsupported"),
    ("Полёт тяжело идёт, мне садиться?","unsupported")])
def test_provider_free_routing_composition_before_host_wiring(text, expected):
    # Actual existing routers followed by proposed Level0 ingress. No provider.
    g = Gateway(); token = PlannerCancellationToken(); u = utterance(text)
    result = FullVoiceCore(g, clock=lambda:NOW).run(u,token)
    if result.finalized: actual = "frozen"
    else:
        information = HybridAircraftCore(g, lambda:pytest.fail("Planner/provider forbidden"),clock=lambda:NOW).run(u,token)
        if information.finalized: actual = "hybrid"
        else: actual = "conversation" if ConversationalCore().request(u) else "unsupported"
    assert actual == expected
    assert len(g.calls) == int(expected == "frozen" or text == MIXED)


def test_ru_tts_builder_literal_borrowing():
    text = "  Понимаю вас. Хотите поговорить?\n"
    tts = InformationalStreamingTts("fixture")
    requests = tts._requests(text)
    assert requests[0].options.voice == "jane"
    assert requests[1].synthesis_input.text == text


def test_frozen_subsystems_byte_identical():
    root = Path(__file__).resolve().parents[1]
    frozen = ["full_voice_stt.py", "full_voice_srs.py", "yandex_srs_live_core.py", "launcher_cloud_voice_sections.py",
        "protected_presentation.py", "protected_streaming_presentation.py", "protected_streaming_tts.py",
        "informational_presentation.py", "interaction_router.py", "tool_gateway.py", "world_model.py",
        "radio_router.py", "srs_radio_transport.py", "yandex_qwen_planner.py", "hybrid_aircraft_core.py"]
    for name in frozen:
        path = "orion/"+name
        before = subprocess.check_output(["git","show","f0c9e364:"+path],cwd=root)
        assert before.replace(b"\r\n",b"\n") == (root/path).read_bytes().replace(b"\r\n",b"\n"),path
