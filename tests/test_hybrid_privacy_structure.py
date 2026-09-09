"""Exact timestamp collision + deliberate leaks across Hybrid content surfaces."""
from copy import deepcopy
import json

import pytest

from hybrid_privacy_assertions import assert_aircraft_privacy
from orion.planner import PlannerCancellationToken
from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
from test_hybrid_aircraft import MIXED, setup


def surfaces(tmp_path):
    def add_extra_fact(tool):
        tool["data"]["snapshot"]["fuel"] = 9876
    core, _, _, observed, utterance = setup(MIXED, mutate=add_extra_fact)
    result = core.run(utterance, PlannerCancellationToken())
    assert result.finalized is not None
    recorder = RealtimeTestEvidenceRecorder(tmp_path, max_events=30)
    recorder.start(provider="yandex", transport="srs")
    for name, fields in observed:
        fields = {**fields, "monotonic": 69876.89}
        recorder.record_aircraft_slice(name, realtime_session_id="fixture", tool_result={"fuel":9876}, **fields)
    recorder.record_aircraft_slice("tts_input", realtime_session_id="fixture", tts_input=result.finalized.text)
    return result.finalized.model_dump(mode="json"), list(recorder._events)


def test_exact_collision_is_metadata_not_leak(tmp_path):
    final, events = surfaces(tmp_path)
    assert any(e.get("monotonic") == 69876.89 for e in events)
    # BEFORE characterization ONLY: the old assertion fails on this safe record.
    assert "9876" in json.dumps(events, ensure_ascii=False)
    # AFTER: exact fact projection + semantic fields, not serialized metadata.
    assert_aircraft_privacy(finalized=final, events=events)
    assert final["plan"]["aircraft"]["aircraft_type"] == "FA-18C_hornet"
    assert final["text"] == "Добрый день! По данным DCS, вы находитесь в F/A-18C Hornet."
    assert next(e["tts_input"] for e in events if "tts_input" in e) == final["text"]


@pytest.mark.parametrize("surface", ["selected_fact", "aircraft_name", "plan_fact", "finalized_text",
    "rendered_text", "evidence_fact", "tts_input", "provider_prompt", "provider_context", "tool_projection",
    "nested_metadata_name", "malformed_metadata", "heading_text"])
def test_deliberate_leak_is_rejected(tmp_path, surface):
    final, events = surfaces(tmp_path)
    final, events = deepcopy(final), deepcopy(events)
    if surface == "selected_fact": final["plan"]["aircraft"]["fuel"] = 9876
    elif surface == "aircraft_name": final["plan"]["aircraft"]["aircraft_type"] = "fuel=9876"
    elif surface == "plan_fact": final["plan"]["facts"] = {"fuel":9876}
    elif surface == "finalized_text": final["text"] += " fuel=9876"
    elif surface == "evidence_fact": next(e["aircraft"] for e in events if "aircraft" in e)["fuel"] = 9876
    elif surface == "tts_input": next(e for e in events if "tts_input" in e)["tts_input"] = "fuel=9876"
    elif surface == "nested_metadata_name": events.append({"semantic_facts":{"monotonic":9876}})
    elif surface == "malformed_metadata": events.append({"monotonic":{"fuel":9876}})
    elif surface == "heading_text": events.append({"tts_input":"heading 137"})
    else:
        events.append({surface: {"fuel":9876} if surface != "rendered_text" else "fuel=9876"})
    with pytest.raises(AssertionError):
        assert_aircraft_privacy(finalized=final, events=events)


@pytest.mark.parametrize("field,value", [("monotonic", 69876.89), ("frames", 9876),
    ("turn_id", "00009876-0000-4000-8000-000000000000"), ("timestamp", "2026-09-09T16:09:07.987600+00:00")])
def test_metadata_policy_not_one_timestamp_special_case(tmp_path, field, value):
    final, events = surfaces(tmp_path)
    events[0][field] = value
    final["plan"]["aircraft"]["generation"] = 9876
    assert_aircraft_privacy(finalized=final, events=events)
