from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
import threading
import time
from uuid import uuid4

import pytest

from orion.full_voice_capture import PhysicalRadioTurn, RadioTurnEventKind
from orion.full_voice_stt import NativeSpeechKitTurns
from orion.speechkit_v3_stt_transport import SpeechKitProviderEvent, SpeechKitSttProtocolError
from orion.srs_tx_state import SrsTxStateSnapshot
from orion.full_voice_core import FullVoiceCore
from orion.planner import PlannerCancellationToken
from orion.protected_streaming_tts import protected_stream_requests
from orion.protected_streaming_presentation import StreamingProtectedPresentation
from orion.bounded_radio_stream import BoundedPcmStream
from orion.radio_contracts import (
    RadioAdapterTxResult, RadioAdapterOutcome, RadioContext, RadioEntityRef,
    RadioModulation, RadioTransportCapability,
)
from orion.radio_router import RadioRouter
from orion.protected_presentation import tx_correlation
from test_interaction_router import OwnshipProvider, gateway, NOW
from test_radio_router import FakeRadioTransportAdapter


class Port:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.audio = []
        self.eous = 0
        self.closed = False

    async def open(self, _key): pass
    async def send_audio(self, pcm): self.audio.append(pcm)
    async def send_eou(self): self.eous += 1
    async def receive(self): return await self.queue.get()
    async def done_writing(self): pass
    async def close(self): self.closed = True


def terminal(kind="final", text="Какой мой текущий курс и координаты?", **kwargs):
    return replace(SpeechKitProviderEvent(
        kind=kind, session_uuid="provider-session", transcript=text if kind == "final" else "",
        final_index=0, received_data_ms=200, final_time_ms=200, eou_time_ms=200,
    ), **kwargs)


async def opened():
    failures = []
    port = Port()
    native = NativeSpeechKitTurns(port, fail=failures.append, barrier_timeout=.03)
    await native.open("not-a-real-key")
    identity = uuid4()
    native.start(identity, 1.0)
    await native.audio(identity, b"\x01\x00" * 320, 1.02)
    return native, port, identity, failures


@pytest.mark.parametrize("order", [("final", "eou_update"), ("eou_update", "final")])
def test_one_physical_turn_barrier_exact_text_and_no_duplicate(order):
    async def run():
        native, port, identity, failures = await opened()
        try:
            native.accept(terminal("partial"))
            assert not native.future.done()
            await native.end(identity, 1.2)
            for kind in order:
                native.accept(terminal(kind, "  Курс и координаты?  "))
            result = await native.result()
            assert result.text == "  Курс и координаты?  "
            assert result.interaction_id == identity and port.eous == 1
            native.accept(terminal("final", "  Курс и координаты?  "))
            assert await native.result() is result
            native.release(identity)
            native.accept(terminal("final", "  Курс и координаты?  "))
            assert not failures
        finally: await native.close()
        assert port.closed and native._reader.done()
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["early", "mismatch", "busy", "conflict", "cursor", "session", "overflow"])
def test_native_rejects_ambiguous_or_excessive_turn(mode):
    async def run():
        native, port, identity, failures = await opened()
        try:
            with pytest.raises(SpeechKitSttProtocolError):
                if mode == "early": native.accept(terminal())
                elif mode == "mismatch": await native.end(uuid4(), 1.2)
                elif mode == "busy": native.start(uuid4(), 1.1)
                elif mode == "overflow": await native.audio(identity, bytes(960002), 1.1)
                else:
                    await native.end(identity, 1.2)
                    native.accept(terminal())
                    if mode == "conflict": native.accept(terminal(text="other"))
                    elif mode == "cursor": native.accept(terminal("eou_update", eou_time_ms=199))
                    else: native.accept(terminal("eou_update", session_uuid="other"))
            assert failures and native.future.cancelled()
        finally: await native.close()
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["final", "eou_update"])
def test_incomplete_barrier_times_out_without_utterance(kind):
    async def run():
        native, _, identity, failures = await opened()
        try:
            await native.end(identity, 1.2)
            native.accept(terminal(kind))
            assert not native.future.done()
            await asyncio.sleep(.05)
            assert failures == ["final_eou_timeout"] and native.future.cancelled()
        finally: await native.close()
    asyncio.run(run())


def test_empty_final_and_late_closed_event_do_not_dispatch():
    async def run():
        native, _, identity, failures = await opened()
        await native.end(identity, 1.2)
        native.accept(terminal(text="")); native.accept(terminal("eou_update"))
        assert await native.result() is None
        await native.close()
        native.accept(terminal(text="late"))
        assert not failures
    asyncio.run(run())


def snapshot(at, sending=False, radio=1):
    return SrsTxStateSnapshot(sending, radio, 0, at, "test")


def test_held_ptt_pause_candidate_pcm_and_explicit_end_only():
    events, failures = [], []
    capture = PhysicalRadioTurn(events.append, failures.append)
    capture.snapshot(snapshot(0))
    capture.pcm(b"\x01\x00" * 640, .1)
    capture.snapshot(snapshot(.2, True))
    capture.tick(2.0)  # Far beyond the old 400 ms packet-gap boundary.
    assert [e.kind for e in events] == [RadioTurnEventKind.START, RadioTurnEventKind.PCM]
    capture.pcm(b"\x02\x00" * 640, 2.1)
    capture.snapshot(snapshot(2.2))
    capture.tick(2.29)
    assert events[-1].kind is RadioTurnEventKind.END and events[-1].timestamp == 2.2
    assert len({e.identity for e in events}) == 1 and not failures
    assert capture.tx_permitted()
    capture.release(events[0].identity)


@pytest.mark.parametrize("mode", ["wrong_radio", "busy", "unconfirmed", "overflow", "release"])
def test_physical_fail_closed(mode):
    events, failures = [], []
    capture = PhysicalRadioTurn(events.append, failures.append)
    capture.snapshot(snapshot(0))
    if mode == "wrong_radio": capture.snapshot(snapshot(.1, True, 2))
    elif mode == "unconfirmed": capture.pcm(b"\0\0", .1); capture.tick(1)
    elif mode == "overflow":
        for _ in range(4): capture.pcm(bytes(6400), .1)
    else:
        capture.snapshot(snapshot(.1, True)); capture.snapshot(snapshot(.2)); capture.tick(.3)
        if mode == "busy": capture.snapshot(snapshot(.4, True))
        else: capture.release(uuid4())
    assert failures and not capture.tx_permitted()


@pytest.mark.parametrize("text", ["Fly heading zero three seven.", "  Exact protected text.\n", "Current heading zero zero zero point zero degrees."])
def test_streaming_request_text_exact(text):
    requests = protected_stream_requests(text)
    assert requests[1].synthesis_input.text == text
    assert requests[0].options.voice == "john"
    assert requests[0].options.output_audio_spec.raw_audio.sample_rate_hertz == 48000


def test_stream_bounds_and_cancellation_unblock_writer():
    stream = BoundedPcmStream(capacity=10584, limit=21168)
    stream.feed(bytes(10584))
    failures = []
    def write():
        try: stream.feed(bytes(10584))
        except RuntimeError: failures.append(True)
    worker = threading.Thread(target=write)
    worker.start(); stream.abort(); worker.join(1)
    assert failures and not worker.is_alive() and stream.high_water == 10584


class StreamingFakeRadio(FakeRadioTransportAdapter):
    def __init__(self, first):
        super().__init__(transport_id="srs")
        self.first = first
    def capabilities(self):
        return super().capabilities() | {RadioTransportCapability.STREAMING_PCM}
    def transmit(self, request):
        self.transmit_calls.append(request)
        stream = request.audio.stream
        stream.wait_prebuffer()
        started = time.monotonic()
        while True:
            data, end = stream.read(3528)
            if data: self.first.set()
            if end: break
            if time.monotonic() - started > 2: raise TimeoutError
            time.sleep(.001)
        return RadioAdapterTxResult(
            tx_correlation_id=request.context.tx_correlation_id,
            outcome=RadioAdapterOutcome.COMPLETED, completed_at=NOW,
        )


class FakeStreamingTts:
    def __init__(self, first): self.first, self.texts = first, []
    async def stream(self, text):
        self.texts.append(text)
        yield bytes(24000)
        assert await asyncio.to_thread(self.first.wait, 1), "TX must begin before final TTS chunk"
        yield bytes(24000)
    async def aclose(self): pass


def test_actual_full_chain_one_response_and_replay():
    async def run():
        native, _, identity, failures = await opened()
        first = threading.Event()
        adapter = StreamingFakeRadio(first)
        router = RadioRouter(default_transport_id="srs", queue_capacity=1)
        router.register_adapter(adapter); router.start()
        tts = FakeStreamingTts(first)
        presentation = StreamingProtectedPresentation(tts, router)
        try:
            await native.end(identity, 1.2)
            native.accept(terminal()); native.accept(terminal("eou_update"))
            utterance = await native.result()
            provider = OwnshipProvider()
            core = FullVoiceCore(gateway(), lambda: provider, clock=lambda: NOW)
            result = core.run(utterance, PlannerCancellationToken())
            assert result.status == "completed" and len(provider.requests) == 0
            assert core.run(utterance, PlannerCancellationToken()) is result
            finalized = result.finalized
            assert finalized.text.startswith("Current heading one three seven point zero degrees.")
            assert "Fly heading" not in finalized.text
            assert [v.value for v in finalized.protected_fragments[0].semantic_unit.protected_values] == [137, 42.1, 41.2]
            radio = RadioContext(
                tx_correlation_id=tx_correlation(identity), source_domain=finalized.context.domain,
                communication_priority=finalized.priority, interaction_id=identity,
                radio_entity=RadioEntityRef(entity_id="controlled", operational_callsign="ORION"),
                target_frequency_hz=251000000, modulation=RadioModulation.AM,
            )
            outcome = await presentation.present(finalized, radio)
            assert outcome.state == "completed"
            assert await presentation.present(finalized, radio) == outcome
            assert len(adapter.transmit_calls) == len(tts.texts) == 1
            assert tts.texts[0] == finalized.text and not failures
        finally:
            await native.close(); await presentation.shutdown()
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["unsupported", "mismatch", "cancelled", "stale"])
def test_core_never_fabricates_an_operational_answer(mode):
    async def run():
        native, _, identity, _ = await opened()
        try:
            await native.end(identity, 1.2)
            text = "Расскажи анекдот." if mode == "unsupported" else "Какой мой текущий курс и координаты?"
            native.accept(terminal(text=text)); native.accept(terminal("eou_update"))
            utterance = await native.result()
            provider = OwnshipProvider(heading=99 if mode == "mismatch" else 137)
            core = FullVoiceCore(gateway(), lambda: provider, clock=lambda: NOW + timedelta(seconds=10 if mode == "stale" else 0), deterministic=False)
            cancel = PlannerCancellationToken()
            if mode == "cancelled": cancel.cancel()
            if mode == "stale":
                with pytest.raises(ValueError): core.run(utterance, cancel)
            else:
                result = core.run(utterance, cancel)
                assert result.finalized is None
        finally: await native.close()
    asyncio.run(run())
