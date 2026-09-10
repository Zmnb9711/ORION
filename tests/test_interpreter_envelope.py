"""Exact observed terminal replay; no provider network or phrase grammar change."""
import json
from uuid import uuid4

import pytest

from orion.aircraft_interpretation import (
    AircraftProposal, InterpretationParseError, normalize_intent_envelope, parse_intent,
)
from orion.planner import PlannerCancellationToken
from test_aircraft_interpretation import NATURAL, router

BODY = '{"capability":"aircraft.identity"}'
RAW = ' ```\n{"capability":"aircraft.identity"}\n```'


@pytest.mark.parametrize("raw", [BODY, RAW, '```json\n'+BODY+'\n```',
    '\t\r\n```json \r\n'+BODY+'\r\n``` \t\r\n'])
def test_exact_envelope_body_and_bound_core_admission(raw):
    assert normalize_intent_envelope(raw) == BODY
    assert parse_intent(raw).capability == "aircraft.identity"
    class Provider:
        def interpret(self, request, cancellation):
            return AircraftProposal(request=request, response_id="recorded-response",
                                    intent=parse_intent(raw))
    core, identity, token = router(), uuid4(), PlannerCancellationToken()
    grant = core.interpret_aircraft(identity=identity, text=NATURAL[0], language="ru-RU",
                                   provider_factory=Provider, cancellation=token)
    assert grant is not None
    assert core.consume_aircraft_admission(grant, identity, NATURAL[0], token)
    assert not core.consume_aircraft_admission(grant, identity, NATURAL[0], token)


@pytest.mark.parametrize("raw,category", [
    ("Вот результат:\n"+RAW, "ENVELOPE_INVALID"),
    (RAW+"\n"+RAW, "ENVELOPE_INVALID"),
    ('```\n'+RAW+'\n```', "ENVELOPE_INVALID"),
    ('```python\n'+BODY+'\n```', "ENVELOPE_INVALID"),
    ('```JSON\n'+BODY+'\n```', "ENVELOPE_INVALID"),
    ('```\n'+BODY, "ENVELOPE_INVALID"),
    ('```\n\n```', "ENVELOPE_INVALID"),
    (RAW+" готово", "ENVELOPE_INVALID"),
    (BODY+BODY, "JSON_INVALID"),
    ('[]', "SCHEMA_INVALID"),
    ('{"capability":}', "JSON_INVALID"),
    ('{"capability":"aircraft.identity","aircraft":"F/A-18C"}', "SCHEMA_INVALID"),
    ('{"capability":"aircraft.identity","parameters":{}}', "SCHEMA_INVALID"),
    ('{"capability":"aircraft.identity","capability":"not_applicable"}', "JSON_INVALID"),
    ('{"capability":["aircraft.identity","fuel"]}', "SCHEMA_INVALID"),
    ('{"capability":"plane"}', "SCHEMA_INVALID"),
    ('{"capability":"самолет"}', "SCHEMA_INVALID"),
    ('{"capability":"aircraft_identity"}', "SCHEMA_INVALID"),
    ('x'*257, "ENVELOPE_INVALID"),
])
def test_negative_envelope_schema_matrix(raw, category):
    with pytest.raises(InterpretationParseError, match=category):
        parse_intent(raw)


def test_negative_contract_and_body_preserved_without_semantic_repair(monkeypatch):
    raw = ' \n```json\n { "capability" : "not_applicable" } \n```\t'
    expected = ' { "capability" : "not_applicable" } '
    assert normalize_intent_envelope(raw) == expected
    original, seen = json.loads, []
    def observe(text, **kwargs):
        seen.append(text)
        return original(text, **kwargs)
    monkeypatch.setattr(json, "loads", observe)
    assert parse_intent(raw).capability == "not_applicable"
    assert seen == [expected]
