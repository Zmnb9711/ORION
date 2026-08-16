import json
from pathlib import Path

from orion.voice_process import VoiceProcessManager


def test_voice_status_defaults_to_stopped(tmp_path: Path) -> None:
    manager = VoiceProcessManager(tmp_path, "http://127.0.0.1:8000")
    assert manager.status()["state"] == "STOPPED"


def test_voice_state_round_trip(tmp_path: Path) -> None:
    manager = VoiceProcessManager(tmp_path, "http://127.0.0.1:8000")
    manager._write_state("LISTENING")
    payload = manager.status()
    assert payload["state"] == "LISTENING"
    assert payload["heard"] == ""
    assert payload["reply"] == ""
    raw = json.loads((tmp_path / "voice" / "state.json").read_text(encoding="utf-8"))
    assert raw["state"] == "LISTENING"


def test_voice_command_uses_python_module_when_not_frozen(tmp_path: Path) -> None:
    manager = VoiceProcessManager(tmp_path, "http://127.0.0.1:8000")
    command = manager._command()
    assert command[-2:] == ["-m", "orion.whisper_voice_worker"]
