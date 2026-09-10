"""Contract/replay proof, no provider network or physical I/O."""
from datetime import UTC, datetime, timedelta
import json
from uuid import uuid4

import pytest

from orion.aircraft_interpretation import (
    AircraftIntent, AircraftProposal, InterpretationRequest, eligible_aircraft_interpretation, parse_intent, source_hash,
)
from orion.interaction_router import InteractionRouter
from orion.planner import PlannerCancellationToken
from orion.yandex_aircraft_interpreter import YandexAircraftInterpreter
from orion.yandex_qwen_planner import YandexTransportResponse
from test_interaction_router import gateway
from test_yandex_qwen_planner import FakeTransport, config

NATURAL = ("Что у нас за машина?", "На чём мы сегодня летим?", "Слушай, на чём я сейчас?")


def request(text=NATURAL[0]):
    return InterpretationRequest(interaction_id=uuid4(), operation_id=uuid4(), source_text=text,
        source_sha256=source_hash(text), deadline=datetime.now(UTC) + timedelta(seconds=10))


def body(text='{"capability":"aircraft.identity"}'):
    return {"id": "response-test", "status": "completed", "output": [
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}]}


@pytest.mark.parametrize("text", NATURAL)
def test_one_exact_text_no_context_no_tools(text):
    from orion.hybrid_aircraft_core import classify_aircraft_identity_query, HybridRoute, recognize_local_decomposition
    assert classify_aircraft_identity_query(text) is HybridRoute.UNSUPPORTED
    assert recognize_local_decomposition(text) is None
    transport = FakeTransport([YandexTransportResponse(200, body())])
    result = YandexAircraftInterpreter(config(), transport_factory=lambda _: transport).interpret(request(text), PlannerCancellationToken())
    assert result.intent.capability == "aircraft.identity"
    assert transport.closed and transport.deleted == ["response-test"]
    assert len(transport.payloads) == 1
    payload = transport.payloads[0]
    assert payload["input"] == text and payload["store"] is False
    assert not {"tools", "previous_response_id", "context", "telemetry", "audio"} & payload.keys()
    assert "F/A-18" not in json.dumps(payload)


@pytest.mark.parametrize("value", [
    '{"capability":"fuel"}', '{"capability":["aircraft.identity"]}',
    '{"capability":"aircraft.identity","aircraft":"F-16"}',
    '{"capability":"aircraft.identity","parameters":{}}',
    '{"capability":"aircraft.identity","tools":[]}',
    '{"capability":"aircraft.identity","capability":"not_applicable"}',
    'Here is your answer', '{"capability":null}', '[]', 'x'*257,
])
def test_strict_output_rejects(value):
    with pytest.raises(ValueError): parse_intent(value)


@pytest.mark.parametrize("mutation", ["tool", "audio", "role", "incomplete", "multiple", "bad_id"])
def test_provider_envelope_fail_closed_and_cleanup(mutation):
    data = body()
    if mutation == "tool": data["output"].append({"type": "function_call", "name": "test"})
    if mutation == "audio": data["output"][0]["content"][0]["type"] = "audio"
    if mutation == "role": data["output"][0]["role"] = "user"
    if mutation == "incomplete": data["status"] = "incomplete"
    if mutation == "multiple": data["output"] *= 2
    if mutation == "bad_id": data["id"] = "not a safe id"
    transport = FakeTransport([YandexTransportResponse(200, data)])
    with pytest.raises(ValueError):
        YandexAircraftInterpreter(config(), transport_factory=lambda _: transport).interpret(request(), PlannerCancellationToken())
    assert transport.closed and len(transport.payloads) == 1


class ProposalProvider:
    def __init__(self, mutation=None): self.calls, self.mutation = [], mutation
    def interpret(self, req, token):
        self.calls.append(req)
        result = AircraftProposal(request=req, response_id="test-response", intent=AircraftIntent(capability="aircraft.identity"))
        return self.mutation(result, token) if self.mutation else result


def router():
    return InteractionRouter(provider_factory=lambda: None, bounded_ownship_gateway=gateway())


@pytest.mark.parametrize("mutation", ["turn", "text", "hash", "operation", "deadline", "provider", "cancel", "failure", "none"])
def test_core_admission_negative(mutation):
    def mutate(p, token):
        if mutation == "cancel": token.cancel(); return p
        if mutation == "failure": raise RuntimeError("secret provider body")
        if mutation == "none": return p.model_copy(update={"intent": AircraftIntent(capability="not_applicable")})
        if mutation == "provider": return p.model_copy(update={"provider_id": "evil"})
        edits = {"turn": {"interaction_id": uuid4()}, "text": {"source_text": "другой текст"},
            "hash": {"source_sha256": "a"*64}, "operation": {"operation_id": uuid4()},
            "deadline": {"deadline": datetime.now(UTC)-timedelta(seconds=1)}}
        return p.model_copy(update={"request": p.request.model_copy(update=edits[mutation])})
    p, r, token = ProposalProvider(mutate), router(), PlannerCancellationToken()
    assert r.interpret_aircraft(identity=uuid4(), text=NATURAL[0], language="ru-RU", provider_factory=lambda: p, cancellation=token) is None
    assert len(p.calls) == 1


def test_core_single_use_grant_replay_and_source_binding():
    p, r, token, identity = ProposalProvider(), router(), PlannerCancellationToken(), uuid4()
    kwargs = dict(identity=identity, text=NATURAL[0], language="ru-RU", provider_factory=lambda: p, cancellation=token)
    grant = r.interpret_aircraft(**kwargs)
    assert grant is not None
    assert r.interpret_aircraft(**kwargs) is None and len(p.calls) == 1
    assert r.consume_aircraft_admission(grant, identity, NATURAL[0], token)
    assert not r.consume_aircraft_admission(grant, identity, NATURAL[0], token)


@pytest.mark.parametrize("text", ["Можно взлетать?", "Какие у меня координаты?", "Какой у меня курс?",
    "Что с топливом?", "Найди танкер.", "Разрешите посадку.", "Расскажи про F/A-18C.", "Какая погода?", "x"*501])
def test_protected_or_out_of_scope_never_calls_model(text):
    p = ProposalProvider()
    assert router().interpret_aircraft(identity=uuid4(), text=text, language="ru-RU", provider_factory=lambda: p,
                                      cancellation=PlannerCancellationToken()) is None
    assert not p.calls


def test_not_an_aircraft_positive_grammar():
    assert all(eligible_aircraft_interpretation(s, "ru-RU") for s in NATURAL)
    assert eligible_aircraft_interpretation("Что у нас там?", "ru-RU")  # Model must decline ambiguity, not force an intent.


def test_neutral_cleanup_failure_is_not_swallowed_by_core():
    from orion.aircraft_interpretation import InterpretationCleanupError
    def fail(_proposal, _token):
        raise InterpretationCleanupError("interpreter_cleanup_failed")
    with pytest.raises(InterpretationCleanupError):
        router().interpret_aircraft(identity=uuid4(), text=NATURAL[0], language="ru-RU",
            provider_factory=lambda: ProposalProvider(fail), cancellation=PlannerCancellationToken())
