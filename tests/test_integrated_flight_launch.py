from orion.app import app


def test_integrated_flight_launch_route_is_exposed() -> None:
    schema = app.openapi()

    assert "/v1/dcs-processes/launch-flight" in schema["paths"]
    assert "post" in schema["paths"]["/v1/dcs-processes/launch-flight"]


def test_sse_event_state_accepts_pydantic_console_state() -> None:
    from uuid import uuid4

    from orion.flight_console import FlightConsoleState
    from orion.flight_console_events import FlightConsoleEvent

    launch_id = uuid4()
    event = FlightConsoleEvent(
        sequence=1,
        launch_id=launch_id,
        event_type="updated",
        state=FlightConsoleState(
            launch_id=launch_id,
            profile_label="Hornet VR (OpenXR)",
            dcs_pid=1234,
            last_message="AI готов",
        ),
    )

    assert event.state["profile_label"] == "Hornet VR (OpenXR)"
    assert event.state["last_message"] == "AI готов"
