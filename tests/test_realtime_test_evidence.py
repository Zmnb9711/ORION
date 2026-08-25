from __future__ import annotations

import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from orion.app import app
from orion.realtime_test_evidence import (
    RealtimeTestEvidenceRecorder,
    realtime_test_evidence,
)


def test_explicit_test_session_exports_bounded_sanitized_evidence(tmp_path) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    status = recorder.start(provider="yandex", transport="srs", build_sha="abcdef1")
    assert status.active and status.test_session_id
    recorder.record(
        "response_first_audio",
        turn_id="turn_001",
        response_id="response-1",
        context_generation=42,
        context_version="0123456789abcdef",
        response_created_to_first_audio_ms=909.0,
        provider="untrusted-override",
        transport="untrusted-override",
        latitude=31.505,
        longitude=65.847,
        transcript="private words",
        pcm=b"raw-audio",
        api_key="super-secret",
        authorization="Api-Key super-secret",
    )
    output = recorder.stop_and_export()
    assert output.name.startswith("ORION-Test-Evidence-")
    with zipfile.ZipFile(output) as archive:
        assert archive.namelist() == [
            "events.jsonl",
            "manifest.txt",
            "session-summary.txt",
        ]
        event = json.loads(archive.read("events.jsonl"))
        combined = b"".join(archive.read(name) for name in archive.namelist())
    assert event["turn_id"] == "turn_001"
    assert event["context_generation"] == 42
    assert event["provider"] == "yandex"
    assert event["transport"] == "srs"
    assert event["response_created_to_first_audio_ms"] == 909.0
    assert b"private words" not in combined
    assert b"raw-audio" not in combined
    assert b"super-secret" not in combined
    assert b"31.505" not in combined
    assert not recorder.status().active


def test_recorder_is_noop_until_explicitly_started(tmp_path) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.record("response_created", response_id="not-retained")
    assert recorder.status().event_count == 0


def test_core_api_exposes_explicit_start_status_and_stop_export(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(realtime_test_evidence, "_runtime_dir", tmp_path)
    if realtime_test_evidence.status().active:
        realtime_test_evidence.stop_and_export()
    client = TestClient(app)
    started = client.post(
        "/v1/realtime/test-evidence/start",
        json={"provider": "yandex", "transport": "srs"},
    )
    assert started.status_code == 200
    assert started.json()["active"] is True
    assert client.get("/v1/realtime/test-evidence/status").json()["active"] is True
    stopped = client.post("/v1/realtime/test-evidence/stop-export")
    assert stopped.status_code == 200
    assert stopped.json()["active"] is False
    assert Path(stopped.json()["export_path"]).exists()
