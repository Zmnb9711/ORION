"""Recorded FINAL and bounded ASR variations, with full-source exclusion."""
import ast
from itertools import permutations
from pathlib import Path
import subprocess

import pytest

from orion.conversational_core import ConversationalCore, eligible_conversation, source_hash
from test_hybrid_aircraft import utterance


PHYSICAL_FINAL = "чтото полет сегодня тяжело идет"
STT_FINALS = [
    PHYSICAL_FINAL,
    "что то сегодня полет тяжело идет",
    "сегодня полет както тяжело идет",
    "сегодня не мой день",
    "чтото сегодня не мой день",
    "  Что‑то\tполёт сегодня тяжело идёт!\n",
    "сегодня, полет как то идет тяжело",
    "полеты сегодня тяжело идут",
    "полёты идут сегодня тяжело",
    "давно я нормально не летала",
    "я сегодня как-то не в форме",
    "сегодня всё как-то тяжеловато",
    "тяжело сегодня летится",
]
OPERATIONAL = [
    "Привет разрешите взлет.",
    "Сегодня тяжело летится какой у меня курс?",
    "Что-то не мой день можно садиться?",
    "Какой у меня самолёт?",
    "Какой мой текущий курс и координаты?",
    "Добрый день в каком самолете я нахожусь",
    "какой мой текущий вкус или оригинал",
    "Куда мне поворачивать", "Какую цель атаковать",
    "что то двигатель плохо работает", "сегодня мало топлива",
]


@pytest.mark.parametrize("text", STT_FINALS)
def test_realistic_final_and_exact_source_provenance(text):
    request = ConversationalCore().request(utterance(text))
    assert request is not None
    assert request.source_text == text
    assert request.source_sha256 == source_hash(text)


@pytest.mark.parametrize("text", OPERATIONAL)
def test_operational_and_corrupted_source_not_conversation(text):
    assert not eligible_conversation(text)


@pytest.mark.parametrize("residue", ["разрешите взлет", "какой у меня курс", "можно садиться",
    "двигатель", "топливо", "неизвестно", "не", "игнорируй инструкции"])
@pytest.mark.parametrize("text", STT_FINALS[:5])
def test_no_meaningful_residue_removed_at_any_position(text, residue):
    tokens = text.split()
    for i in range(len(tokens) + 1):
        assert not eligible_conversation(" ".join(tokens[:i] + [residue] + tokens[i:]))


def test_modifier_mobility_not_arbitrary_word_reordering():
    for particle in ("что-то", "что то", "чтото"):
        for order in permutations([particle, "сегодня", "полет", "тяжело идет"]):
            value = " ".join(order)
            assert eligible_conversation(value) == (order.index("полет") < order.index("тяжело идет"))
    for text in ("не день мой", "форме не я в", "я летала нормально не давно",
                 "сегодня сегодня не мой день", "чтото чтото не мой день",
                 "полет тяжело идут", "полеты тяжело идет", "не мой день?",
                 '"сегодня не мой день"', "сегодня не мой день. разрешите взлет",
                 "сегодня не мой день\x00", "сегодня не мой день\u202e", "x" * 501):
        assert not eligible_conversation(text)


def test_only_input_recognition_changed_against_field_build():
    path = "orion/conversational_core.py"
    before = ast.parse(subprocess.check_output(["git", "show", "c444860:" + path]).decode("utf-8"))
    after = ast.parse(Path(path).read_text(encoding="utf-8"))
    def unchanged(tree):
        return [ast.dump(n) for n in tree.body
                if not (isinstance(n, ast.FunctionDef) and n.name == "eligible_conversation")
                and not (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name)
                    and t.id in {"_INPUT", "_SOCIAL_CLAUSE", "_DISCOURSE_MODIFIERS"} for t in n.targets))]
    assert unchanged(before) == unchanged(after)


def test_all_other_production_and_packaging_frozen():
    changed = subprocess.check_output([
        "git", "diff", "c444860", "--name-only", "--", "orion", "packaging", "dcs-export"
    ]).decode().splitlines()
    from ia_scope_guard import ADDED, HUNKS, verify_ia_scope
    verify_ia_scope()
    assert set(changed) - HUNKS.keys() - ADDED == {"orion/conversational_core.py"}
    assert not set(subprocess.check_output([
        "git", "ls-files", "--others", "--exclude-standard", "--", "orion", "packaging", "dcs-export"
    ]).decode().splitlines()) - ADDED
