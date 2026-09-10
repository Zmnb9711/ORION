"""Reviewed complete files, not a mutable allowlist or broad frozen exemption.

The 2026-09-10 tranche explicitly authorizes replacing terminal whitelist misses.
These hashes freeze the reviewed integration. Historical tests run on the exact
2c58 preservation source only AFTER verifying current complete-file identity.
An additional edit inside any approved file fails just like an outside edit.

The stabilization Gate A revision adds bounded owner recovery/context and exact
Test Session terminal diagnostics. The two streaming files gain observation-only
hooks, not synthesis/radio behavior. Their complete hashes are checked before
restoration too; functional request/PCM/host replay remains a separate test gate.
"""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = '2c58b3752ad79a639db6e406e2eeb1927b21086d'
HASHES = json.loads(Path(__file__).with_name('general_ingress_hashes.json').read_text(encoding='utf-8'))
ADDED = {'orion/general_semantic_contracts.py','orion/general_semantic_core.py','orion/general_semantic_voice.py',
         'orion/general_fact_registry.py','orion/general_fact_presentation.py','orion/personal_context.py'}
CHANGED = HASHES.keys() - ADDED
SCOPE = set(HASHES)


def restore_general(path, text):
    if path not in CHANGED:
        return text
    assert hashlib.sha256(text.encode()).hexdigest() == HASHES[path], f'Unreviewed general ingress edit: {path}'
    return subprocess.check_output(['git','show',BASE+':'+path],cwd=ROOT).decode('utf-8')


def verify_general_scope():
    for path, expected in HASHES.items():
        text=(ROOT/path).read_text(encoding='utf-8')
        assert hashlib.sha256(text.encode()).hexdigest()==expected, f'Unreviewed general ingress edit: {path}'
    changed=set(subprocess.check_output(['git','diff',BASE,'--name-only','--','orion','packaging','dcs-export'],cwd=ROOT).decode().splitlines())
    untracked=set(subprocess.check_output(['git','ls-files','--others','--exclude-standard','--','orion','packaging','dcs-export'],cwd=ROOT).decode().splitlines())
    assert changed<=SCOPE, f'Frozen production changed: {changed-SCOPE}'
    assert untracked<=ADDED, f'Unreviewed production additions: {untracked-ADDED}'
