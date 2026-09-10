"""Exact reviewed IA handoff hunks, not blanket exemptions for old frozen files.

Reverse ONLY the checked-in literal integration hunks, then require complete
byte identity with d324529. Historical tests still compare that recovered text
against their original checkpoint. New modifications, including inside a hunk,
fail unless separately reviewed and explicitly recorded here.
"""
import json
from pathlib import Path
import subprocess

BASE = "d3245292c176d6dc51b2a9adcb71b2e238e0b234"
ROOT = Path(__file__).resolve().parents[1]
HUNKS = json.loads((Path(__file__).with_name("ia_handoff_hunks.json")).read_text(encoding="utf-8"))
ADDED = {"orion/aircraft_interpretation.py", "orion/yandex_aircraft_interpreter.py",
         "orion/yandex_warm_aircraft_interpreter.py"}


def restore_ia(path, text):
    if path not in HUNKS:
        return text
    for hunk in reversed(HUNKS[path]):
        assert text.count(hunk["after"]) == 1, f"Unreviewed IA handoff change: {path}"
        text = text.replace(hunk["after"], hunk["before"], 1)
    original = subprocess.check_output(["git", "show", BASE + ":" + path], cwd=ROOT).decode("utf-8")
    assert text == original, f"Frozen code outside IA handoff changed: {path}"
    return text


def verify_ia_scope():
    for path in HUNKS:
        restore_ia(path, (ROOT/path).read_text(encoding="utf-8"))
    changed = set(subprocess.check_output(["git", "diff", BASE, "--name-only", "--",
        "orion", "packaging", "dcs-export"], cwd=ROOT).decode().splitlines())
    untracked = set(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "--",
        "orion", "packaging", "dcs-export"], cwd=ROOT).decode().splitlines())
    assert changed <= HUNKS.keys() | ADDED
    assert untracked <= ADDED
