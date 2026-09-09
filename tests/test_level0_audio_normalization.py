"""Schema-aware output audio representation; live prefix, synthetic text tail.

Third live receipt 7AE7127324A6AC50B0C62EB5F3F6047B60C628598219E3705E627982FDE4BC51.
Yandex RealtimeOutputAudioPart defines optional audio/transcript string|null;
DT403405 permits transcript in text-only output as a comparison, not authority.
The observed `audio` tag is the provider alias for this output representation.
"""
import asyncio
from copy import deepcopy

import pytest

from level0_protocol_fixture import SOURCE, sequence
from test_conversation_prerequisites import Fake, setup
from orion.conversational_contracts import ConversationFailure
from orion.planner import PlannerCancellationToken
from orion.yandex_realtime_text_conversation import TextConversationProvider, _TextOperation


def third_shape():
    events = sequence()
    events[8]["part"] = {"type": "audio", "audio": None, "transcript": None}
    return events


def test_third_live_shape_preserves_all_text_state():
    op = _TextOperation(SOURCE)
    events = third_shape()
    for event in events[:8]: op.feed(event)
    before = (op.text, op.done_text, list(op.representations), op.terminal)
    assert op.feed(events[8]) is None
    assert (op.text, op.done_text, op.representations, op.terminal) == before
    assert op.parts[1] == "audio"


@pytest.mark.parametrize("audio_present", [False, True])
@pytest.mark.parametrize("transcript", ["absent", None, "", "matching"])
def test_optional_schema_fields_across_parts_items_and_terminal(audio_present, transcript):
    events = deepcopy(sequence())
    body = events[22]["text"]
    def normalize(value):
        if isinstance(value, dict):
            if value.get("type") == "output_audio":
                value.clear()
                value["type"] = "audio"
                if audio_present: value["audio"] = None
                if transcript != "absent": value["transcript"] = body if transcript == "matching" else transcript
            for child in value.values(): normalize(child)
        elif isinstance(value, list):
            for child in value: normalize(child)
    normalize(events)
    async def run():
        fake = Fake(events); provider = TextConversationProvider(lambda: fake)
        core, request = setup()
        candidate = await provider.generate(request, PlannerCancellationToken())
        assert core.authorize(core.admit(candidate))
        assert candidate.draft.text == "  Понимаю вас. Хотите об этом поговорить?\n"
        assert fake.closed == 1 and not provider.owned and not provider.busy
    asyncio.run(run())


@pytest.mark.parametrize("field,value", [("audio", "AA=="), ("audio", b"\x00\x01"),
    ("audio", [0]), ("audio", {}), ("audio", False), ("audio", ""),
    ("transcript", 0), ("transcript", False), ("transcript", []), ("transcript", {}),
    ("transcript", "x" * 4097), ("data", "AA=="), ("payload", b"\x00\x01"),
    ("unknown", None), ("unknown", {"data": "AA=="}), ("text", "unsafe text"),
    ("function", {}), ("tools", [{"type": "function"}]),
    ("item_id", "wrong"), ("response_id", "wrong"), ("content_index", 1)])
def test_field_semantics_fail_closed(field, value):
    events = third_shape(); events[8]["part"][field] = value
    op = _TextOperation(SOURCE)
    with pytest.raises(ConversationFailure):
        for event in events[:9]: op.feed(event)
    assert op.done_text is None and not op.terminal


@pytest.mark.parametrize("mode", ["missing_terminal", "transcript_only", "conflicting_transcript",
    "wrong_response", "wrong_item", "wrong_index", "audio_delta"])
def test_non_authoritative_transcript_and_binding(mode):
    events = third_shape()
    body = events[22]["text"]
    events[8]["part"]["transcript"] = body
    if mode == "missing_terminal": events = [e for e in events if e["type"] != "response.output_text.done"]
    elif mode == "transcript_only": events = [e for e in events if e["type"] not in {"response.output_text.done", "response.output_text.delta"}]
    elif mode == "conflicting_transcript": events[8]["part"]["transcript"] = "different representation"
    elif mode == "wrong_response": events[8]["response_id"] = "wrong"
    elif mode == "wrong_item": events[8]["item_id"] = "wrong"
    elif mode == "wrong_index": events[8]["content_index"] = 0
    else: events[8] = {**events[8], "type": "response.output_audio.delta", "delta": "AA=="}
    async def run():
        fake = Fake(events); provider = TextConversationProvider(lambda: fake)
        core, request = setup()
        with pytest.raises(ConversationFailure): await provider.generate(request, PlannerCancellationToken())
        assert not core._finalized and fake.closed == 1 and not provider.owned and not provider.busy
    asyncio.run(run())


def test_transcript_comparison_never_updates_authoritative_text():
    op = _TextOperation(SOURCE); events = third_shape()
    for event in events[:8]: op.feed(event)
    events[8]["part"]["transcript"] = "Понимаю вас."
    op.feed(events[8])
    assert op.text == "" and op.done_text is None and not op.terminal
    assert op.representations == ["Понимаю вас."]
