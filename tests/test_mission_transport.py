from uuid import uuid4

from orion.mission_bridge import MissionCommand, MissionCommandType
from orion.mission_transport import DeliveryTracker


def command() -> MissionCommand:
    return MissionCommand(
        command=MissionCommandType.SMOKE,
        target_unit_id="target-1",
        smoke_color="red",
    )


def test_sequences_are_scoped_to_session() -> None:
    tracker = DeliveryTracker()
    session_a = uuid4()
    session_b = uuid4()

    first = tracker.create(session_a, command())
    second = tracker.create(session_a, command())
    other = tracker.create(session_b, command())

    assert first.envelope.sequence == 1
    assert second.envelope.sequence == 2
    assert other.envelope.sequence == 1


def test_ack_is_idempotent_and_stops_retry() -> None:
    tracker = DeliveryTracker()
    record = tracker.create(uuid4(), command())
    command_id = record.envelope.command.command_id

    assert tracker.retry(command_id).envelope.attempt == 2
    acknowledged = tracker.acknowledge(command_id)
    assert acknowledged is not None
    assert acknowledged.acknowledged is True
    first_ack_time = acknowledged.acknowledged_at

    acknowledged_again = tracker.acknowledge(command_id)
    assert acknowledged_again is not None
    assert acknowledged_again.acknowledged_at == first_ack_time
    assert tracker.retry(command_id) is None
    assert tracker.pending() == []
