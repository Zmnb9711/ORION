"""Permanent normal-host preservation and historical six-turn regression.

All input strings are test data, never production grammar or a blind field script.
"""
import json

import pytest

import orion.full_voice_service as host
from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter
from test_general_semantic import SemanticWire
from test_hybrid_aircraft import Gateway
from test_hybrid_host import test_gate10_normal_host_coexistence_and_single_owner as replay
from test_interaction_router import gateway


HISTORICAL = [
    ("поговори со мной", "DIALOGUE", None),
    ("как настроение", "DIALOGUE", None),
    ("как дела", "DIALOGUE", None),
    ("что думаешь о сегодняшнем полете", "DIALOGUE", None),
    ("что у нас за машина", "FACT_REQUEST", "aircraft.identity"),
    ("как тебя зовут", "DIALOGUE", None),
]
DEVELOPER = [
    ("I'm curious about the way people learn new skills.", "DIALOGUE", None),
    ("Расскажи о пользе привычки задавать вопросы.", "DIALOGUE", None),
    ("Which type of machine am I piloting?", "FACT_REQUEST", "aircraft.identity"),
    ("Мне нужно текущее значение широты и долготы.", "FACT_REQUEST", "ownship.position"),
    ("Tell me our present heading.", "FACT_REQUEST", "ownship.heading"),
    ("Какая сейчас ориентация носа по горизонту?", "FACT_REQUEST", "ownship.heading"),
    ("Where is the player aircraft located, in coordinates?", "FACT_REQUEST", "ownship.position"),
    ("Explain why designers use swept wings.", "DIALOGUE", None),
    ("Какие погодные условия в этой миссии?", "CAPABILITY_GAP", None),
    ("Что с тем объектом?", "CLARIFICATION", None),
    ("Отдай команду на атаку.", "DOMAIN_REQUEST", None),
    ("Мне нужны вместе положение и текущий курс.", "FACT_REQUEST", ("ownship.position", "ownship.heading")),
]


@pytest.mark.parametrize("source,kind,capability", HISTORICAL+DEVELOPER)
def test_normal_host_general_replay(monkeypatch, tmp_path, source, kind, capability):
    body = {"kind":kind}
    if kind == "DIALOGUE": body["text"] = "Об этом интересно подумать. Могу продолжить эту тему."
    if kind == "FACT_REQUEST": body["capabilities"] = list(capability) if isinstance(capability,tuple) else [capability]
    if kind == "CAPABILITY_GAP": body["need"] = "weather"
    if kind == "CLARIFICATION": body["slot"] = "object"
    owners=[]
    class Configured:
        @classmethod
        def configured(cls,*args,**kwargs):
            owner=WarmYandexAircraftInterpreter(lambda:SemanticWire(json.dumps(body,ensure_ascii=False)),**kwargs)
            owners.append(owner)
            return owner
    monkeypatch.setattr(host,"WarmYandexAircraftInterpreter",Configured)
    monkeypatch.setattr(Gateway,"definitions",lambda self:gateway().definitions(),raising=False)
    captured=[]
    response_kind={"DIALOGUE":"DIALOGUE_NON_AUTHORITATIVE","FACT_REQUEST":"CORE_FACT_AUTHORITATIVE",
                   "CAPABILITY_GAP":"TRUTHFUL_UNAVAILABLE","CLARIFICATION":"CLARIFICATION",
                   "DOMAIN_REQUEST":"TRUTHFUL_UNAVAILABLE"}.get(kind)
    replay(monkeypatch,tmp_path,source,True,0,"active",general_kind=response_kind,
           expected_reads=int(kind=="FACT_REQUEST"),capture=captured)
    assert len(captured)==1 and captured[0]["tx_count"]==1
    assert owners[0].operation_count==1
    assert not owners[0].owned and owners[0].state=="stopped"
    if response_kind:
        event=next(e for e in captured[0]["events"] if e.get("response_kind")==response_kind)
        assert event["semantic_provider_operations"]==1
        assert event["separate_conversation_provider_operations"]==0
        assert event["planner_operations"]==0
        assert event["dialogue_role_selected"]==int(kind=="DIALOGUE")


def test_offline_provider_unavailable_is_a_response_not_silence(monkeypatch,tmp_path):
    replay(monkeypatch,tmp_path,"какой мой текущий вкус или оригинал",True,0,"active",
           general_kind="TRUTHFUL_UNAVAILABLE",expected_reads=0)


def test_general_normal_mode_retains_no_text_or_fact_events(monkeypatch,tmp_path):
    replay(monkeypatch,tmp_path,"An ordinary unresolved conversational turn.",True,0,"inactive",
           general_kind="TRUTHFUL_UNAVAILABLE",expected_reads=0)


def test_general_cleanup_failure_still_closes_borrowed_interpreter(monkeypatch,tmp_path):
    from orion.general_semantic_voice import GeneralSemanticVoice
    from orion.conversational_contracts import ConversationCleanupError
    owners=[]
    class Configured:
        @classmethod
        def configured(cls,*args,**kwargs):
            owner=WarmYandexAircraftInterpreter(lambda:SemanticWire('{"kind":"DIALOGUE","text":"A bounded reply."}'),**kwargs)
            owners.append(owner)
            return owner
    original=GeneralSemanticVoice.shutdown
    async def broken(self):
        await original(self)
        raise ConversationCleanupError('fixture_general_shutdown')
    monkeypatch.setattr(host,'WarmYandexAircraftInterpreter',Configured)
    monkeypatch.setattr(GeneralSemanticVoice,'shutdown',broken)
    with pytest.raises(ConversationCleanupError,match='fixture_general_shutdown'):
        replay(monkeypatch,tmp_path,'An unresolved natural turn.',True,0,'active',
               general_kind='DIALOGUE_NON_AUTHORITATIVE',expected_reads=0)
    assert owners and owners[0].state=='stopped' and not owners[0].owned


def test_scope_rejects_both_inside_and_outside_reviewed_hunks():
    from general_ingress_scope import ROOT, restore_general, verify_general_scope
    verify_general_scope()
    path='orion/full_voice_service.py'
    text=(ROOT/path).read_text(encoding='utf-8')
    for bad in (text+'\n# unreviewed\n',text.replace('general=True','general=False')):
        with pytest.raises(AssertionError,match='Unreviewed'):
            restore_general(path,bad)
