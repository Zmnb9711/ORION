from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from orion.app import app
from orion.desktop_launcher_field_fixed import FieldFixedAudioLauncher


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_source_modules_are_removed() -> None:
    for relative in (
        "orion/whisper_cpp_stt.py",
        "orion/whisper_cpp_direct_stt.py",
        "orion/whisper_voice_worker.py",
        "orion/voice_process.py",
        "orion/launcher_voice_status.py",
        "orion/voice_text_bridge_api.py",
    ):
        assert not (ROOT / relative).exists()


def test_legacy_voice_text_endpoint_is_absent() -> None:
    with TestClient(app) as client:
        response = client.post("/v1/voice/text", json={"text": "legacy"})

    assert response.status_code == 404


def test_active_realtime_provider_stop_is_requested_synchronously_before_exit() -> None:
    calls: list[tuple[str, str]] = []
    launcher = object.__new__(FieldFixedAudioLauncher)
    launcher._realtime_core_json = lambda path, *, method="GET", payload=None: calls.append((method, path)) or {}

    launcher._stop_realtime_before_exit()

    assert calls == [("POST", "/v1/realtime/live/stop")]


def test_realtime_stop_failure_does_not_block_core_shutdown_boundary() -> None:
    launcher = object.__new__(FieldFixedAudioLauncher)

    def unavailable(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise OSError("Core unavailable")

    launcher._realtime_core_json = unavailable
    launcher._stop_realtime_before_exit()


def test_build_definitions_have_no_legacy_voice_payload() -> None:
    alpha = (ROOT / ".github/workflows/alpha-build.yml").read_text(encoding="utf-8")
    installer = (ROOT / ".github/workflows/installer-smoke.yml").read_text(encoding="utf-8")
    for workflow in (alpha, installer):
        assert "--name ORION-Voice" not in workflow
        assert "whisper-bin-x64.zip" not in workflow
        assert "dist-product/Voice/whisper" not in workflow


def test_installer_removes_only_known_legacy_paths() -> None:
    source = (ROOT / "packaging/orion-alpha.iss").read_text(encoding="utf-8")

    assert 'Source: "..\\dist-product\\Voice\\*"' not in source
    assert "taskkill /F /IM ORION-Voice.exe" not in source
    assert 'Type: filesandordirs; Name: "{app}\\Voice"' in source
    assert 'Type: filesandordirs; Name: "{localappdata}\\ORION\\runtime\\voice"' in source
    assert 'Type: filesandordirs; Name: "{localappdata}\\ORION\\runtime\\stt\\whisper.cpp"' in source
