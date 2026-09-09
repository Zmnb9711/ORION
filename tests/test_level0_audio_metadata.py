"""Response metadata is not audio content. No network or audio decoding.

Live report SHA256 17DC876913337185C1430E4E3DC82BF889B69FF8D150FD05574D385F999EF81B
preserves response.created /response/audio as a one-member object ONLY. The
member was not captured. `output/voice=kirill` below is synthetic non-payload
configuration borrowed from the saved session schema, NOT recovered live data.
"""
import asyncio
from copy import deepcopy

import pytest

from level0_protocol_fixture import SOURCE, sequence
from test_conversation_prerequisites import Fake, setup
from orion.conversational_contracts import ConversationFailure
from orion.planner import PlannerCancellationToken
from orion.yandex_realtime_text_conversation import TextConversationProvider, _TextOperation


SYNTHETIC_METADATA = {"output": {"voice": "kirill"}}


def live_failure_pattern():
    events = sequence()
    events[3]["response"]["audio"] = deepcopy(SYNTHETIC_METADATA)
    return events


def test_live_failure_shape_passes_response_created_after_correction():
    operation = _TextOperation(SOURCE)
    events = live_failure_pattern()
    assert len(events[3]["response"]["audio"]) == 1
    for event in events[:4]:
        assert operation.feed(event) is None
    assert operation.response_id == "response-one"
    assert operation.done_text is None and not operation.terminal


@pytest.mark.parametrize("metadata", [None, {}, SYNTHETIC_METADATA,
    {"output": {"format": {"type": "audio/pcm", "rate": 24000}, "voice": "kirill", "speed": 1.0}},
    {"output": {"format": None, "voice": None}}])
@pytest.mark.parametrize("position", [3, 27])
def test_response_metadata_does_not_block_exact_admission(metadata, position):
    async def run():
        events = sequence()
        events[position]["response"]["audio"] = deepcopy(metadata)
        fake = Fake(events); provider = TextConversationProvider(lambda:fake)
        core, request = setup()
        candidate = await provider.generate(request, PlannerCancellationToken())
        final = core.admit(candidate)
        assert core.authorize(final)
        assert final.text == "  Понимаю вас. Хотите об этом поговорить?\n"
        assert candidate.provider_response_id == "response-one"
        assert fake.closed == 1 and not provider.owned
    asyncio.run(run())


@pytest.mark.parametrize("metadata", ["AA==", b"\x00\x01", [], 1, False, ""])
def test_response_audio_configuration_must_be_object_or_null(metadata):
    operation = _TextOperation(SOURCE)
    events = sequence()
    events[3]["response"]["audio"] = metadata
    with pytest.raises(ConversationFailure, match="^invalid_response_audio_config$"):
        for event in events[:4]: operation.feed(event)


@pytest.mark.parametrize("mode", ["delta_empty", "delta_data", "delta_wrong_response", "delta_late",
    "content_base64", "content_bytes", "content_object", "nested_audio", "root_audio",
    "metadata_tools", "wrong_response", "no_text_terminal"])
def test_metadata_exception_cannot_hide_payload_or_bypass_protocol(mode):
    events = live_failure_pattern()
    if mode.startswith("delta"):
        event = deepcopy(events[9])
        event.update(type="response.output_audio.delta", event_id="forbidden-audio",
                     delta="" if mode == "delta_empty" else "AA==")
        if mode == "delta_wrong_response": event["response_id"] = "wrong"
        events.insert(23 if mode == "delta_late" else 9, event)
    elif mode.startswith("content"):
        events[23]["part"]["audio"] = {"content_base64":"AA==", "content_bytes":b"\x00\x01", "content_object":{}}[mode]
    elif mode == "nested_audio": events[3]["response"]["audio"]["output"]["audio"] = "AA=="
    elif mode == "root_audio": events[3]["audio"] = "AA=="
    elif mode == "metadata_tools": events[3]["response"]["audio"]["output"]["tools"] = [{"type":"function"}]
    elif mode == "wrong_response": events[9]["response_id"] = "wrong"
    elif mode == "no_text_terminal": del events[22]
    async def run():
        fake = Fake(events); provider = TextConversationProvider(lambda:fake)
        core, request = setup()
        with pytest.raises(ConversationFailure): await provider.generate(request, PlannerCancellationToken())
        assert not core._finalized
        assert fake.closed == 1 and not provider.owned
    asyncio.run(run())
