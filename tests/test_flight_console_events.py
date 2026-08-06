from uuid import uuid4

from orion.flight_console_events import FlightConsoleEventStream


def test_event_stream_supports_cursor_filter_and_limit() -> None:
    stream = FlightConsoleEventStream(max_events=10)
    first_launch = uuid4()
    second_launch = uuid4()

    first = stream.publish("created", first_launch, {"dcs_running": True})
    stream.publish("updated", second_launch, {"dcs_running": True})
    third = stream.publish("updated", first_launch, {"last_message": "Ready"})

    events = stream.read_after(sequence=first.sequence, launch_id=first_launch, limit=10)

    assert [event.sequence for event in events] == [third.sequence]
    assert events[0].state["last_message"] == "Ready"
    assert stream.latest_sequence == third.sequence


def test_event_stream_keeps_bounded_history() -> None:
    stream = FlightConsoleEventStream(max_events=2)
    launch_id = uuid4()

    first = stream.publish("one", launch_id, {})
    stream.publish("two", launch_id, {})
    stream.publish("three", launch_id, {})

    events = stream.read_after(sequence=0)

    assert len(events) == 2
    assert all(event.sequence > first.sequence for event in events)
