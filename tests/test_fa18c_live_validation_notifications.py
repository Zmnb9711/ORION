from orion.assistant_messages import AssistantMessageQueue
from orion.fa18c_live_validation import HornetLiveValidationSnapshot
from orion.fa18c_live_validation_notifications import HornetLiveValidationNotifier


def snapshot(*, validated: bool, tacan: bool = True, comm1: bool = True, comm2: bool = True) -> HornetLiveValidationSnapshot:
    return HornetLiveValidationSnapshot(
        validated=validated,
        consecutive_valid_samples=3 if validated else 0,
        required_samples=3,
        mapping_version="fa18c-clickable-calibrated-v1",
        tacan_valid=tacan,
        comm1_valid=comm1,
        comm2_valid=comm2,
        last_issue=None if validated else "TACAN/COMM semantic state is incomplete",
    )


def test_notifier_announces_ready_transition_once() -> None:
    queue = AssistantMessageQueue()
    notifier = HornetLiveValidationNotifier(queue=queue)

    assert notifier.observe(snapshot(validated=False)) is None
    message = notifier.observe(snapshot(validated=True))
    duplicate = notifier.observe(snapshot(validated=True))

    assert message is not None
    assert message.metadata["event"] == "ready_to_fly"
    assert "Ready to Fly" in message.text
    assert duplicate is None
    assert len(queue.list()) == 1


def test_notifier_announces_which_live_semantic_state_was_lost() -> None:
    queue = AssistantMessageQueue()
    notifier = HornetLiveValidationNotifier(queue=queue)
    notifier.observe(snapshot(validated=True))

    message = notifier.observe(snapshot(validated=False, comm2=False))

    assert message is not None
    assert message.metadata["event"] == "ready_to_fly_lost"
    assert "COMM2" in message.text


def test_mapping_change_can_generate_new_ready_notification() -> None:
    queue = AssistantMessageQueue()
    notifier = HornetLiveValidationNotifier(queue=queue)
    notifier.observe(snapshot(validated=True))

    changed = snapshot(validated=True).model_copy(update={"mapping_version": "fa18c-clickable-calibrated-v2"})
    message = notifier.observe(changed)

    assert message is not None
    assert message.metadata["mapping_version"] == "fa18c-clickable-calibrated-v2"
    assert len(queue.list()) == 2


def test_english_ready_message_is_supported() -> None:
    queue = AssistantMessageQueue()
    notifier = HornetLiveValidationNotifier(queue=queue, language="en")

    message = notifier.observe(snapshot(validated=True))

    assert message is not None
    assert message.text == "F/A-18C live cockpit validation complete. ORION is Ready to Fly."
