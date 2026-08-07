from uuid import uuid4

from orion.dcs_process import DcsProcessRecord, ProcessState
from orion.flight_console import (
    FlightConsoleCreate,
    FlightConsoleStore,
    FlightConsoleUpdate,
)


def test_flight_console_tracks_process_and_status(monkeypatch) -> None:
    launch_id = uuid4()
    profile_id = uuid4()
    process = DcsProcessRecord(
        launch_id=launch_id,
        profile_id=profile_id,
        pid=4242,
        executable="DCS.exe",
        arguments=["--force_enable_VR", "--force_OpenXR"],
    )

    monkeypatch.setattr("orion.flight_console.dcs_processes.get", lambda _: process)
    store = FlightConsoleStore()
    state = store.create(
        FlightConsoleCreate(
            launch_id=launch_id,
            profile_label="Hornet VR (OpenXR)",
            mission_name="Operation Desert",
            map_name="Persian Gulf",
            aircraft_name="F/A-18C Hornet",
        )
    )

    assert state.dcs_pid == 4242
    assert state.dcs_running is True
    assert state.ai_status == "AI готов"

    updated = store.update(
        launch_id,
        FlightConsoleUpdate(
            flight_bridge_connected=True,
            mission_bridge_connected=True,
            mission_pack_connected=True,
            voice_active=True,
            last_command="Запросить танкер",
            last_command_status="Texaco 1-1 найден",
            last_message="До танкера 26 морских миль",
        ),
    )

    assert updated is not None
    assert updated.flight_bridge_connected is True
    assert updated.last_command == "Запросить танкер"
    assert updated.last_message == "До танкера 26 морских миль"

    exited = process.model_copy(update={"state": ProcessState.EXITED, "exit_code": 0})
    monkeypatch.setattr("orion.flight_console.dcs_processes.get", lambda _: exited)
    refreshed = store.get(launch_id)

    assert refreshed is not None
    assert refreshed.dcs_running is False
    assert refreshed.dcs_exit_code == 0


def test_flight_console_rejects_unknown_launch(monkeypatch) -> None:
    monkeypatch.setattr("orion.flight_console.dcs_processes.get", lambda _: None)
    store = FlightConsoleStore()

    try:
        store.create(
            FlightConsoleCreate(
                launch_id=uuid4(),
                profile_label="Hornet VR (OpenXR)",
            )
        )
    except KeyError as exc:
        assert "launch" in str(exc).lower()
    else:
        raise AssertionError("Expected unknown launch to be rejected")
