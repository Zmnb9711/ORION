from uuid import uuid4

from fastapi.testclient import TestClient

from orion.app import app
from orion.flight_console import FlightConsoleState
from orion.flight_console_api import _format_sse
from orion.flight_console_events import FlightConsoleEvent


def test_format_sse_includes_id_type_and_json_data() -> None:
    launch_id = uuid4()
    event = FlightConsoleEvent(
        sequence=42,
        launch_id=launch_id,
        event_type="updated",
        state=FlightConsoleState(
            launch_id=launch_id,
            profile_label="Hornet VR (OpenXR)",
            dcs_pid=1234,
            last_message="AI готов",
        ),
    )

    frame = _format_sse(event)

    assert frame.startswith("id: 42\nevent: updated\ndata: ")
    assert str(launch_id) in frame
    assert "AI готов" in frame
    assert frame.endswith("\n\n")


def test_sse_route_is_exposed_in_openapi() -> None:
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    assert "/v1/flight-console/stream" in schema["paths"]
    parameters = schema["paths"]["/v1/flight-console/stream"]["get"]["parameters"]
    names = {parameter["name"] for parameter in parameters}
    assert {"after", "launch_id", "heartbeat_seconds"}.issubset(names)
