import json

from orion.config import Settings
from orion.events import EventJournal


def test_settings_defaults_and_environment(monkeypatch) -> None:
    defaults = Settings.from_env()
    assert defaults.flight_bridge_host == "127.0.0.1"
    assert defaults.flight_bridge_telemetry_port == 45100
    assert defaults.flight_bridge_command_port == 45101
    assert defaults.mission_bridge_host == "127.0.0.1"
    assert defaults.mission_bridge_port == 45200

    monkeypatch.setenv("ORION_FLIGHT_BRIDGE_HOST", "0.0.0.0")
    monkeypatch.setenv("ORION_FLIGHT_BRIDGE_TELEMETRY_PORT", "55100")
    monkeypatch.setenv("ORION_FLIGHT_BRIDGE_COMMAND_PORT", "55101")
    monkeypatch.setenv("ORION_MISSION_BRIDGE_HOST", "localhost")
    monkeypatch.setenv("ORION_MISSION_BRIDGE_PORT", "55200")
    monkeypatch.setenv("ORION_EVENT_LOG_PATH", "custom/events.jsonl")

    configured = Settings.from_env()
    assert configured.flight_bridge_host == "0.0.0.0"
    assert configured.flight_bridge_telemetry_port == 55100
    assert configured.flight_bridge_command_port == 55101
    assert configured.mission_bridge_host == "localhost"
    assert configured.mission_bridge_port == 55200
    assert configured.event_log_path == "custom/events.jsonl"


def test_event_journal_appends_jsonl_record(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    journal = EventJournal(str(path))

    journal.append("telemetry.received", {"aircraft_type": "FA-18C_hornet"})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    record = json.loads(lines[0])
    assert record["type"] == "telemetry.received"
    assert record["payload"]["aircraft_type"] == "FA-18C_hornet"
    assert record["timestamp"]
