"""Physical A positive, physical B negative, SYNTHETIC corrected-B positive.

Historical classification is removed ONLY by this test fixture adapter. Runtime
strict parsing rejects it; neither offsets nor source text are repaired here.
"""
import ast
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import inspect
import itertools
import json
from pathlib import Path
import subprocess
from uuid import uuid4
import zipfile

import pytest

import orion.hybrid_aircraft_contracts as contracts
import orion.hybrid_aircraft_core as core
import orion.yandex_qwen_planner as qwen
from orion.planner import PlannerCancellationToken
from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
from test_hybrid_aircraft import Provider, decomposition, setup
from test_yandex_qwen_planner import FakeTransport, config

ROOT = Path(__file__).resolve().parents[1]
BASE = "4ca5effe2c5772a3268ba1f131bbad77a095c7ea"
PHYSICAL = json.loads((ROOT / "tests/fixtures/hybrid_aircraft_physical_20260908.json").read_text(encoding="utf-8"))
RESULTS = [e for e in PHYSICAL[0]["events"] if "decomposition" in e]
TEXT = next(e["transcript"] for e in PHYSICAL[0]["events"] if "transcript" in e)


def source(path):
    return subprocess.check_output(["git", "show", f"{BASE}:{path}"], cwd=ROOT).decode("utf-8")


def legacy_fixture_structure(payload):
    """Test-only old-shape conversion; discard authority, NEVER repair spans."""
    converted = deepcopy(payload)
    converted.pop("classification")
    return contracts.HybridAircraftDecomposition.model_validate_json(json.dumps(converted), strict=True)


def old_validator():
    namespace = dict(vars(contracts))
    node = next(n for n in ast.parse(source("orion/hybrid_aircraft_contracts.py")).body
                if isinstance(n, ast.ClassDef) and n.name == "HybridAircraftDecomposition")
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<exact-baseline-contract>", "exec"), namespace)
    model = namespace["HybridAircraftDecomposition"]
    namespace = dict(vars(core), HybridAircraftDecomposition=model)
    node = next(n for n in ast.parse(source("orion/hybrid_aircraft_core.py")).body
                if isinstance(n, ast.FunctionDef) and n.name == "validate_decomposition")
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<exact-baseline-validator>", "exec"), namespace)
    return model, namespace["validate_decomposition"]


@pytest.mark.parametrize("case,error", [(0, "decomposition_class_mismatch"), (1, "rejected_decomposition_has_spans")])
def test_gate01_exact_baseline_field_failures(case, error):
    model, validator = old_validator()
    with pytest.raises(ValueError, match=error):
        validator(TEXT, model.model_validate_json(json.dumps(RESULTS[case]["decomposition"]), strict=True))


def test_gate01_zip2_no_terminal_outcome_inferred():
    assert PHYSICAL[1]["kind"] == "PHYSICAL_EVIDENCE"
    assert [e["event"] for e in PHYSICAL[1]["events"]] == [
        "stt_core_boundary", "aircraft_slice.routing", "aircraft_slice.decomposition_started"]
    assert "orion_build_sha=unknown" in PHYSICAL[1]["summary"]


def test_gate02_strict_schema_roundtrip():
    schema = qwen._strict_provider_schema(contracts.HybridAircraftDecomposition.model_json_schema())
    assert set(schema["properties"]) == {"language", "spans"}
    assert set(schema["required"]) == {"language", "spans"}
    assert schema["additionalProperties"] is False
    span = schema["$defs"]["SourceSpan"]
    assert set(span["properties"]) == {"start", "end", "act"}
    assert span["additionalProperties"] is False
    value = legacy_fixture_structure(RESULTS[0]["decomposition"])
    assert contracts.HybridAircraftDecomposition.model_validate_json(value.model_dump_json(), strict=True) == value


@pytest.mark.parametrize("case", ["REAL_A", "REAL_B", "SYNTHETIC_CORRECTED_B"])
def test_gate03_required_triad(case, monkeypatch):
    payload = deepcopy(RESULTS[1 if case == "REAL_B" else 0]["decomposition"])
    if case == "SYNTHETIC_CORRECTED_B":
        payload["classification"] = "UNSUPPORTED"  # Synthetic, never claimed as observed.
    value = legacy_fixture_structure(payload)
    assert value.model_dump(mode="json")["spans"] == payload["spans"]
    derived = []
    original = core.derive_route
    def derive(checked):
        derived.append(checked)
        return original(checked)
    monkeypatch.setattr(core, "derive_route", derive)
    # Fault injection at the new candidate boundary; historical spans unchanged.
    monkeypatch.setattr(core, "recognize_local_decomposition", lambda _: value)
    c, gateway, provider, events, utterance = setup(TEXT, provider=Provider(result=value))
    result = c.run(utterance, PlannerCancellationToken())
    assert not provider.calls
    if case == "REAL_B":
        with pytest.raises(ValueError, match="invalid_social_span"):
            core.validate_decomposition(TEXT, value)
        assert not derived and not gateway.calls and result.finalized is None
        assert result.failure == "decomposition_validation"
        assert not any("core_derived_route" in fields for _, fields in events)
    else:
        assert len(derived) == len(gateway.calls) == 1
        assert result.route == contracts.HybridRoute.FREE_PLUS_AIRCRAFT_IDENTITY
        assert result.finalized.plan.aircraft.aircraft_type == "FA-18C_hornet"
        assert c.authorize(result.finalized)
    assert c.run(utterance, PlannerCancellationToken()) is result
    assert not provider.calls


@pytest.mark.parametrize("text,spans,error", [
    (TEXT, [(0, 10, "GREETING"), (11, 39, "AIRCRAFT_IDENTITY_QUERY")], "invalid_social_span"),
    (TEXT, [(0, 11, "GREETING"), (10, 39, "AIRCRAFT_IDENTITY_QUERY")], "invalid_source_span"),
    (TEXT, [(12, 39, "AIRCRAFT_IDENTITY_QUERY"), (0, 11, "GREETING")], "uncovered_source_residue"),
    (TEXT, [(0, 11, "GREETING")], "uncovered_or_excess_intent"),
    (TEXT, [(0, 40, "GREETING")], "invalid_source_span"),
    (TEXT + " и сколько топлива", [(0, 11, "GREETING"), (12, 39, "AIRCRAFT_IDENTITY_QUERY")], "uncovered_or_excess_intent"),
    (TEXT + " разрешите взлет", [(0, 11, "GREETING"), (12, 39, "AIRCRAFT_IDENTITY_QUERY")], "uncovered_or_excess_intent"),
    ("не " + TEXT, [(3, 14, "GREETING"), (15, 42, "AIRCRAFT_IDENTITY_QUERY")], "uncovered_source_residue"),
    ('"' + TEXT + '"', [(1, 12, "GREETING"), (13, 40, "AIRCRAFT_IDENTITY_QUERY")], "uncovered_source_residue"),
    ("если " + TEXT, [(5, 16, "GREETING"), (17, 44, "AIRCRAFT_IDENTITY_QUERY")], "uncovered_source_residue"),
    (TEXT + " как дела", [(0, 11, "GREETING"), (12, 39, "AIRCRAFT_IDENTITY_QUERY")], "uncovered_or_excess_intent"),
])
def test_gate04_source_negatives(text, spans, error):
    value = contracts.HybridAircraftDecomposition(language="ru-RU", spans=tuple(
        contracts.SourceSpan(start=a, end=b, act=c) for a, b, c in spans))
    with pytest.raises(ValueError, match=error): core.validate_decomposition(text, value)


@pytest.mark.parametrize("claim,text,spans,expected", [
    ("AIRCRAFT_IDENTITY", "добрый день", [(0, 11, "GREETING")], "FREE_ONLY"),
    ("FREE_ONLY", "в каком самолете я нахожусь", [(0, 27, "AIRCRAFT_IDENTITY_QUERY")], "AIRCRAFT_IDENTITY"),
    ("UNSUPPORTED", TEXT, [(0, 11, "GREETING"), (12, 39, "AIRCRAFT_IDENTITY_QUERY")], "FREE_PLUS_AIRCRAFT_IDENTITY"),
])
def test_gate05_obsolete_authority_cannot_force_or_suppress(claim, text, spans, expected):
    payload = {"classification": claim, "language": "ru-RU", "spans": [
        {"start": a, "end": b, "act": c} for a, b, c in spans]}
    with pytest.raises(ValueError):
        contracts.HybridAircraftDecomposition.model_validate_json(json.dumps(payload), strict=True)
    checked = core.validate_decomposition(text, legacy_fixture_structure(payload))
    assert core.derive_route(checked).value == expected


def test_gate05_closed_acts_matrix():
    social = [act.value for act in contracts.SocialAct]
    for count in range(5):
        for acts in itertools.product([*social, "AIRCRAFT_IDENTITY_QUERY", "FUEL_QUERY"], repeat=count):
            # Forged objects exercise the closed mapper defensively; runtime first validates schema/source.
            value = contracts.HybridAircraftDecomposition.model_construct(language="ru-RU", spans=tuple(
                contracts.SourceSpan.model_construct(start=0, end=1, act=act) for act in acts))
            a = acts.count("AIRCRAFT_IDENTITY_QUERY")
            s = [act for act in acts if act in social]
            valid = bool(acts) and "FUEL_QUERY" not in acts and a <= 1 and len(s) <= 2 and len(s) == len(set(s))
            expected = ("UNSUPPORTED" if not valid else "FREE_PLUS_AIRCRAFT_IDENTITY" if a and s
                        else "AIRCRAFT_IDENTITY" if a else "FREE_ONLY")
            assert core.derive_route(value).value == expected


@pytest.mark.parametrize("extra", ["classification", "route", "aircraft", "response_text", "heading", "tool_calls"])
def test_gate05_extra_fields_rejected(extra):
    raw = decomposition().model_dump(mode="json")
    raw[extra] = "AIRCRAFT_IDENTITY"
    with pytest.raises(ValueError): contracts.HybridAircraftDecomposition.model_validate_json(json.dumps(raw), strict=True)


def test_gate04_two_real_aircraft_spans_rejected():
    part = "в каком самолете я нахожусь"
    text = part + " " + part
    value = contracts.HybridAircraftDecomposition(language="ru-RU", spans=(
        contracts.SourceSpan(start=0, end=len(part), act="AIRCRAFT_IDENTITY_QUERY"),
        contracts.SourceSpan(start=len(part)+1, end=len(text), act="AIRCRAFT_IDENTITY_QUERY")))
    with pytest.raises(ValueError, match="uncovered_or_excess_intent"):
        core.validate_decomposition(text, value)


@pytest.mark.parametrize("case", ["REAL_A", "REAL_B", "SYNTHETIC_CORRECTED_B"])
def test_gate07_exact_field_structure_through_normal_host(monkeypatch, tmp_path, case):
    import test_hybrid_host as host_test
    payload = deepcopy(RESULTS[1 if case == "REAL_B" else 0]["decomposition"])
    if case == "SYNTHETIC_CORRECTED_B": payload["classification"] = "UNSUPPORTED"
    value = legacy_fixture_structure(payload)
    monkeypatch.setattr(host_test, "Provider", lambda **kwargs: Provider(result=value, **kwargs))
    monkeypatch.setattr(core, "recognize_local_decomposition", lambda _: value)
    # Actual FullVoiceService/Core/ToolGateway/informational TTS request builder
    # and RadioRouter; only PCM, STT terminal input and network endpoints are fake.
    host_test.test_gate10_normal_host_coexistence_and_single_owner(
        monkeypatch, tmp_path, TEXT, case != "REAL_B", 0, "active")


def test_gate08_fifteen_second_deadline_not_enlarged(monkeypatch):
    from test_hybrid_aircraft import NOW
    now = [NOW]
    def exceed(_):
        now[0] += timedelta(seconds=15.001)
        return legacy_fixture_structure(RESULTS[0]["decomposition"])
    monkeypatch.setattr(core, "recognize_local_decomposition", exceed)
    c, g, p, events, u = setup(TEXT, provider=Provider(
        result=legacy_fixture_structure(RESULTS[0]["decomposition"]), action=exceed), clock=lambda: now[0])
    result = c.run(u, PlannerCancellationToken())
    assert result.failure == "decomposition" and not result.finalized
    assert not p.calls and not g.calls
    assert not any("core_derived_route" in fields for _, fields in events)


@pytest.mark.parametrize("mode", ["success", "http_failure", "timeout", "invalid_schema", "cleanup_failure", "observer_failure"])
def test_gate08_timing_observation_preserves_single_request_cleanup(monkeypatch, mode, tmp_path):
    raw = decomposition().model_dump(mode="json")
    if mode == "invalid_schema": raw["classification"] = "FREE_PLUS_AIRCRAFT_IDENTITY"
    body = {"id": "resp-fixture", "status": "completed", "output": [
        {"type": "message", "content": [{"type": "output_text", "text": json.dumps(raw)}]}]}
    response = qwen.YandexTransportResponse(429 if mode == "http_failure" else 200, body)
    if mode == "timeout": response = qwen.YandexPlannerTransportError(qwen.YandexFailureCategory.TIMEOUT)
    transport = FakeTransport([response])
    provider = qwen.YandexQwenPlannerProvider(config(), transport_factory=lambda _: transport)
    events = []
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(provider="yandex", transport="srs")
    def observe(event, **fields):
        events.append((event, fields))
        recorder.record_aircraft_slice(event, realtime_session_id="fixture", turn_id="fixture", **fields)
        if mode == "observer_failure": raise OSError("private filesystem details")
    if mode == "cleanup_failure":
        original = qwen.YandexQwenPlannerRun.cancel
        def fail(run):
            original(run)
            raise RuntimeError("private cleanup details")
        monkeypatch.setattr(qwen.YandexQwenPlannerRun, "cancel", fail)
    kwargs = dict(observe=observe)
    args = ("  exact input  ", uuid4(), datetime.now(UTC)+timedelta(seconds=2), PlannerCancellationToken())
    if mode in {"success", "observer_failure"}:
        assert provider.decompose_aircraft(*args, **kwargs) == decomposition()
    else:
        with pytest.raises(Exception): provider.decompose_aircraft(*args, **kwargs)
    assert len(transport.payloads) == 1 and transport.closed
    assert transport.payloads[0]["input"] == args[0]
    assert events[-1][0] == "cleanup_completed"
    assert events[-1][1]["provider_category"] == ("RuntimeError" if mode == "cleanup_failure" else "completed")
    assert [e[0] for e in events] == ["provider_result_received", "cleanup_completed"]
    if mode == "timeout": assert events[0][1]["provider_category"] == qwen.YandexFailureCategory.TIMEOUT.value
    saved = json.dumps(list(recorder._events))
    assert "private" not in saved and "exact input" not in saved
    assert len(recorder._events) == len(events)


def test_gate09_new_evidence_separates_validated_core_route(tmp_path):
    c, _, _, events, u = setup(TEXT, provider=Provider(result=legacy_fixture_structure(RESULTS[0]["decomposition"])))
    c.run(u, PlannerCancellationToken())
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(provider="yandex", transport="srs")
    for name, fields in events: recorder.record_aircraft_slice(name, realtime_session_id="fixture", **fields)
    accepted = next(e for e in recorder._events if e.get("status") == "accepted")
    assert accepted["core_derived_route"] == "FREE_PLUS_AIRCRAFT_IDENTITY"
    assert set(accepted["decomposition"]) == {"language", "spans"}
    assert "route" not in accepted
    # Historical events are generic persisted JSON, not reparsed as new runtime models.
    legacy = deepcopy(RESULTS[0])
    recorder._events.append(legacy)
    with zipfile.ZipFile(recorder.stop_and_export()) as archive:
        exported = [json.loads(line) for line in archive.read("events.jsonl").splitlines()]
    assert legacy in exported and accepted in exported


def test_gate09_local_core_timing_order(monkeypatch, tmp_path):
    from test_hybrid_aircraft import NOW
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return NOW
    monkeypatch.setattr(qwen, "datetime", Clock)
    raw = legacy_fixture_structure(RESULTS[0]["decomposition"]).model_dump_json()
    body = {"id": "resp-fixture", "status": "completed", "output": [
        {"type": "message", "content": [{"type": "output_text", "text": raw}]}]}
    transport = FakeTransport([qwen.YandexTransportResponse(200, body)])
    provider = qwen.YandexQwenPlannerProvider(config(), transport_factory=lambda _: transport)
    c, gateway, _, events, u = setup(TEXT, provider=provider)
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(provider="yandex", transport="srs")
    c.observe = lambda name, **fields: recorder.record_aircraft_slice(name, realtime_session_id="fixture", **fields)
    result = c.run(u, PlannerCancellationToken())
    assert result.finalized and len(gateway.calls) == 1 and not transport.payloads
    events = list(recorder._events)
    assert [e["event"] for e in events[:6]] == ["aircraft_slice." + name for name in (
        "routing", "decomposition_started", "decomposition_completed",
        "decomposition_validation", "decomposition_validation", "authoritative_read_started")]
    assert events[3]["status"] == "checking" and events[4]["status"] == "accepted"
    assert all(e["turn_id"] == str(u.interaction_id) for e in events)
    assert [e["monotonic"] for e in events] == sorted(e["monotonic"] for e in events)
    assert events[2]["decomposition_source"] == "LOCAL"
    assert events[4]["provider_call_count"] == 0


def test_gate11_literal_span_checks_and_frozen_sources():
    before = ast.parse(source("orion/hybrid_aircraft_core.py"))
    validator = next(n for n in before.body if isinstance(n, ast.FunctionDef) and n.name == "validate_decomposition")
    validator.body = [n for n in validator.body if not (
        isinstance(n, ast.If) and "checked.classification" in ast.unparse(n.test)) and not (
        isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "expected")]
    current = ast.parse(inspect.getsource(core.validate_decomposition)).body[0]
    assert ast.dump(current) == ast.dump(validator)
    changed = subprocess.check_output(["git", "diff", BASE, "--name-only", "--", "orion", "dcs-export", "packaging"], cwd=ROOT).decode().splitlines()
    assert set(changed) <= {"orion/hybrid_aircraft_contracts.py", "orion/hybrid_aircraft_core.py",
                            "orion/yandex_qwen_planner.py", "orion/realtime_test_evidence.py"}
    # Provider transport/retry/cleanup classes and the general planner are byte-for-byte frozen.
    before = source("orion/yandex_qwen_planner.py")
    after = (ROOT / "orion/yandex_qwen_planner.py").read_text(encoding="utf-8")
    def without_extension(text):
        node = next(n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef) and n.name == "decompose_aircraft")
        lines = text.splitlines(keepends=True)
        return "".join(lines[:node.lineno-1] + lines[node.end_lineno:])
    assert without_extension(before) == without_extension(after)
