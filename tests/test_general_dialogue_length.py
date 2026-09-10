"""Output-bound regression, not a vocabulary for future blind user inputs."""
import json

import pytest

from orion.general_semantic_contracts import (
    DIALOGUE_MAX_CHARS, DIALOGUE_TARGET_CHARS, Dialogue, SemanticProposal,
    parse_semantic, provider_instructions,
)
from orion.planner import PlannerCancellationToken
from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
from test_general_semantic import make


# Exact previously rejected provider text, preserved solely as output evidence.
SAVED_351 = (
    "ORION интерпретирует запросы пользователя и отвечает в формате JSON, работая в рамках заданного набора возможностей. "
    "Сейчас он может вести диалог и запрашивать данные из ограниченного каталога (тип самолёта, координаты и курс судна), "
    "но не выполняет действий, не имеет доступа к данным о погоде, местоположении в виде названий и прочим внешним данным."
)


@pytest.mark.parametrize("text", ["x"*300, "x"*301, SAVED_351, "я"*DIALOGUE_MAX_CHARS,
                                " " + "x"*(DIALOGUE_MAX_CHARS-2) + " "])
def test_dialogue_preserved_through_core_context_tts_builder_and_evidence(text):
    from orion.informational_presentation import InformationalStreamingTts
    core, hybrid, utterance, request, gateway = make()
    result = parse_semantic(json.dumps({"kind":"DIALOGUE", "text":text}, ensure_ascii=False))
    final = core.execute(utterance, SemanticProposal(request=request, response_id="length-fixture", result=result),
                         PlannerCancellationToken(), hybrid)
    assert final.text == text and final.plan.text == text and core.authorize(final)
    assert not gateway.calls
    core.context.accept(final, delivery="unknown")
    assert core.context.project().exchanges[-1].reply == text
    assert len(core.context.project().model_dump_json().encode()) <= 4096
    assert InformationalStreamingTts("offline")._requests(final.text)[1].synthesis_input.text == text
    recorder = RealtimeTestEvidenceRecorder()
    recorder.record_conversation_slice("tts_input", realtime_session_id="fixture", tts_input=text)
    assert not recorder._events
    recorder.start(provider="yandex", transport="srs")
    recorder.record_conversation_slice("admission", realtime_session_id="fixture", candidate_text=text,
        finalized_text=text, tts_input=text, authorization="NEVER_SAVE", provider_body="NEVER_SAVE")
    assert recorder._events[-1]["tts_input"] == text
    assert recorder._events[-1]["finalized_text"] == text
    assert "NEVER_SAVE" not in json.dumps(list(recorder._events))


def test_hard_ceiling_rejects_without_truncation_and_legacy_is_unchanged():
    from orion.conversational_contracts import SocialDraft
    from test_general_stabilization import test_invalid_terminal_recovers_once_for_future_dialogue_and_fact
    bad = json.dumps({"kind":"DIALOGUE", "text":"я"*(DIALOGUE_MAX_CHARS+1)}, ensure_ascii=False)
    with pytest.raises(ValueError, match="string_too_long"):
        parse_semantic(bad)
    with pytest.raises(ValueError):
        SocialDraft(kind="social_support", text="x"*301)
    # One rejected operation, fresh owner for future requests; never same-turn retry.
    test_invalid_terminal_recovers_once_for_future_dialogue_and_fact(bad)


def test_policy_separates_style_from_validity():
    assert len(SAVED_351) == 351
    assert DIALOGUE_TARGET_CHARS == 200 and DIALOGUE_MAX_CHARS == 400
    prompt = provider_instructions()
    assert "usually <= 200" in prompt and "ceiling is 400" in prompt
    assert "not a target" in prompt and SAVED_351 not in prompt
    assert Dialogue(kind="DIALOGUE", text="x"*201)


@pytest.mark.parametrize("text", [SAVED_351, "Н"*DIALOGUE_MAX_CHARS])
def test_normal_host_long_dialogue_one_operation_exact_tts(monkeypatch, tmp_path, text):
    import orion.full_voice_service as host
    from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter
    from test_general_semantic import SemanticWire
    from test_hybrid_aircraft import Gateway
    from test_hybrid_host import test_gate10_normal_host_coexistence_and_single_owner as replay
    from test_interaction_router import gateway
    owners = []
    class Configured:
        @classmethod
        def configured(cls, *args, **kwargs):
            owner = WarmYandexAircraftInterpreter(lambda: SemanticWire(json.dumps(
                {"kind":"DIALOGUE", "text":text}, ensure_ascii=False)), **kwargs)
            owners.append(owner)
            return owner
    monkeypatch.setattr(host, "WarmYandexAircraftInterpreter", Configured)
    monkeypatch.setattr(Gateway, "definitions", lambda self: gateway().definitions(), raising=False)
    captured = []
    replay(monkeypatch, tmp_path, "Discuss how people compare competing explanations.", True, 0, "active",
           general_kind="DIALOGUE_NON_AUTHORITATIVE", expected_reads=0, capture=captured)
    events = captured[0]["events"]
    assert any(e.get("finalized_text") == text for e in events)
    assert any(e.get("tts_input") == text for e in events)
    assert captured[0]["tx_count"] == 1
    assert owners[0].operation_count == 1 and not owners[0].owned


def test_context_with_two_long_replies_stays_bounded():
    from orion.general_semantic_contracts import ContextExchange, ContextProjection
    context = ContextProjection(revision=1, session_id="fixture", exchanges=tuple(
        ContextExchange(user="Question", reply="я"*DIALOGUE_MAX_CHARS, language="ru-RU") for _ in range(2)))
    assert len(context.model_dump_json().encode()) <= 4096
