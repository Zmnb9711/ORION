"""Required bounded slice matrix, fake provider and actual local ToolGateway only."""
import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
import threading
from uuid import uuid4

import pytest

from orion.full_voice_stt import FinalizedUserUtterance
from orion.hybrid_aircraft_contracts import *
from orion.hybrid_aircraft_core import *
from orion.informational_presentation import InformationalPresentation, InformationalStreamingTts
from orion.planner import PlannerCancellationToken
from orion.protected_presentation import tx_correlation
from orion.radio_contracts import RadioContext, RadioEntityRef, RadioModulation, RadioReadiness
from orion.radio_router import RadioRouter
from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
from orion.yandex_qwen_planner import YandexQwenPlannerProvider, YandexTransportResponse
from test_full_voice import StreamingFakeRadio, FakeStreamingTts
from test_interaction_router import gateway, NOW
from test_yandex_qwen_planner import FakeTransport, config


PURE = "в каком самолёте я нахожусь?"
MIXED = "Добрый день! В каком самолёте я нахожусь?"
FREE = "Добрый день! Как дела?"


def utterance(text=PURE):
    return FinalizedUserUtterance(uuid4(), text, 1, 2, 1.9, 2.1, 2.2, 2.3, NOW, NOW, "fixture", 0, 640)


def decomposition(text=MIXED):
    # Fixture provider output, not a production classifier or prefix stripper.
    parts = {
        MIXED: [(0, 12, "GREETING"), (12, len(MIXED), "AIRCRAFT_IDENTITY_QUERY")],
        FREE: [(0, 12, "GREETING"), (12, len(FREE), "SOCIAL_WELLBEING_QUERY")],
        "Здравствуйте! На каком самолёте я сейчас нахожусь?": [(0, 14, "GREETING"), (14, 48, "AIRCRAFT_IDENTITY_QUERY")],
        "В каком самолёте я нахожусь? И добрый день!": [(0, 28, "AIRCRAFT_IDENTITY_QUERY"), (28, 41, "GREETING")],
        "Добрый день!": [(0, 12, "GREETING")], "Спасибо.": [(0, 8, "THANKS_ACKNOWLEDGEMENT")],
    }[text]
    # Exact offsets include the whole fixture's punctuation/space boundary.
    if text.startswith("Здравствуйте"):
        parts = [(0, 14, "GREETING"), (14, len(text), "AIRCRAFT_IDENTITY_QUERY")]
    if text.startswith("В каком"):
        split = text.index("И добрый")
        parts = [(0, split, "AIRCRAFT_IDENTITY_QUERY"), (split, len(text), "GREETING")]
    aircraft = any(p[2] == "AIRCRAFT_IDENTITY_QUERY" for p in parts)
    return HybridAircraftDecomposition(classification=HybridRoute.FREE_PLUS_AIRCRAFT_IDENTITY if aircraft else HybridRoute.FREE_ONLY,
        language="ru-RU", spans=tuple(SourceSpan(start=a, end=b, act=c) for a, b, c in parts))


class Provider:
    def __init__(self, result=None, action=None): self.result, self.action, self.calls = result, action, []
    def decompose_aircraft(self, text, identity, deadline, cancellation):
        self.calls.append(text)
        if self.action: self.action(cancellation)
        return self.result or decomposition(text)


class Gateway:
    def __init__(self, mutate=None, action=None): self.calls, self.mutate, self.action = [], mutate, action
    def execute(self, call):
        self.calls.append(call)
        result = gateway().execute(call)
        if self.action: self.action()
        if self.mutate:
            data = result.model_dump(mode="json")
            self.mutate(data)
            from orion.tool_gateway_contracts import ToolResult
            result = ToolResult.model_validate(data)
        return result


def setup(text=PURE, *, provider=None, mutate=None, clock=None, action=None):
    events = []
    g, p = Gateway(mutate, action), provider or Provider()
    core = HybridAircraftCore(g, lambda: p, clock=clock or (lambda: NOW),
                              observe=lambda event, **fields: events.append((event, fields)))
    return core, g, p, events, utterance(text)


@pytest.mark.parametrize("extra", ["aircraft_name", "response_text", "tts_text", "heading", "operational_intent", "tool_calls", "voice", "ttl"])
def test_gate01_strict_schema(extra):
    payload = decomposition().model_dump(mode="json")
    payload[extra] = "F-16C Viper at 15000 feet, cleared for takeoff"
    with pytest.raises(ValueError): HybridAircraftDecomposition.model_validate(payload)


@pytest.mark.parametrize("text,route,reads,calls", [
    (PURE, HybridRoute.AIRCRAFT_IDENTITY, 1, 0),
    ("На каком самолёте я нахожусь?", HybridRoute.AIRCRAFT_IDENTITY, 1, 0),
    ("Какой у меня самолёт?", HybridRoute.AIRCRAFT_IDENTITY, 1, 0),
    (MIXED, HybridRoute.FREE_PLUS_AIRCRAFT_IDENTITY, 1, 1),
    ("Здравствуйте! На каком самолёте я сейчас нахожусь?", HybridRoute.FREE_PLUS_AIRCRAFT_IDENTITY, 1, 1),
    ("В каком самолёте я нахожусь? И добрый день!", HybridRoute.FREE_PLUS_AIRCRAFT_IDENTITY, 1, 1),
    (FREE, HybridRoute.FREE_ONLY, 0, 1), ("Добрый день!", HybridRoute.FREE_ONLY, 0, 1),
    ("Спасибо.", HybridRoute.FREE_ONLY, 0, 1),
    ("Какой это самолёт?", HybridRoute.AMBIGUOUS, 0, 0),
    ("какой мой текущий вкус или оригинал", HybridRoute.UNSUPPORTED, 0, 0),
    ("Он спросил: в каком самолёте я нахожусь?", HybridRoute.UNSUPPORTED, 0, 0),
    ("Я не спрашиваю, в каком самолёте я нахожусь.", HybridRoute.UNSUPPORTED, 0, 0),
    ("Если бы я спросил, в каком самолёте я нахожусь...", HybridRoute.UNSUPPORTED, 0, 0),
    ('"В каком самолёте я нахожусь?"', HybridRoute.UNSUPPORTED, 0, 0),
    ("Добрый день! В каком самолёте я нахожусь и сколько у меня топлива?", HybridRoute.UNSUPPORTED, 0, 0),
    ("Добрый день! В каком самолёте я нахожусь и разрешите взлёт.", HybridRoute.UNSUPPORTED, 0, 0),
])
def test_gate02_routing(text, route, reads, calls):
    core, g, p, events, u = setup(text)
    result = core.run(u, PlannerCancellationToken())
    assert result.route == route and result.failure is None
    assert len(g.calls) == reads and len(p.calls) == calls
    assert bool(result.finalized) == (reads > 0 or route == HybridRoute.FREE_ONLY)
    if calls: assert p.calls == [text]
    if reads:
        assert result.finalized.plan.aircraft.receipt == gateway().execute(g.calls[0]).receipt
        assert result.finalized.plan.aircraft.aircraft_type == "FA-18C_hornet"
    if result.finalized: assert core.authorize(result.finalized)


@pytest.mark.parametrize("mode", ["range", "overlap", "reverse", "residue", "negation", "quote", "hypothetical", "fuel", "wrong_act", "classification", "duplicate", "wrong_language"])
def test_gate03_span_safety(mode):
    raw = decomposition().model_dump(mode="json")
    text = MIXED
    if mode == "range": raw["spans"][1]["end"] = 3999
    elif mode == "overlap": raw["spans"][1]["start"] = 1
    elif mode == "reverse": raw["spans"].reverse()
    elif mode == "residue": text += " ещё"
    elif mode == "negation": text = "Я не спрашиваю: " + text
    elif mode == "quote": text = '"' + text + '"'
    elif mode == "hypothetical": text = "Если бы " + text
    elif mode == "fuel": text += " Сколько топлива?"
    elif mode == "wrong_act": raw["spans"][0]["act"] = "THANKS_ACKNOWLEDGEMENT"
    elif mode == "classification": raw["classification"] = "FREE_ONLY"
    elif mode == "duplicate": raw["spans"].append(raw["spans"][0])
    elif mode == "wrong_language": raw["language"] = "en-US"
    with pytest.raises(ValueError): validate_decomposition(text, HybridAircraftDecomposition.model_validate(raw))


@pytest.mark.parametrize("mode", ["interaction", "turn", "session", "actor", "call", "tool", "version", "schema", "generation", "source", "authority", "age", "future_receipt"])
def test_gate04_bad_receipt_provenance(mode):
    def mutate(r):
        receipt = r["receipt"]
        if mode in {"interaction", "turn", "session", "actor"}: receipt[mode+"_id"] = "wrong"
        elif mode == "call": receipt["call_id"] = "wrong"
        elif mode == "tool": r["tool_name"] = "orion.test.ping"
        elif mode == "version": receipt["tool_version"] = "9.0"
        elif mode == "schema": r["output_schema"] = "wrong.v1"
        elif mode == "generation": r["provenance"]["generations"] = [777]
        elif mode == "source": r["data"]["snapshot"]["aircraft"]["source"] = "mission_store"
        elif mode == "authority": r["data"]["snapshot"]["aircraft"]["authority"] = "observed"
        elif mode == "age": r["data"]["snapshot"]["aircraft"]["age_seconds"] = 99
        elif mode == "future_receipt": receipt["completed_at"] = (NOW+timedelta(seconds=2)).isoformat()
    core, g, p, _, u = setup(mutate=mutate)
    result = core.run(u, PlannerCancellationToken())
    assert result.finalized is None and result.failure == "authoritative_read" and len(g.calls) == 1 and not p.calls


@pytest.mark.parametrize("state", ["stale", "unknown", "unavailable", "unknown_type", "unsafe_type"])
def test_gate04_missing_stale_unknown(state):
    def mutate(r):
        f = r["data"]["snapshot"]["aircraft"]
        if state == "unknown_type": f["value"]["aircraft_type"] = "X_TEST_2026"
        elif state == "unsafe_type": f["value"]["aircraft_type"] = "F-16C at 15000 feet"
        else:
            f["status"] = state
            f["reason"] = "source_stale" if state == "stale" else "source_not_connected"
            if state != "stale": f["value"] = None
            r["provenance"]["fact_statuses"].append(state)
    core, _, _, _, u = setup(mutate=mutate)
    result = core.run(u, PlannerCancellationToken())
    assert result.finalized
    assert result.finalized.text == ("По данным DCS, вы находитесь в X TEST 2026." if state == "unknown_type" else UNAVAILABLE_TEXT)


def test_gate05_extra_telemetry_cannot_leak_any_boundary():
    def mutate(r):
        r["data"]["snapshot"]["extra_fuel"] = "F-16C Viper fuel 9876 cleared for takeoff"
    core, g, p, events, u = setup(MIXED, mutate=mutate)
    result = core.run(u, PlannerCancellationToken())
    assert result.finalized.text == "Добрый день! По данным DCS, вы находитесь в F/A-18C Hornet."
    payload = result.finalized.model_dump_json() + json.dumps(events, ensure_ascii=False)
    for forbidden in (": 137,", ": 42.1,", ": 41.2,", "Colt", "F-16C", '"fuel"', '"heading"', '"position"'):
        assert forbidden not in payload
    assert p.calls == [MIXED]


def radio_for(finalized):
    from orion.communication_contracts import CommunicationDomain, CommunicationPriority
    i = finalized.plan.interaction_id
    return RadioContext(tx_correlation_id=tx_correlation(i), interaction_id=i, turn_id=str(i),
        session_id="recovery-full-voice", source_domain=CommunicationDomain.GENERAL,
        communication_priority=CommunicationPriority.ROUTINE,
        radio_entity=RadioEntityRef(entity_id="controlled", operational_callsign="ORION"),
        target_frequency_hz=251000000, modulation=RadioModulation.AM)


@pytest.mark.parametrize("mode", ["normal", "tamper", "raw", "operational", "fake_receipt", "wrong_language", "expired", "radio_mismatch", "protected_rejects"])
def test_gate06_typed_admission(mode):
    async def run():
        core, _, _, _, u = setup(MIXED)
        final = core.run(u, PlannerCancellationToken()).finalized
        first = threading.Event()
        adapter = StreamingFakeRadio(first)
        router = RadioRouter(default_transport_id="srs")
        router.register_adapter(adapter); router.start()
        tts = FakeStreamingTts(first)
        events = []
        presentation = InformationalPresentation(tts, router, authorize=core.authorize,
            clock=lambda: NOW+timedelta(seconds=6 if mode == "expired" else 0),
            observe=lambda event, **fields: events.append((event, fields)))
        try:
            context = radio_for(final)
            value = final
            if mode == "tamper": value = final.model_copy(update={"text": "F-16C Viper at 15000 feet"})
            elif mode == "raw": value = final.text
            elif mode == "operational":
                from test_protected_presentation import final as protected_final
                value = protected_final()
            elif mode == "fake_receipt":
                a = final.plan.aircraft.model_copy(update={"aircraft_type": "F-16C"})
                p = final.plan.model_copy(update={"aircraft": a})
                value = FinalizedInformationalText(plan=p, text=render_informational(p, NOW))
            elif mode == "wrong_language": value = final.model_copy(update={"plan": final.plan.model_copy(update={"language": "en-US"})})
            elif mode == "radio_mismatch": context = context.model_copy(update={"turn_id": "wrong"})
            elif mode == "protected_rejects":
                from orion.protected_streaming_presentation import StreamingProtectedPresentation
                protected = StreamingProtectedPresentation(tts, router)
                outcome = await protected.present(final, context)
                assert outcome.state == "failed" and not tts.texts and not adapter.transmit_calls
                await protected.shutdown()
                return
            outcome = await presentation.present(value, context)
            if mode == "normal":
                assert outcome.state == "completed"
                assert await presentation.present(value, context) == outcome
                assert len(tts.texts) == len(adapter.transmit_calls) == 1
                assert tts.texts == [final.text]
                assert any(f.get("finalized_text") == final.text for _, f in events)
            else:
                assert outcome.state == "failed" and not tts.texts and not adapter.transmit_calls
        finally:
            await presentation.shutdown(); router.shutdown()
    asyncio.run(run())


def test_gate07_ru_builder_exact_and_john_unchanged():
    from orion.protected_streaming_tts import protected_stream_requests
    text = "  Добрый день! F/A-18C Hornet.\n"
    client = InformationalStreamingTts("fixture")
    requests = client._requests(text)
    assert requests[0].options.voice == "jane" and requests[1].synthesis_input.text == text
    assert requests[0].options.output_audio_spec.raw_audio.sample_rate_hertz == 48000
    requests[0].options.voice = "john"
    assert [r.SerializeToString() for r in requests] == [r.SerializeToString() for r in protected_stream_requests(text)]


@pytest.mark.parametrize("mode", ["failure", "timeout", "cancel", "late", "before_read", "after_read"])
def test_gate08_cancellation_and_provider_failures(mode):
    token = PlannerCancellationToken()
    clock = [NOW]
    def action(cancel):
        if mode in {"failure", "timeout"}: raise TimeoutError("private provider payload")
        if mode == "cancel": cancel.cancel()
        if mode == "late": clock[0] += timedelta(seconds=16)
    provider = Provider(action=action)
    core, g, _, events, u = setup(MIXED if mode not in {"before_read", "after_read"} else PURE,
        provider=provider, clock=lambda: clock[0], action=token.cancel if mode == "after_read" else None)
    if mode == "before_read": token.cancel()
    result = core.run(u, token)
    assert result.finalized is None
    assert len(g.calls) == int(mode == "after_read")
    assert "private provider payload" not in str(events)
    assert core.run(u, token) is result


def test_gate08_replay_and_pure_provider_independence():
    def fail(_): raise RuntimeError("provider offline")
    core, g, p, _, u = setup(provider=Provider(action=fail))
    first = core.run(u, PlannerCancellationToken())
    assert first.finalized and not p.calls
    assert core.run(u, PlannerCancellationToken()) is first and len(g.calls) == 1
    with pytest.raises(ValueError, match="conflicting_replay"):
        core.run(replace(u, text=MIXED), PlannerCancellationToken())


@pytest.mark.parametrize("mode", ["normal", "extra", "tools", "timeout", "billing", "cancel_late"])
def test_gate08_real_qwen_io_extension_one_request_cleanup(monkeypatch, mode):
    payload = decomposition().model_dump(mode="json")
    if mode == "extra": payload["aircraft"] = "F-16C Viper"
    body = {"id": "resp-fixture", "status": "completed", "output": [
        {"type": "message", "content": [{"type": "output_text", "text": json.dumps(payload)}]}]}
    if mode == "tools": body["output"] = [{"type": "function_call", "name": "orion_world_ownship_get"}]
    status = 429 if mode == "billing" else 598 if mode == "timeout" else 200
    transport = FakeTransport([YandexTransportResponse(status, body)])
    provider = YandexQwenPlannerProvider(config(), transport_factory=lambda _: transport)
    token = PlannerCancellationToken()
    if mode == "cancel_late":
        create = transport.create
        def cancel(*args, **kwargs):
            result = create(*args, **kwargs); token.cancel(); return result
        monkeypatch.setattr(transport, "create", cancel)
    text = "  " + MIXED + "\n"
    if mode == "normal":
        result = provider.decompose_aircraft(text, uuid4(), datetime.now(UTC)+timedelta(seconds=2), token)
        assert result == decomposition()
    else:
        with pytest.raises(Exception): provider.decompose_aircraft(text, uuid4(), datetime.now(UTC)+timedelta(seconds=2), token)
    assert transport.closed and len(transport.payloads) == 1
    request = transport.payloads[0]
    assert request["input"] == text and request["store"] is False
    assert "tools" not in request and request["text"]["format"]["strict"] is True
    assert "FA-18C_hornet" not in json.dumps(request) and "ToolResult" not in json.dumps(request)


def test_gate08_evidence_explicit_bounded_and_aircraft_only(tmp_path):
    recorder = RealtimeTestEvidenceRecorder(tmp_path, max_events=20)
    core, _, _, events, u = setup(MIXED)
    result = core.run(u, PlannerCancellationToken())
    for name, fields in events: recorder.record_aircraft_slice(name, realtime_session_id="fixture", **fields)
    assert not recorder._events
    recorder.start(provider="yandex", transport="srs")
    for name, fields in events:
        recorder.record_aircraft_slice(name, realtime_session_id="fixture", secret="not allowed", tool_result={"fuel":9876}, **fields)
    recorder.record_aircraft_slice("tts_input", realtime_session_id="fixture", tts_input=result.finalized.text)
    recorder.record("tx_completed", response_id=tx_correlation(u.interaction_id), frames=123)
    serialized = json.dumps(list(recorder._events), ensure_ascii=False)
    assert "9876" not in serialized and "not allowed" not in serialized and "heading" not in serialized
    assert recorder._events[-1]["frames"] == 123 and result.finalized.text in serialized
    assert len({e["test_session_id"] for e in recorder._events}) == 1


@pytest.mark.parametrize("mode", ["tts_failure", "radio_rejection", "cancel_tts", "conflict"])
def test_gate08_stream_failure_cancel_and_conflicting_replay(mode):
    async def run():
        core, _, _, _, u = setup()
        final = core.run(u, PlannerCancellationToken()).finalized
        first = threading.Event()
        adapter = StreamingFakeRadio(first)
        if mode == "radio_rejection": adapter.readiness = RadioReadiness.UNAVAILABLE
        router = RadioRouter(default_transport_id="srs")
        router.register_adapter(adapter); router.start()
        entered = asyncio.Event()
        class Tts:
            calls = 0
            async def stream(self, text):
                self.calls += 1; entered.set()
                if mode == "tts_failure": raise RuntimeError("private provider payload")
                if mode == "cancel_tts": await asyncio.Event().wait()
                yield bytes(48000)
            async def aclose(self): pass
        tts = Tts()
        service = InformationalPresentation(tts, router, authorize=core.authorize, clock=lambda: NOW)
        try:
            context = radio_for(final)
            task = asyncio.create_task(service.present(final, context))
            if mode == "cancel_tts":
                await asyncio.wait_for(entered.wait(), 1)
                task.cancel()
                with pytest.raises(asyncio.CancelledError): await task
                await asyncio.sleep(.03)
            else:
                result = await asyncio.wait_for(task, 2)
                assert result.state == ("completed" if mode == "conflict" else "failed")
                if mode == "conflict":
                    conflict = context.model_copy(update={"target_frequency_hz": 252000000})
                    duplicate = await service.present(final, conflict)
                    assert duplicate.failure.value == "conflicting_replay"
                else:
                    assert await service.present(final, context) == result
            assert tts.calls == int(mode != "radio_rejection")
            assert len(adapter.transmit_calls) <= 1
        finally:
            await service.shutdown(); router.shutdown()
    asyncio.run(run())


def test_gate04_real_no_dcs_read_stays_unavailable():
    from orion.live_telemetry_store import LiveTelemetryStore
    from orion.world_model import WorldModelFacade
    from orion.tool_gateway import build_tool_gateway
    world = WorldModelFacade(telemetry=LiveTelemetryStore(), clock=lambda: NOW)
    g = build_tool_gateway(world=world, clock=lambda: NOW)
    core = HybridAircraftCore(g, lambda: pytest.fail("provider not allowed"), clock=lambda: NOW)
    result = core.run(utterance(), PlannerCancellationToken())
    assert result.finalized.text == UNAVAILABLE_TEXT
    assert result.finalized.plan.aircraft.aircraft_type is None


def test_gate08_invalid_decomposition_never_reads():
    invalid = decomposition().model_copy(update={"spans": (SourceSpan(start=0, end=3000, act="GREETING"),)})
    core, g, p, events, u = setup(MIXED, provider=Provider(invalid))
    result = core.run(u, PlannerCancellationToken())
    assert result.failure == "decomposition_validation" and not g.calls and result.finalized is None
    assert len(p.calls) == 1 and any(name == "failed" for name, _ in events)


def test_gate08_ru_actual_stream_rpc_exact_text_and_closed(monkeypatch):
    import sys
    from test_hybrid_seams import FakeGrpc
    async def run():
        rpc = FakeGrpc("normal")
        monkeypatch.setitem(sys.modules, "grpc", rpc.module())
        observed = []
        tts = InformationalStreamingTts("fixture", observe=observed.append)
        text = "  Добрый день! По данным DCS, вы находитесь в F/A-18C Hornet.\n"
        chunks = [chunk async for chunk in tts.stream(text)]
        await tts.aclose()
        from orion.protected_streaming_tts import p
        requests = [p.StreamSynthesisRequest.FromString(b) for b in rpc.requests]
        assert requests[0].options.voice == "jane" and requests[1].synthesis_input.text == text
        assert observed == [text] and chunks == [b"\x01\x00", b"\x02\x00"]
        assert rpc.closed == 1 and tts._call is None
    asyncio.run(run())
