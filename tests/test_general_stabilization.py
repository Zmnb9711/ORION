"""Gate A mechanism tests: no network, provider credentials or physical audio."""
import asyncio
from datetime import UTC, datetime
import json

import pytest

from orion.conversational_contracts import ConversationFailure
from orion.general_semantic_contracts import (
    CapabilityGap, Clarification, Dialogue, FactRequest, SemanticProposal, provider_instructions,
)
from orion.planner import PlannerCancellationToken
from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter
from test_general_semantic import make, SemanticWire
from test_yandex_warm_aircraft_interpreter import Wire


GOOD = '{"kind":"DIALOGUE","text":"A new contribution to our discussion."}'
FACT = '{"kind":"FACT_REQUEST","capabilities":["ownship.heading"]}'


def request():
    core, _, u, _, _ = make()
    core.clock = lambda: datetime.now(UTC)
    core.pending.clear()
    return core.request(u)


@pytest.mark.parametrize("bad", [
    '{"kind":"DIALOGUE","text":42}',
    '{"kind":"CAPABILITY_GAP","need":"invalid"}',
    '{"kind":"FACT_REQUEST","capabilities":["unknown"]}',
    '{"kind":"DIALOGUE","kind":"DIALOGUE","text":"x"}',
    'not json',
])
def test_invalid_terminal_recovers_once_for_future_dialogue_and_fact(bad):
    async def run():
        wires = [SemanticWire(GOOD), SemanticWire(GOOD)]
        observed = []
        owner = WarmYandexAircraftInterpreter(lambda: wires[owner.connect_count], general=True,
            observe=lambda e, **f: observed.append((e, f)))
        token = PlannerCancellationToken()
        assert await owner.prepare()
        assert (await owner.interpret_general(request(), token)).result.kind == "DIALOGUE"
        await owner.wait_isolation()
        wires[0].body = bad
        with pytest.raises(ValueError):
            await owner.interpret_general(request(), token)
        assert owner.operation_count == 2 and owner.state == "recovering"
        assert wires[0].closed == 1
        assert await owner.wait_recovery()
        assert owner.connect_count == 2 and owner.recovery_count == 1
        assert (await owner.interpret_general(request(), token)).result.kind == "DIALOGUE"
        await owner.wait_isolation()
        wires[1].body = FACT
        assert (await owner.interpret_general(request(), token)).result.kind == "FACT_REQUEST"
        await owner.wait_isolation()
        assert owner.operation_count == 4  # No same-turn retry.
        raw = [f["raw_terminal_text"] for e, f in observed if e == "terminal_text"]
        assert raw[1] == bad
        failures = [f for e, f in observed if e == "validation_failed"]
        assert failures and all("validation_path" in f and "validation_type" in f for f in failures)
        assert all("input" not in f and "ctx" not in f for f in failures)
        assert any(e == "parsed_terminal" for e, _ in observed)
        await owner.shutdown()
        assert not owner.owned and owner.state == "stopped"
    asyncio.run(run())


def test_semantic_timeout_recovery_and_no_retry():
    async def run():
        wires = [Wire("generation_stall"), SemanticWire(GOOD)]
        owner = WarmYandexAircraftInterpreter(lambda: wires[owner.connect_count], general=True)
        assert await owner.prepare()
        with pytest.raises(ConversationFailure, match="LATENCY"):
            await owner.interpret_general(request(), PlannerCancellationToken())
        assert owner.operation_count == 1
        assert await owner.wait_recovery()
        await owner.interpret_general(request(), PlannerCancellationToken())
        await owner.wait_isolation()
        await owner.shutdown()
        assert owner.operation_count == 2 and not owner.owned
    asyncio.run(run())


def test_failed_rewarm_does_not_loop_or_consume_future_turn():
    async def run():
        wires = [SemanticWire('{"kind":"bad"}'), Wire("connect_error")]
        owner = WarmYandexAircraftInterpreter(lambda: wires[owner.connect_count], general=True)
        assert await owner.prepare()
        with pytest.raises(ValueError): await owner.interpret_general(request(), PlannerCancellationToken())
        assert not await owner.wait_recovery()
        for _ in range(3):
            with pytest.raises(ConversationFailure, match="not_warm"):
                await owner.interpret_general(request(), PlannerCancellationToken())
        assert owner.connect_count == 2 and owner.operation_count == 1 and owner.recovery_count == 1
        await owner.shutdown()
    asyncio.run(run())


def test_stop_owns_stalled_recovery_and_never_reaches_ready():
    async def run():
        wires = [SemanticWire('{"kind":"bad"}'), Wire("connect_stall")]
        owner = WarmYandexAircraftInterpreter(lambda: wires[owner.connect_count], general=True)
        assert await owner.prepare()
        with pytest.raises(ValueError): await owner.interpret_general(request(), PlannerCancellationToken())
        await wires[1].entered.wait()
        with pytest.raises(ConversationFailure, match="not_warm"):
            await owner.interpret_general(request(), PlannerCancellationToken())
        await owner.shutdown()
        assert owner.state == "stopped" and not owner.owned
        assert owner._recovery_task.done() and wires[1].closed == 1
    asyncio.run(run())


@pytest.mark.parametrize("result", [
    Dialogue(kind="DIALOGUE", text="Here is a genuinely new perspective."),
    Clarification(kind="CLARIFICATION", slot="reference"),
    CapabilityGap(kind="CAPABILITY_GAP", need="navigation"),
    FactRequest(kind="FACT_REQUEST", capabilities=("ownship.position",)),
])
@pytest.mark.parametrize("delivery", ["completed", "failed", "cancelled"])
def test_context_keeps_semantics_separate_from_delivery(result, delivery):
    core, hybrid, u, req, g = make()
    final = core.execute(u, SemanticProposal(request=req, response_id="fixture", result=result), PlannerCancellationToken(), hybrid)
    core.context.accept(final, delivery=delivery, tts_started=True)
    entry = core.context.project().exchanges[-1]
    assert entry.delivery == delivery and not entry.user_heard and entry.tts_started
    assert entry.semantic_understood and entry.response_admitted
    if isinstance(result, FactRequest):
        assert entry.topic == "ownship.position" and entry.core_fact_produced
        assert entry.reply is None and entry.response_fingerprint is None
        assert "42.1" not in provider_instructions(core.context.project())
    else:
        assert entry.reply == final.text and entry.response_fingerprint
    if isinstance(result, Clarification): assert entry.clarification_slot == "reference"
    if isinstance(result, CapabilityGap): assert entry.unavailable_reason == "CAPABILITY_NOT_EXPOSED"


def test_provider_failure_remains_in_context_without_claiming_understanding():
    core, _, _, req, _ = make()
    final = core.unavailable(req, "PROVIDER_UNAVAILABLE")
    core.context.accept(final, delivery="completed")
    entry = core.context.project().exchanges[-1]
    assert not entry.semantic_understood and not entry.user_heard
    assert entry.reply == final.text


def test_optional_terminal_observer_failure_does_not_change_result():
    async def run():
        def broken(*args, **kwargs): raise OSError("offline evidence failure")
        owner = WarmYandexAircraftInterpreter(lambda: SemanticWire(GOOD), general=True, observe=broken)
        assert await owner.prepare()
        assert (await owner.interpret_general(request(), PlannerCancellationToken())).result.kind == "DIALOGUE"
        await owner.wait_isolation()
        await owner.shutdown()
    asyncio.run(run())


def test_provider_policy_has_roles_not_historical_input_phrases():
    prompt = provider_instructions()
    for text in ("как дела", "хорнет", "какие у меня координаты", "сколько у меня топлива"):
        assert text not in prompt.casefold()
    assert "verbatim repetition" in prompt and "META_REQUEST" in prompt
    assert "Core describes actual product/registry metadata" in prompt
    assert "CURRENT simulator state" in prompt


def test_existing_evidence_preserves_terminal_and_validation_only_in_test_mode():
    from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
    recorder = RealtimeTestEvidenceRecorder()
    recorder.record_conversation_slice("routing", realtime_session_id="s", raw_terminal_text=GOOD,
        parsed_terminal=GOOD, validation_path="FACT_REQUEST.capabilities.0", validation_type="literal_error")
    assert not recorder._events
    recorder.start(provider="yandex", transport="srs")
    recorder.record_conversation_slice("routing", realtime_session_id="s", raw_terminal_text=GOOD,
        parsed_terminal=GOOD, validation_path="FACT_REQUEST.capabilities.0", validation_type="literal_error",
        authorization="SECRET", audio="SECRET", provider_body={"secret":"SECRET"})
    saved = json.dumps(list(recorder._events))
    assert "SECRET" not in saved and "parsed_terminal" in saved and "literal_error" in saved


# Saved 182918 FINALs are historical replay data, NOT production input policy.
HISTORICAL_20 = [
    ("привет", "DIALOGUE", None), ("как тебя зовут", "DIALOGUE", None),
    ("что ты умеешь", "DIALOGUE", None),
    ("в каком я самолете", "FACT_REQUEST", "aircraft.identity"),
    ("какие у меня координаты", "FACT_REQUEST", "ownship.position"),
    ("какой мой текущий курс", "FACT_REQUEST", "ownship.heading"),
    ("какие у меня координаты", "FACT_REQUEST", "ownship.position"),
    ("как дела", "LOCAL_SOCIAL", None), ("расскажи что нибудь", "DIALOGUE", None),
    ("меня интересует вся информация о хорнет", "DIALOGUE", None),
    ("в какой стране я нахожусь", "CAPABILITY_GAP", None),
    ("мой вопрос относится к моему текущему местоположению", "CAPABILITY_GAP", None),
    ("в какой стране я нахожусь", "CAPABILITY_GAP", None),
    ("сколько у меня топлива", "CAPABILITY_GAP", None),
    ("какие возможности тебе доступны", "DIALOGUE", None),
    ("на каком радиоканале мы общаемся", "CAPABILITY_GAP", None),
    ("о какой речи идет речь", "CLARIFICATION", None),
    ("ты говоришь только шаблонными фразами", "DIALOGUE", None),
    ("сейчас день или ночь", "CAPABILITY_GAP", None),
    ("что еще ты умеешь", "DIALOGUE", None),
]


@pytest.mark.parametrize("source,kind,capability", HISTORICAL_20)
def test_historical_twenty_finals_normal_host_connectivity(monkeypatch, tmp_path, source, kind, capability):
    # Labels are controlled fixtures: proof of host reachability, NOT AI quality.
    from test_general_semantic_host import test_normal_host_general_replay
    test_normal_host_general_replay(monkeypatch, tmp_path, source, kind, capability)


def test_local_ambiguity_is_an_abstention_not_final_silence(monkeypatch, tmp_path):
    from test_general_semantic_host import test_normal_host_general_replay
    test_normal_host_general_replay(monkeypatch, tmp_path, "какой это самолет", "CLARIFICATION", None)


def test_tts_optional_diagnostics_do_not_change_protected_request():
    from orion.protected_streaming_tts import ProtectedStreamingTts, protected_stream_requests
    tts = ProtectedStreamingTts("unused offline")
    text = "  Fly heading zero three seven.  "
    before = [item.SerializeToString() for item in protected_stream_requests(text)]
    def fail(*a, **k): raise PermissionError("offline")
    tts.observe_diagnostic = fail
    tts._diagnostic("tts_rpc_start", tts_request_id="fixture")
    assert before == [item.SerializeToString() for item in tts._requests(text)]
    assert tts._requests(text)[1].synthesis_input.text == text
