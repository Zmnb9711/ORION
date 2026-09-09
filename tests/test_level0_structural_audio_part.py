"""Second live gate structural shape, with synthetic surrounding completion.

Live report FCC8E48F293358983AC997368ABBB2D5E6B4B90B3AD278C38B24776E367909F4
preserves content_part.added: type=audio, audio=null, index=1. The successful
text/completion tail below is an offline fixture, not claimed live evidence.
"""
import asyncio
from copy import deepcopy

import pytest

from level0_protocol_fixture import SOURCE, sequence
from test_conversation_prerequisites import Fake, setup
from orion.conversational_contracts import ConversationFailure
from orion.planner import PlannerCancellationToken
from orion.yandex_realtime_text_conversation import TextConversationProvider, _TextOperation


def live_shape():
    events = sequence()
    events[8]["part"] = {"type": "audio", "audio": None}
    return events


def test_exact_live_audio_null_part_accepted_without_text_state_change():
    op = _TextOperation(SOURCE)
    events = live_shape()
    for event in events[:8]:
        op.feed(event)
    before = (op.text, op.done_text, list(op.representations), op.terminal)
    assert op.feed(events[8]) is None
    assert (op.text, op.done_text, op.representations, op.terminal) == before
    assert op.parts[1] == "audio"


def test_live_shape_with_synthetic_completion_exact_candidate_admission_cleanup():
    async def run():
        fake = Fake(live_shape())
        provider = TextConversationProvider(lambda: fake)
        core, request = setup()
        candidate = await provider.generate(request, PlannerCancellationToken())
        final = core.admit(candidate)
        assert core.authorize(final)
        assert final.text == "  Понимаю вас. Хотите об этом поговорить?\n"
        assert fake.connected == fake.closed == 1
        assert not provider.owned and not provider.busy
    asyncio.run(run())


@pytest.mark.parametrize("part", [None, [], "audio", {}, {"type": "audio", "transcript": 123},
    {"type": "audio", "audio": ""}, {"type": "audio", "audio": "AA=="},
    {"type": "audio", "audio": b"\x00\x01"}, {"type": "audio", "audio": []},
    {"type": "audio", "audio": {}}, {"type": "audio", "audio": False},
    {"type": "audio", "audio": None, "data": "AA=="},
    {"type": "audio", "audio": None, "bytes": [0, 1]},
    {"type": "audio", "audio": None, "payload": "AA=="},
    {"type": "audio", "audio": None, "tools": [{"type": "function"}]},
    {"type": "audio", "audio": None, "function": {}},
    {"type": "function_call", "audio": None},
    {"type": "audio", "audio": None, "transcript": {}},
    {"type": "audio", "audio": None, "text": "Понимаю вас."}])
def test_malformed_or_payload_part_rejected(part):
    events = live_shape()
    events[8]["part"] = deepcopy(part)
    op = _TextOperation(SOURCE)
    with pytest.raises(ConversationFailure):
        for event in events[:9]:
            op.feed(event)
    assert op.done_text is None and not op.terminal


@pytest.mark.parametrize("mode", ["response", "item", "index", "delta_empty", "delta_payload",
    "missing_text_terminal", "transcript_only"])
def test_audio_envelope_cannot_bypass_contract(mode):
    events = live_shape()
    if mode == "response": events[8]["response_id"] = "wrong"
    elif mode == "item": events[8]["item_id"] = "wrong"
    elif mode == "index": events[8]["content_index"] = 0
    elif mode.startswith("delta"):
        delta = {**events[8], "type": "response.output_audio.delta", "delta": "" if mode == "delta_empty" else "AA=="}
        events[8] = delta
    elif mode == "missing_text_terminal":
        events = [e for e in events if e["type"] != "response.output_text.done"]
    elif mode == "transcript_only":
        events = [e for e in events if e["type"] not in {"response.output_text.done", "response.output_text.delta"}]
    async def run():
        fake = Fake(events)
        provider = TextConversationProvider(lambda: fake)
        core, request = setup()
        with pytest.raises(ConversationFailure):
            await provider.generate(request, PlannerCancellationToken())
        assert not core._finalized
        assert fake.closed == 1 and not provider.owned and not provider.busy
    asyncio.run(run())
