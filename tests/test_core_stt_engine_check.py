from __future__ import annotations

from pathlib import Path

import pytest

import orion.core_main as core_main
import orion.faster_whisper_stt as stt


def test_stt_engine_check_imports_engine_without_starting_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORION_RUNTIME_DIR", str(tmp_path))
    calls: list[str] = []

    class FakeWhisperModel:
        pass

    def fake_import_engine():
        calls.append("engine")
        return FakeWhisperModel, object()

    monkeypatch.setattr(stt, "_import_engine", fake_import_engine)
    monkeypatch.setattr(core_main.uvicorn, "run", lambda *args, **kwargs: pytest.fail("uvicorn must not start"))

    assert core_main.main(["--stt-engine-check"]) == 0
    assert calls == ["engine"]
    log = (tmp_path / "core-startup.log").read_text(encoding="utf-8")
    assert "stt_engine_check_start" in log
    assert "stt_engine_check_pass" in log
