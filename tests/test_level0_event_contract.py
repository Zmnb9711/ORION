"""Offline DT403405 contract, projection replay and deliberate hostile mutations."""
import asyncio
from copy import deepcopy
import json

import pytest

from level0_protocol_fixture import HISTORICAL_DELTAS, SOURCE, sequence
from test_conversation_prerequisites import Fake, SAFE, SOCIAL, UNSAFE, setup
from orion.conversational_contracts import ConversationFailure
from orion.conversational_core import parse_draft
from orion.planner import PlannerCancellationToken
from orion.yandex_realtime_text_conversation import INSTRUCTIONS, TextConversationProvider, _TextOperation


def replay(seq):
    operation = _TextOperation(SOURCE)
    for event in seq:
        result = operation.feed(event)
    return operation, result


@pytest.mark.parametrize("text", SOCIAL)
@pytest.mark.parametrize("matching", [True, False])
def test_request_derived_ack_and_explicit_wrong_ack(text, matching):
    async def run():
        seq = sequence()
        ack = seq[2]["item"]
        ack["content"][0]["text"] = "deliberately wrong fixture source"
        fake = Fake(seq, echo_submitted=matching)
        provider = TextConversationProvider(lambda:fake)
        core, request = setup(text)
        if matching:
            candidate = await provider.generate(request, PlannerCancellationToken())
            assert core.authorize(core.admit(candidate))
            assert ack["content"] == fake.sent[1]["item"]["content"] == [{"type":"input_text", "text":text}]
            assert ack["content"] is not fake.sent[1]["item"]["content"]
        else:
            with pytest.raises(ConversationFailure, match="^user_item_correlation$"):
                await provider.generate(request, PlannerCancellationToken())
            assert not core._finalized
        assert fake.closed == 1 and not provider.owned
    asyncio.run(run())


def test_historical_projection_order_reconstructed_not_raw_and_not_admissible():
    seq = sequence(historical=True)
    assert len(seq) == 28
    operation, raw = replay(seq)
    assert operation.terminal and raw == "".join(HISTORICAL_DELTAS)
    assert raw.startswith(" ")
    with pytest.raises(ConversationFailure, match="invalid_candidate_schema"):
        parse_draft(raw)  # Protocol success is NOT SocialDraft/admission success.


@pytest.mark.parametrize("text", SAFE + ["  Понимаю вас.\n"])
@pytest.mark.parametrize("audio", [None, "", "absent"])
def test_structured_replay_exact_admission_and_cleanup(text, audio):
    async def run():
        seq = sequence(text)
        def replace_audio(value):
            if isinstance(value, dict):
                if "audio" in value and not isinstance(value["audio"], dict):
                    if audio == "absent": del value["audio"]
                    else: value["audio"] = audio
                for child in value.values(): replace_audio(child)
            elif isinstance(value, list):
                for child in value: replace_audio(child)
        replace_audio(seq)
        fake = Fake(seq); observed = []
        provider = TextConversationProvider(lambda: fake, observe=lambda e, **f: observed.append(e))
        core, request = setup()
        candidate = await provider.generate(request, PlannerCancellationToken())
        final = core.admit(candidate)
        assert final.text == text and core.authorize(final)
        assert fake.connected == fake.closed == 1 and not provider.owned and not provider.busy
        assert len(fake.sent) == 3
        assert fake.sent[0]["session"] == {"instructions": INSTRUCTIONS, "output_modalities": ["text"]}
        assert fake.sent[2]["response"] == {"instructions": INSTRUCTIONS, "output_modalities": ["text"]}
        assert fake.sent[1]["item"]["content"] == [{"type": "input_text", "text": SOURCE}]
        assert observed == ["connect_started", "connect_complete", "session.created", "session.updated", "connected",
                            "request_sent", "first_token", "text_complete", "terminal_text", "normalized_candidate",
                            "candidate_complete", "closed"]
    asyncio.run(run())


@pytest.mark.parametrize("position", [0, 1, 3, 27])
@pytest.mark.parametrize("value", [None, "text", [], ["audio"], ["text", "text"], ["text", 1], ["text", "video"]])
def test_bad_capabilities_fail_closed(position, value):
    seq = sequence(); key = "session" if position < 2 else "response"
    seq[position][key]["output_modalities"] = value
    with pytest.raises(ConversationFailure): replay(seq)


@pytest.mark.parametrize("position", [4, 5, 6, 8, 23, 24, 26, 27])
@pytest.mark.parametrize("payload", ["AA==", [0], {}, 0, False])
def test_payload_at_every_envelope_never_accepted(position, payload):
    seq = sequence()
    target = seq[position]
    if position in (4, 5, 6, 26): target = target["item"]
    if position in (8, 23): target = target["part"]
    if position == 27: target = target["response"]["output"][0]["content"][0]
    target["audio"] = payload
    with pytest.raises(ConversationFailure, match="audio_payload"): replay(seq)


@pytest.mark.parametrize("mode", ["audio_delta_empty", "audio_delta", "audio_late", "tool", "vad", "unknown",
    "duplicate_session", "duplicate_update", "wrong_session", "missing_session", "missing_event_id", "duplicate_response",
    "wrong_response", "missing_response", "duplicate_user", "wrong_user_text", "user_audio", "user_role",
    "assistant_role", "assistant_type", "assistant_missing_id", "assistant_other_id", "assistant_second_empty",
    "assistant_third", "multiple_item", "bad_part", "bad_content", "wrong_content_index", "bool_content_index",
    "wrong_output_index", "wrong_item", "missing_item", "duplicate_text_done", "late_text", "missing_text_done",
    "missing_delta", "mismatch", "delta_bound", "terminal_status", "terminal_other_item", "terminal_tools",
    "terminal_transcript", "terminal_whitespace", "terminal_multiple_output", "legacy_text_done", "event_replay",
    "audio_transcript_mismatch", "content_text_mismatch", "duplicate_audio_done", "duplicate_part_done"])
def test_negative_mutations(mode):
    seq = sequence()
    def insert(index, event):
        copy = deepcopy(event); copy["event_id"] = "mutation"; seq.insert(index, copy)
    if mode.startswith("audio_delta") or mode == "audio_late":
        event = deepcopy(seq[9]); event.update(type="response.output_audio.delta", delta="" if mode.endswith("empty") else "AA==")
        insert(23 if mode == "audio_late" else 9, event)
    elif mode in ("tool", "vad", "unknown"):
        seq[9]["type"] = {"tool":"response.function_call_arguments.delta", "vad":"input_audio_buffer.speech_started", "unknown":"future.event"}[mode]
    elif mode == "duplicate_session": insert(1, seq[0])
    elif mode == "duplicate_update": insert(2, seq[1])
    elif mode == "wrong_session": seq[1]["session"]["id"] = "other"
    elif mode == "missing_session": del seq[1]["session"]
    elif mode == "missing_event_id": del seq[9]["event_id"]
    elif mode == "duplicate_response": insert(4, seq[3])
    elif mode == "wrong_response": seq[9]["response_id"] = "other"
    elif mode == "missing_response": del seq[3]
    elif mode == "duplicate_user": insert(3, seq[2])
    elif mode == "wrong_user_text": seq[2]["item"]["content"][0]["text"] += " "
    elif mode == "user_audio": seq[2]["item"]["content"][0]["type"] = "input_audio"
    elif mode == "user_role": seq[2]["item"]["role"] = "system"
    elif mode == "assistant_role": seq[4]["item"]["role"] = "tool"
    elif mode == "assistant_type": seq[4]["item"]["type"] = "function_call"
    elif mode == "assistant_missing_id": del seq[4]["item"]["id"]
    elif mode == "assistant_other_id": seq[5]["item"]["id"] = "other"
    elif mode == "assistant_second_empty": seq[5]["item"]["content"] = []
    elif mode == "assistant_third": insert(6, seq[5])
    elif mode == "multiple_item": seq[6]["item"]["id"] = "other"
    elif mode == "bad_part": seq[8]["part"] = {"type":"image"}
    elif mode == "bad_content": seq[5]["item"]["content"] = {}
    elif mode == "wrong_content_index": seq[9]["content_index"] = 1
    elif mode == "bool_content_index": seq[9]["content_index"] = False
    elif mode == "wrong_output_index": seq[9]["output_index"] = 1
    elif mode == "wrong_item": seq[9]["item_id"] = "other"
    elif mode == "missing_item": del seq[9]["item_id"]
    elif mode == "duplicate_text_done": insert(23, seq[22])
    elif mode == "late_text": insert(23, seq[9])
    elif mode == "missing_text_done": del seq[22]
    elif mode == "missing_delta": del seq[9]
    elif mode == "mismatch": seq[22]["text"] += " "
    elif mode == "delta_bound": seq[9]["delta"] = "x"*4097
    elif mode == "terminal_status": seq[-1]["response"]["status"] = "cancelled"
    elif mode == "terminal_other_item": seq[-1]["response"]["output"][0]["id"] = "other"
    elif mode == "terminal_tools": seq[-1]["response"]["output"][0]["type"] = "function_call"
    elif mode in ("terminal_transcript", "terminal_whitespace"):
        seq[-1]["response"]["output"][0]["content"][0]["transcript"] += " " if mode.endswith("whitespace") else "other"
    elif mode == "terminal_multiple_output": seq[-1]["response"]["output"] *= 2
    elif mode == "legacy_text_done": seq[22]["type"] = "response.text.done"
    elif mode == "event_replay": seq[10]["event_id"] = seq[9]["event_id"]
    elif mode == "audio_transcript_mismatch": seq[25]["transcript"] = "different"
    elif mode == "content_text_mismatch": seq[21]["part"]["text"] += " "
    elif mode == "duplicate_audio_done": insert(25, seq[24])
    elif mode == "duplicate_part_done": insert(24, seq[23])
    else: raise AssertionError(mode)
    async def run():
        fake = Fake(seq); provider = TextConversationProvider(lambda:fake)
        with pytest.raises(ConversationFailure): await provider.generate(setup()[1], PlannerCancellationToken())
        assert fake.closed == 1 and not provider.owned and not provider.busy
    asyncio.run(run())


@pytest.mark.parametrize("text", UNSAFE)
def test_protocol_validity_does_not_certify_facts(text):
    async def run():
        fake = Fake(sequence(text)); provider = TextConversationProvider(lambda:fake)
        core, request = setup()
        candidate = await provider.generate(request, PlannerCancellationToken())
        if "TACAN" in text:  # Latin text shape remains outside this Russian slice.
            with pytest.raises(ConversationFailure): core.admit(candidate)
        else:
            assert core.admit(candidate).text == text
        assert fake.closed == 1 and not provider.owned
        assert set(type(candidate.draft).model_fields) == {"kind", "text"}
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["response.done", "response.output_text.delta", "response.output_audio.delta"])
def test_sealed_parser_cannot_accept_post_response_terminal(kind):
    operation, _ = replay(sequence())
    with pytest.raises(ConversationFailure, match="event_after_response_terminal"):
        operation.feed({"type":kind, "event_id":"late"})


@pytest.mark.parametrize("phase", ["text_done", "response_done", "close"])
def test_terminal_cancellation_races_return_no_candidate(phase):
    async def run():
        token = PlannerCancellationToken()
        class Cancelling(Fake):
            async def receive(self):
                event = await super().receive()
                if event["type"] == {"text_done":"response.output_text.done", "response_done":"response.done"}.get(phase): token.cancel()
                return event
            async def close(self):
                await super().close()
                if phase == "close": token.cancel()
        fake = Cancelling(sequence()); provider = TextConversationProvider(lambda:fake)
        with pytest.raises(ConversationFailure, match="cancelled"): await provider.generate(setup()[1], token)
        assert fake.closed == 1 and not provider.owned
    asyncio.run(run())


@pytest.mark.parametrize("invalid_id", [None, "", 7, "x"*201])
def test_invalid_observed_response_id_never_reaches_presentation(invalid_id):
    from test_conversation_presentation import rig
    from test_hybrid_aircraft import utterance
    async def run():
        seq = sequence()
        seq[3]["response"]["id"] = invalid_id
        fake = Fake(seq)
        voice, router, radio, tts, _ = rig(fake)
        try:
            assert await voice.run(utterance(SOURCE), PlannerCancellationToken())
            assert not voice.core._finalized
            assert not tts.texts and not radio.transmit_calls
            assert fake.closed == 1 and not voice.provider.owned
        finally:
            await voice.shutdown(); router.shutdown()
    asyncio.run(run())


def test_candidate_boundary_revalidates_absent_identity(monkeypatch):
    # Fault injection after the parser's normal validation: exercise the new
    # construction guard itself, not a cast or a schema-created fake identity.
    original = _TextOperation.feed
    def lose_identity(self, event):
        result = original(self, event)
        if result is not None:
            self.response_id = None
        return result
    monkeypatch.setattr(_TextOperation, "feed", lose_identity)
    async def run():
        fake = Fake(sequence()); provider = TextConversationProvider(lambda:fake)
        core, request = setup()
        with pytest.raises(ConversationFailure, match="^response_correlation$"):
            await provider.generate(request, PlannerCancellationToken())
        assert not core._finalized and fake.closed == 1 and not provider.owned
    asyncio.run(run())
