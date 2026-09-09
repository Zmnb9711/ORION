"""Fourth live candidate, grammar-bounded envelope and unchanged admission."""
import json

import pytest

from orion.conversational_contracts import ConversationalCandidate, ConversationFailure
from orion.conversational_core import parse_draft
from test_conversation_prerequisites import setup

LIVE = ' ```\n{"kind":"social_support","text":"Похоже, сегодня у вас непростой день. Бывает, что всё даётся тяжелее обычного. Я готова вас выслушать."}\n```'
BODY = '{"kind":"social_support","text":"  Понимаю вас.\\n"}'


def test_exact_fourth_live_candidate_parses_without_semantic_rewrite():
    draft = parse_draft(LIVE)
    assert draft.kind == "social_support"
    assert draft.text == "Похоже, сегодня у вас непростой день. Бывает, что всё даётся тяжелее обычного. Я готова вас выслушать."
    core, request = setup()
    candidate = ConversationalCandidate(request=request, draft=draft, provider_response_id="fixture", terminal="completed")
    # Existing positive grammar does not accept 'сегодня у вас' word order.
    # Wrapper compatibility does not authorize changing this semantic boundary.
    with pytest.raises(ConversationFailure, match="candidate_not_admitted"):
        core.admit(candidate)
    assert not core._finalized


@pytest.mark.parametrize("opening", [None, "```", "```json"])
@pytest.mark.parametrize("outer", ["", " \t\r\n"])
def test_supported_envelope_preserves_inner_text_and_admission(opening, outer):
    from orion.conversational_core import normalize_candidate_envelope
    raw = outer + (BODY if opening is None else opening + "\n" + BODY + "\n```") + outer
    normalized = normalize_candidate_envelope(raw)
    assert normalized == (raw if opening is None else BODY)
    draft = parse_draft(raw)
    assert draft.text == "  Понимаю вас.\n"
    core, request = setup()
    candidate = ConversationalCandidate(request=request, draft=draft, provider_response_id="fixture", terminal="completed")
    assert core.authorize(core.admit(candidate))


@pytest.mark.parametrize("raw", [
    "Here is JSON:\n```json\n" + BODY + "\n```",
    "```\n" + BODY + "\n```\nExplanation",
    "```\n" + BODY + "\n```\n```\n" + BODY + "\n```",
    "```\n```json\n" + BODY + "\n```\n```",
    "```python\n" + BODY + "\n```", "```JSON\n" + BODY + "\n```",
    "```json\n{bad}\n```", "```\n" + BODY + " explanation\n```",
    "```\n" + BODY + BODY + "\n```", "Some prose {with braces}",
    '```\n{"kind":"social_support","text":"Понимаю вас.","fuel":9876}\n```',
    "```\n[]\n```", "```\n\n```", "```" + BODY + "```",
    "````\n" + BODY + "\n````", "```\n" + BODY, BODY + "\n```",
    '```\n{"kind":"social_support","kind":"social_support","text":"Понимаю вас."}\n```',
    '```\n{"kind":"other","text":"Понимаю вас."}\n```',
    '```\n{"kind":"social_support","text":123}\n```',
    '```\n{"kind":"social_support","text":"' + "я" * 301 + '"}\n```',
    "x" * 4097,
])
def test_untrusted_envelopes_and_schema_stay_rejected(raw):
    with pytest.raises(ConversationFailure): parse_draft(raw)


def test_normalized_candidate_is_separate_from_exact_raw_terminal():
    from orion.conversational_core import normalize_candidate_envelope
    before = LIVE.encode("utf-8")
    inner = normalize_candidate_envelope(LIVE)
    assert LIVE.encode("utf-8") == before
    assert inner == LIVE[len(" ```\n"):-len("\n```")]
    assert json.loads(inner)["text"] == parse_draft(LIVE).text


def test_event_audio_transport_ownership_symbols_are_frozen():
    import ast
    import hashlib
    from pathlib import Path
    tree = ast.parse(Path("orion/yandex_realtime_text_conversation.py").read_text(encoding="utf-8"))
    expected = {
        "_identifier": "1d1a4d9de63c92d09b57e6e7271cbbdab486fbd6b5a300a898ca96ab229c3b88",
        "_capabilities": "ce2d39793d979950a3a6c7e4e668a1f6ed951e99c91bd4ae86e1b30e842317e3",
        "_no_audio_payload": "f168f56f2a7ee287069d028ddc99a15adb2ee5368a4ec92dd5e75092c170361b",
        "_TextOperation": "539a3fd817824b803dc90f96bfb4d273a4943ac7365976888d39f3e4c14e917b",
        "AiohttpConversationTransport": "d9b06fe099567617db3840199adc36705a2b2833b71fa0e8eab727cb189d0a28",
        "TextConversationProvider": "188992b86157dec25a8c748ac16cc191146190d45c62c805e20e5166dd32c4aa",
    }
    actual = {n.name: hashlib.sha256(ast.dump(n).encode()).hexdigest()
              for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef))}
    assert actual == expected


def test_candidate_scope_does_not_allow_admission_relaxation():
    from pathlib import Path
    import subprocess
    from level0_scope_guard import BASELINE, assert_candidate_core_scope
    before = subprocess.check_output(["git", "show", BASELINE + ":orion/conversational_core.py"]).decode("utf-8")
    after = Path("orion/conversational_core.py").read_text(encoding="utf-8")
    assert_candidate_core_scope(before, after)
    with pytest.raises(AssertionError):
        assert_candidate_core_scope(before, after.replace("not admit_social_text(checked.draft.text)", "False"))
