"""Fictional profile fixtures only; no real personal name in source/build."""
import asyncio
from datetime import UTC, datetime, timedelta
import json

import pytest

from orion.personal_context import load_personal_context
from orion.general_semantic_contracts import provider_instructions
from orion.planner import PlannerCancellationToken
from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter
from test_general_semantic import make, SemanticWire


def write_profile(path, authority="USER_PROVIDED"):
    path.write_text(json.dumps({"schema_version":"orion.user-context.v1", "facts":[{
        "fact_id":"fixture-1", "statement":"The user's sister is named Mira.",
        "authority":authority, "source":"EXPLICIT_USER_AUTHORIZATION"}]}), encoding="utf-8")


def test_persistent_authority_is_separate_from_recent_and_simulator_context(monkeypatch, tmp_path):
    monkeypatch.setenv("ORION_RUNTIME_DIR", str(tmp_path))
    file = tmp_path/"personal-context.json"
    write_profile(file)
    core, _, _, req, _ = make()
    assert req.personal_context.facts[0].authority == "USER_PROVIDED"
    assert not req.context.exchanges
    core.context.reset("other-aircraft")
    second = make()[3]
    assert req.personal_context == second.personal_context
    assert "Mira" not in req.context.model_dump_json()
    prompt = provider_instructions(req.context, req.personal_context)
    assert "Mira" in prompt and "infer no additional facts" in prompt
    assert "CURRENT simulator state" in prompt


@pytest.mark.parametrize("authority", ["DCS_AUTHORITATIVE", "MODEL_KNOWLEDGE", "INFERRED"])
def test_non_user_authority_is_not_admitted(tmp_path, authority):
    file = tmp_path/"personal-context.json"
    write_profile(file, authority)
    assert not load_personal_context(file).facts


def test_invalid_and_missing_profile_do_not_break_voice_context(tmp_path):
    file = tmp_path/"personal-context.json"
    assert not load_personal_context(file).facts
    for text in ("invalid", "x"*4097, '{}'):
        file.write_text(text, encoding="utf-8")
        assert not load_personal_context(file).facts


def test_explicit_profile_reaches_single_semantic_operation(monkeypatch, tmp_path):
    monkeypatch.setenv("ORION_RUNTIME_DIR", str(tmp_path))
    write_profile(tmp_path/"personal-context.json")
    req = make()[3]
    now = datetime.now(UTC)
    req = req.model_copy(update={"created_at":now, "deadline":now+timedelta(seconds=12)})
    async def run():
        wire = SemanticWire('{"kind":"DIALOGUE","text":"Your sister is named Mira."}')
        owner = WarmYandexAircraftInterpreter(lambda:wire, general=True)
        assert await owner.prepare()
        result = await owner.interpret_general(req, PlannerCancellationToken())
        assert result.request.personal_context == req.personal_context
        creates = [item for item in wire.sent if item["type"] == "response.create"]
        assert len(creates) == 1 and "Mira" in creates[0]["response"]["instructions"]
        await owner.wait_isolation()
        await owner.shutdown()
        assert owner.operation_count == 1 and not owner.owned
    asyncio.run(run())
