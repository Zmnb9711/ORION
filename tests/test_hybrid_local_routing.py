"""Closed-language equivalence, exact offsets and zero provider/factory calls."""
import ast
import inspect
import itertools
import json
from pathlib import Path
import subprocess

import pytest

import orion.hybrid_aircraft_core as core
from orion.hybrid_aircraft_contracts import HybridRoute
from orion.planner import PlannerCancellationToken
from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
from test_hybrid_aircraft import Gateway, NOW, setup, utterance
from test_hybrid_decomposition_contract import TEXT, RESULTS, legacy_fixture_structure

BASE = "013a36a956cb67565290c506c0e7bda0a89fdf24"
ROOT = Path(__file__).resolve().parents[1]
FORMS = [(f, "AIRCRAFT_IDENTITY_QUERY") for f in sorted(core.AIRCRAFT_FORMS)] + [
    (f, a.value) for f, a in core.SOCIAL_FORMS.items()]


def accepted_sequences():
    for size in range(1, 4):
        for sequence in itertools.product(FORMS, repeat=size):
            acts = [act for _, act in sequence]
            if len(set(acts)) == size and sum(a != "AIRCRAFT_IDENTITY_QUERY" for a in acts) <= 2:
                yield sequence


@pytest.mark.parametrize("sequence", list(accepted_sequences()))
def test_all_existing_closed_combinations_zero_factory_and_exact_spans(sequence):
    text = "! ".join(form for form, _ in sequence) + "?"
    gateway = Gateway()
    calls = []
    def forbidden():
        calls.append(True)
        raise AssertionError("Provider factory MUST NOT execute")
    service = core.HybridAircraftCore(gateway, forbidden, clock=lambda: NOW)
    u = utterance(text)
    result = service.run(u, PlannerCancellationToken())
    assert result.finalized and not result.failure and not calls
    assert len(gateway.calls) == int(any(a == "AIRCRAFT_IDENTITY_QUERY" for _, a in sequence))
    if len(sequence) > 1 or sequence[0][1] != "AIRCRAFT_IDENTITY_QUERY":
        value = core.recognize_local_decomposition(text)
        assert value is not None
        position = 0
        for span, (form, act) in zip(value.spans, sequence, strict=True):
            assert (span.start, span.end, span.act) == (position, position + len(form), act)
            assert text[span.start:span.end] == form
            position += len(form) + 2
        assert core.derive_route(core.validate_decomposition(text, value)) == result.route
    assert service.run(u, PlannerCancellationToken()) is result


@pytest.mark.parametrize("text", [
    "Добрый день! В каком самолете я нахожусь?",
    "  ДОБРЫЙ\tДЕНЬ!\r\nВ каком самолёте я нахожусь?  ",
    "Здравствуйте, какой у меня самолёт? Спасибо.",
    "В каком самолёте я нахожусь? Добрый день!",
])
def test_original_unicode_offsets_and_separators(text):
    value = core.recognize_local_decomposition(text)
    assert value and core.validate_decomposition(text, value) == value
    for span in value.spans:
        part = core.canonical(text[span.start:span.end])
        assert part in core.AIRCRAFT_FORMS or part in core.SOCIAL_FORMS
    assert core.derive_route(value) == HybridRoute.FREE_PLUS_AIRCRAFT_IDENTITY


@pytest.mark.parametrize("text", [
    "Я не спрашиваю, в каком самолёте я нахожусь.",
    "Он спросил: в каком самолёте я нахожусь?",
    "Если бы я спросил, в каком самолёте я нахожусь...",
    "Добрый день! В каком самолёте я нахожусь и сколько топлива осталось?",
    "Добрый день! В каком самолёте я нахожусь, разрешите взлёт.",
    "В каком самолёте я нахожусь и что делать дальше?",
    "Мне сказали добрый день в каком самолете я нахожусь",
    "Я не уверен, но добрый день в каком самолете я нахожусь и что дальше",
    "Повтори: в каком самолете я нахожусь",
    "Что нового?", "Расскажи что-нибудь", "Какая сегодня погода?", "Как проходит миссия?",
    "какой мой текущий вкус или оригинал", "Добрый день день", "добрыйденъ",
    "Добрый день в каком самолете я нахожусь в каком самолете я нахожусь",
    "Добрый день здравствуйте", "Спасибо как дела добрый день",
    "Добрый, день! В каком самолете я нахожусь?", '«Добрый день»',
    "добрый деньв каком самолете я нахожусь", "день добрый", "добрый ден", "", " " * 4001,
])
def test_no_partial_match_no_provider_fallback_no_read(text):
    assert core.recognize_local_decomposition(text) is None
    if not text or not text.strip():
        return  # FINAL itself disallows empty utterances.
    g = Gateway()
    calls = []
    def fail(): calls.append(True); raise AssertionError("forbidden provider")
    service = core.HybridAircraftCore(g, fail, clock=lambda: NOW)
    result = service.run(utterance(text), PlannerCancellationToken())
    assert result.route == HybridRoute.UNSUPPORTED and not result.finalized
    assert not calls and not g.calls


def test_physical_a_equivalence_and_b_stays_corrupt():
    a = legacy_fixture_structure(RESULTS[0]["decomposition"])
    b = legacy_fixture_structure(RESULTS[1]["decomposition"])
    assert core.recognize_local_decomposition(TEXT) == a
    assert [(s.start, s.end) for s in a.spans] == [(0, 11), (12, 39)]
    assert TEXT[b.spans[0].start:b.spans[0].end] == "добрый ден"
    with pytest.raises(ValueError, match="invalid_social_span"):
        core.validate_decomposition(TEXT, b)


def test_validator_then_mapper_are_mandatory(monkeypatch):
    called = []
    validator, mapper = core.validate_decomposition, core.derive_route
    def validate(text, candidate):
        called.append("validate")
        return validator(text, candidate)
    def derive(candidate):
        assert called == ["validate"]
        called.append("derive")
        return mapper(candidate)
    monkeypatch.setattr(core, "validate_decomposition", validate)
    monkeypatch.setattr(core, "derive_route", derive)
    service, g, p, _, u = setup(TEXT)
    assert service.run(u, PlannerCancellationToken()).finalized
    assert called == ["validate", "derive"] and len(g.calls) == 1 and not p.calls


@pytest.mark.parametrize("boundary", ["before", "after_local", "after_read"])
def test_cancellation_no_downstream(boundary):
    token = PlannerCancellationToken()
    service, g, p, _, u = setup(TEXT, action=token.cancel if boundary == "after_read" else None)
    def observe(event, **fields):
        if boundary == "after_local" and event == "decomposition_completed": token.cancel()
    service.observe = observe
    if boundary == "before": token.cancel()
    result = service.run(u, token)
    assert result.failure == "cancelled" and not result.finalized and not p.calls
    assert len(g.calls) == int(boundary == "after_read")


def test_local_evidence_export_timing_and_legacy_readability(tmp_path, record_property):
    service, _, _, events, u = setup(TEXT)
    assert service.run(u, PlannerCancellationToken()).finalized
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(provider="yandex", transport="srs")
    for event, fields in events:
        recorder.record_aircraft_slice(event, realtime_session_id="offline", **fields)
    by_name = {name: fields for name, fields in events}
    for name in ("decomposition_started", "decomposition_completed", "decomposition_validation"):
        assert by_name[name]["decomposition_source"] == "LOCAL"
        assert by_name[name]["provider_call_count"] == 0
    assert by_name["decomposition_validation"]["status"] == "accepted"
    for name in ("decomposition_completed", "decomposition_validation", "authoritative_read", "local_composition"):
        record_property(name + "_from_routing_ms", (by_name[name]["monotonic"] - by_name["routing"]["monotonic"]) * 1000)
    assert len(recorder._events) == len(events)
    assert recorder.stop_and_export().exists()
    with pytest.raises(ValueError):
        recorder.start(provider="yandex", transport="srs")
        recorder.record_aircraft_slice("decomposition_completed", realtime_session_id="offline", decomposition_source="invented")


def test_exact_source_invariance():
    for symbol in ("validate_decomposition", "derive_route", "classify_aircraft_identity_query",
                   "validate_aircraft", "render_informational"):
        before = subprocess.check_output(["git", "show", f"{BASE}:orion/hybrid_aircraft_core.py"], cwd=ROOT).decode()
        node = next(n for n in ast.parse(before).body if isinstance(n, ast.FunctionDef) and n.name == symbol)
        assert ast.dump(node) == ast.dump(ast.parse(inspect.getsource(getattr(core, symbol))).body[0])
    from level0_scope_guard import assert_historical_and_current_scope
    assert_historical_and_current_scope(ROOT, BASE, {"orion/hybrid_aircraft_core.py", "orion/realtime_test_evidence.py"})
