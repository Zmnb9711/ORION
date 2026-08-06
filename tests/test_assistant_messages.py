import pytest

from orion.assistant_messages import (
    AssistantMessageCreate,
    AssistantMessagePriority,
    AssistantMessageQueue,
    AssistantMessageState,
)


def test_correlation_id_prevents_duplicate_spoken_message() -> None:
    queue = AssistantMessageQueue()
    payload = AssistantMessageCreate(
        text="According to the official manual...",
        source="official-knowledge",
        correlation_id="follow-up-42",
    )
    first = queue.enqueue(payload)
    second = queue.enqueue(payload)
    assert first.message_id == second.message_id
    assert len(queue.list()) == 1


def test_claim_prefers_higher_priority() -> None:
    queue = AssistantMessageQueue()
    queue.enqueue(AssistantMessageCreate(text="Normal", source="test"))
    critical = queue.enqueue(
        AssistantMessageCreate(
            text="Critical warning",
            source="threat-analyzer",
            priority=AssistantMessagePriority.CRITICAL,
        )
    )
    claimed = queue.claim_next("tts")
    assert claimed is not None
    assert claimed.message_id == critical.message_id
    assert claimed.state is AssistantMessageState.CLAIMED


def test_delivery_requires_claim_owner() -> None:
    queue = AssistantMessageQueue()
    item = queue.enqueue(AssistantMessageCreate(text="Ready", source="test"))
    queue.claim_next("tts")
    with pytest.raises(ValueError, match="claimed by this consumer"):
        queue.delivered(item.message_id, "flight-console")
    delivered = queue.delivered(item.message_id, "tts")
    assert delivered.state is AssistantMessageState.DELIVERED


def test_release_returns_message_to_queue() -> None:
    queue = AssistantMessageQueue()
    item = queue.enqueue(AssistantMessageCreate(text="Retry me", source="test"))
    queue.claim_next("tts")
    released = queue.release(item.message_id, "tts", error="Audio device unavailable")
    assert released.state is AssistantMessageState.QUEUED
    assert released.claimed_by is None
    assert released.error == "Audio device unavailable"


def test_speech_only_skips_console_only_message() -> None:
    queue = AssistantMessageQueue()
    queue.enqueue(
        AssistantMessageCreate(
            text="Full manual excerpt",
            source="official-knowledge",
            speak=False,
            show_in_console=True,
        )
    )
    assert queue.claim_next("tts", speech_only=True) is None
    assert queue.claim_next("flight-console") is not None


def test_delivered_message_cannot_be_cancelled() -> None:
    queue = AssistantMessageQueue()
    item = queue.enqueue(AssistantMessageCreate(text="Done", source="test"))
    queue.claim_next("tts")
    queue.delivered(item.message_id, "tts")
    with pytest.raises(ValueError, match="cannot be cancelled"):
        queue.cancel(item.message_id)
