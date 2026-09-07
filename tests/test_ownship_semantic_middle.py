"""User-observed MODEL C regression: a received telemetry SET is not speech."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import inspect
import threading
from uuid import uuid4

import pytest

from orion.full_voice_capture import PhysicalRadioTurn, RadioTurnEventKind
from orion.full_voice_core import FullVoiceCore
from orion.full_voice_stt import FinalizedUserUtterance, NativeSpeechKitTurns
from orion.interaction_router import InteractionRoute
from orion.interaction_contracts import InteractionRequest
from orion.live_telemetry_store import LiveTelemetryStore
from orion.models import AircraftState, Position, TelemetryEnvelope
from orion.ownship_report import ownship_semantics_from_tool_result, map_ownship_report
from orion.ownship_phraseology import KEYS, render_ownship_report
from orion.planner import PlannerCancellationToken
from orion.protected_presentation import tx_correlation
from orion.protected_streaming_presentation import StreamingProtectedPresentation
from orion.protected_streaming_tts import protected_stream_requests
from orion.radio_contracts import RadioContext, RadioEntityRef, RadioModulation
from orion.radio_router import RadioRouter
from orion.tool_gateway import build_tool_gateway
from orion.tool_gateway_contracts import ToolCall, ToolData, ExecutionContext
from orion.world_model import WorldModelFacade
from test_interaction_router import NOW, MissionOwner, BridgeOwner, gateway
from test_full_voice import Port, terminal, snapshot, StreamingFakeRadio, FakeStreamingTts

QUERY = "Какой мой текущий курс и координаты?"


def utterance(text=QUERY):
    return FinalizedUserUtterance(uuid4(), text, 1, 2, 2, 2, 2.1, 2.1, NOW, NOW, "test", 0, 1280)


def controlled(extra):
    store = LiveTelemetryStore()
    store.set(TelemetryEnvelope(sequence=1, state=AircraftState(
        aircraft_type="EXTRA_AIRCRAFT_DO_NOT_SPEAK", callsign="EXTRA_CALLSIGN",
        heading_deg=37.125, position=Position(latitude=-42.1, longitude=41.2, altitude_m=extra),
        true_airspeed_mps=extra, vertical_speed_mps=-extra,
        fuel_fraction=.765, diagnostics={"say": "RAW_TELEMETRY_SENTINEL"},
        navigation={"extra_operational_value": extra},
    )), received_at=NOW-timedelta(seconds=1))
    world = WorldModelFacade(telemetry=store, mission=MissionOwner(), mission_bridge=BridgeOwner(), clock=lambda: NOW)
    return build_tool_gateway(world=world, clock=lambda: NOW), store


@pytest.mark.parametrize("extra", [12345, 98765])
def test_received_telemetry_set_never_leaks_into_osu_renderer_composer_or_tts(extra):
    async def run():
        events, failures = [], []
        capture = PhysicalRadioTurn(events.append, failures.append)
        capture.snapshot(snapshot(1))
        capture.snapshot(snapshot(1.1, True))
        capture.pcm(bytes(1280), 1.2)
        capture.snapshot(snapshot(1.3)); capture.tick(1.4)
        port = Port()
        native = NativeSpeechKitTurns(port, fail=failures.append)
        first = threading.Event()
        adapter = StreamingFakeRadio(first)
        radio = RadioRouter(default_transport_id="srs", queue_capacity=1)
        radio.register_adapter(adapter); radio.start()
        tts = FakeStreamingTts(first)
        presentation = StreamingProtectedPresentation(tts, radio)
        await native.open("fake")
        try:
            for event in events:
                if event.kind is RadioTurnEventKind.START: native.start(event.identity, event.timestamp)
                elif event.kind is RadioTurnEventKind.PCM: await native.audio(event.identity, event.pcm, event.timestamp)
                else: await native.end(event.identity, event.timestamp)
            native.accept(terminal()); native.accept(terminal("eou_update"))
            final = await native.result()
            assert final is not None and final.text == QUERY
            actual_gateway, _ = controlled(extra)
            core = FullVoiceCore(actual_gateway, lambda: pytest.fail("Qwen must not be invoked"), clock=lambda: NOW)
            result = core.run(final, PlannerCancellationToken())
            assert result.status == "completed" and len(result.tool_results) == 1
            assert core.router.diagnostic_snapshot()[0].route is InteractionRoute.BOUNDED_OWNSHIP_REPORT
            assert core.run(final, PlannerCancellationToken()) is result
            finalized = result.finalized
            unit = finalized.protected_fragments[0].semantic_unit
            assert tuple(v.key for v in unit.protected_values) == KEYS
            assert tuple(v.value for v in unit.protected_values) == (37.125, -42.1, 41.2)
            assert tuple(v.unit for v in unit.protected_values) == ("deg", None, None)
            assert unit.semantic_meaning == "navigation.current_ownship_state"
            assert unit.polarity == "declarative" and len(unit.provenance) == 3
            tool = result.tool_results[0]
            assert tool.data.root["snapshot"]["true_airspeed_mps"]["value"] == extra
            assert tool.data.root["snapshot"]["position"]["value"]["altitude_m"] == extra
            assert all(p.source.reference_id == tool.call_id for p in unit.provenance)
            assert all(p.generation == tool.provenance.generations[0] for p in unit.provenance)
            assert tool.receipt.interaction_id == str(final.interaction_id)
            expected = (
                "Current heading zero three seven point one two five degrees. "
                "Latitude minus four two point one degrees. Longitude four one point two degrees."
            )
            assert finalized.text == render_ownship_report(unit, finalized.context).text == expected
            assert finalized.protected_fragments[0].text == expected
            assert protected_stream_requests(finalized.text)[1].synthesis_input.text == expected
            context = RadioContext(
                tx_correlation_id=tx_correlation(final.interaction_id), interaction_id=final.interaction_id,
                source_domain=finalized.context.domain, communication_priority=finalized.priority,
                radio_entity=RadioEntityRef(entity_id="controlled", operational_callsign="ORION"),
                target_frequency_hz=251000000, modulation=RadioModulation.AM,
            )
            outcome = await presentation.present(finalized, context)
            assert outcome.state == "completed"
            assert await presentation.present(finalized, context) == outcome
            assert tts.texts == [expected] and len(adapter.transmit_calls) == 1
            assert not failures
            native.release(final.interaction_id); capture.release(final.interaction_id)
        finally:
            await native.close(); await presentation.shutdown()
    asyncio.run(run())


def retained_tool():
    identity = uuid4()
    tool = gateway().execute(ToolCall(
        call_id="strict-ownship", name="orion.world.ownship.get", version="1.0",
        context=ExecutionContext(actor_id="test", interaction_id=str(identity),
                                 allowed_capabilities=("world.ownship.read",), permissions=("world.read",)),
    ))
    return tool, identity


@pytest.mark.parametrize("mode", [
    "missing", "duplicate", "extra_root", "extra_position", "wrong_unit", "wrong_key",
    "wrong_authority", "wrong_source", "stale", "unavailable", "bad_generation",
    "bad_receipt", "wrong_tool", "expired", "bad_sign_range",
])
def test_strict_mapper_rejects_untrusted_missing_conflicting_or_unavailable_evidence(mode):
    tool, identity = retained_tool()
    raw = deepcopy(tool.data.root)
    heading = raw["snapshot"]["heading_deg"]
    now = NOW
    if mode == "missing": del raw["snapshot"]["heading_deg"]
    elif mode == "duplicate": raw["snapshot"]["true_airspeed_mps"] = deepcopy(heading)
    elif mode == "extra_root": raw["say"] = "SPEAK THIS TELEMETRY SET"
    elif mode == "extra_position": raw["snapshot"]["position"]["value"]["say"] = "DUMP"
    elif mode == "wrong_unit": heading["unit"] = "rad"
    elif mode == "wrong_key": heading["key"] = "ownship.altitude"
    elif mode == "wrong_authority": heading["authority"] = "observed"
    elif mode == "wrong_source": heading["source"] = "mission_store"
    elif mode == "stale": heading.update(status="stale", reason="source_stale")
    elif mode == "unavailable": heading.update(status="unavailable", value=None, reason="source_not_connected")
    elif mode == "bad_generation": heading["generation"] = 999
    elif mode == "bad_receipt": tool = tool.model_copy(update={"receipt": tool.receipt.model_copy(update={"call_id": "wrong"})})
    elif mode == "wrong_tool": tool = tool.model_copy(update={"tool_name": "orion.world.navigation.get"})
    elif mode == "expired": now += timedelta(seconds=6)
    else: heading["value"] = -1
    tool = tool.model_copy(update={"data": ToolData(root=raw)})
    with pytest.raises(ValueError): ownship_semantics_from_tool_result(tool, identity, now=now)


@pytest.mark.parametrize("text", [
    "Расскажи анекдот.", "Не говори какой мой текущий курс и координаты",
    QUERY + " И высота?", "курс и координаты", "Какой мой текущий курс и координаты или скорость?",
    "Скажи все данные телеметрии", "Fly heading 037", "ping",
])
def test_bounded_recognizer_never_broadens_to_extra_or_negated_intents(text):
    core = FullVoiceCore(gateway(), lambda: pytest.fail("provider called"), clock=lambda: NOW)
    result = core.run(utterance(text), PlannerCancellationToken())
    assert result.status == "unsupported" and result.finalized is None and result.tool_results == ()


def test_cancellation_and_state_change_no_cached_facts():
    actual_gateway, store = controlled(12345)
    core = FullVoiceCore(actual_gateway, clock=lambda: NOW)
    first = core.run(utterance(), PlannerCancellationToken())
    old = store.get()
    # Replace through the authoritative store, never modify the semantic result.
    store.set(TelemetryEnvelope(sequence=2, state=AircraftState(
        aircraft_type="F-5E", heading_deg=264.5,
        position=Position(latitude=12.25, longitude=-15.75, altitude_m=500), true_airspeed_mps=200,
    )), received_at=NOW)
    second = core.run(utterance(), PlannerCancellationToken())
    assert old is not None
    assert first.finalized.text != second.finalized.text
    assert [v.value for v in second.finalized.protected_fragments[0].semantic_unit.protected_values] == [264.5, 12.25, -15.75]
    token = PlannerCancellationToken(); token.cancel()
    cancelled = core.run(utterance(), token)
    assert cancelled.finalized is None and not cancelled.tool_results


def test_final_semantic_extra_or_duplicate_fact_is_not_silently_projected():
    tool, identity = retained_tool()
    response = ownship_semantics_from_tool_result(tool, identity, now=NOW)
    for fact in (response.authoritative_facts[0], response.authoritative_facts[0].model_copy(update={"key": "ownship.fuel"})):
        invalid = response.model_copy(update={"authoritative_facts": (*response.authoritative_facts, fact)})
        with pytest.raises(ValueError): map_ownship_report(invalid, (tool,), identity, now=NOW)


def test_mapper_and_renderer_have_no_generic_text_or_telemetry_dump_boundary():
    # Runtime exact-equality tests above are primary; this is a narrow structural
    # guard against reintroducing an obvious generic stringify-to-speech shortcut.
    for function in (ownship_semantics_from_tool_result, map_ownship_report, render_ownship_report):
        source = inspect.getsource(function)
        assert "json.dumps" not in source and "model_dump_json" not in source
        assert "str(tool" not in source and "str(snapshot" not in source
    assert "navigation.current_ownship_state" in inspect.getsource(render_ownship_report)


def test_router_deadline_and_provider_default_path_remain_separate():
    core = FullVoiceCore(gateway(), clock=lambda: NOW)
    result = core.router.execute(InteractionRequest(text=QUERY), core.context, deadline=NOW)
    assert result.status.value == "timed_out" and result.response is None
    final = utterance()
    core.run(final, PlannerCancellationToken())
    with pytest.raises(ValueError): core.run(replace(final, text="other"), PlannerCancellationToken())
