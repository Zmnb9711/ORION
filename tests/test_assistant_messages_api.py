from uuid import uuid4

import pytest
from fastapi import HTTPException

from orion import assistant_messages_api as api
from orion.assistant_messages import AssistantMessageCreate, AssistantMessageQueue, AssistantMessageState


@pytest.fixture
def queue(monkeypatch) -> AssistantMessageQueue:
    instance = AssistantMessageQueue()
    monkeypatch.setattr(api, "assistant_messages", instance)
    return instance


def _payload(**overrides) -> AssistantMessageCreate:
    values = {"text": "Test message", "source": "test", "correlation_id": "corr-1"}
    values.update(overrides)
    return AssistantMessageCreate(**values)


def test_api_message_lifecycle(queue: AssistantMessageQueue) -> None:
    created = api.enqueue_message(_payload())
    duplicate = api.enqueue_message(_payload())
    assert duplicate.message_id == created.message_id
    assert api.get_message(created.message_id).state is AssistantMessageState.QUEUED
    assert api.list_messages() == [created]
    assert api.list_messages(state=AssistantMessageState.FAILED) == []

    claimed = api.claim_next_message("speaker", speech_only=True)
    assert claimed is not None
    assert claimed.message_id == created.message_id
    assert claimed.claimed_by == "speaker"

    with pytest.raises(HTTPException) as conflict:
        api.mark_message_delivered(created.message_id, "other")
    assert conflict.value.status_code == 409

    released = api.release_message(created.message_id, "speaker", error="retry")
    assert released.state is AssistantMessageState.QUEUED
    assert released.error == "retry"

    claimed_again = api.claim_next_message("speaker")
    assert claimed_again is not None
    delivered = api.mark_message_delivered(created.message_id, "speaker")
    assert delivered.state is AssistantMessageState.DELIVERED
    assert api.mark_message_delivered(created.message_id, "speaker").state is AssistantMessageState.DELIVERED

    with pytest.raises(HTTPException) as cancel_conflict:
        api.cancel_message(created.message_id)
    assert cancel_conflict.value.status_code == 409


def test_api_failure_cancel_and_not_found_paths(queue: AssistantMessageQueue) -> None:
    first = api.enqueue_message(_payload(correlation_id="fail-me"))
    failed = api.fail_message(first.message_id, "output failed")
    assert failed.state is AssistantMessageState.FAILED

    second = api.enqueue_message(_payload(correlation_id="cancel-me"))
    cancelled = api.cancel_message(second.message_id)
    assert cancelled.state is AssistantMessageState.CANCELLED

    missing = uuid4()
    with pytest.raises(HTTPException) as get_error:
        api.get_message(missing)
    assert get_error.value.status_code == 404

    with pytest.raises(HTTPException) as delivered_error:
        api.mark_message_delivered(missing, "speaker")
    assert delivered_error.value.status_code == 404

    with pytest.raises(HTTPException) as release_error:
        api.release_message(missing, "speaker")
    assert release_error.value.status_code == 404

    with pytest.raises(HTTPException) as fail_error:
        api.fail_message(missing, "boom")
    assert fail_error.value.status_code == 404

    with pytest.raises(HTTPException) as cancel_error:
        api.cancel_message(missing)
    assert cancel_error.value.status_code == 404


def test_release_rejects_wrong_consumer(queue: AssistantMessageQueue) -> None:
    created = api.enqueue_message(_payload(correlation_id="release-conflict"))
    assert api.claim_next_message("speaker") is not None
    with pytest.raises(HTTPException) as error:
        api.release_message(created.message_id, "other")
    assert error.value.status_code == 409
