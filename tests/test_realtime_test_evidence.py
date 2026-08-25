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
        manifest = archive.read("manifest.txt").decode("utf-8")
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
    assert "user_transcript_observability=NOT OBSERVABLE" in manifest
    assert "assistant_transcript_observability=NOT OBSERVABLE" in manifest
    assert not recorder.status().active


def test_recorder_is_noop_until_explicitly_started(tmp_path) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.record("response_created", response_id="not-retained")
    recorder.record_transcript("user", "must not persist", turn_id="turn_001")
    assert recorder.status().event_count == 0
    assert recorder.status().user_transcript_count == 0


def test_explicit_session_records_ordered_correlated_provider_transcripts(tmp_path) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(provider="yandex", transport="srs")
    recorder.record("flight_context_applied", context_version="context-123")
    recorder.record_transcript(
        "user",
        "Какая у меня скорость?",
        turn_id="turn_001",
        event_id="event-user",
        provider_item_id="item-user",
    )
    recorder.record_transcript(
        "assistant",
        "Ваша текущая скорость — двести узлов.",
        turn_id="turn_001",
        response_id="response-1",
        event_id="event-assistant",
        provider_item_id="item-assistant",
    )
    status = recorder.status()
    assert status.user_transcript_count == 1
    assert status.assistant_transcript_count == 1

    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        events = [
            json.loads(line)
            for line in archive.read("events.jsonl").decode("utf-8").splitlines()
        ]
        manifest = archive.read("manifest.txt").decode("utf-8")
        summary = archive.read("session-summary.txt").decode("utf-8")
    transcripts = [event for event in events if event["event"].endswith("_transcript")]
    assert [event["event"] for event in transcripts] == [
        "user_transcript",
        "assistant_transcript",
    ]
    assert transcripts[0] == {
        **{key: transcripts[0][key] for key in ("provider", "test_session_id", "timestamp", "transport")},
        "context_version": "context-123",
        "event": "user_transcript",
        "event_id": "event-user",
        "provider_item_id": "item-user",
        "transcript": "Какая у меня скорость?",
        "turn_id": "turn_001",
    }
    assert transcripts[1]["response_id"] == "response-1"
    assert transcripts[1]["turn_id"] == "turn_001"
    assert "user_transcripts_included=true" in manifest
    assert "assistant_transcripts_included=true" in manifest
    assert "raw_audio_included=false" in manifest
    assert "credentials_included=false" in manifest
    assert "user_transcript_count=1" in summary
    assert "assistant_transcript_count=1" in summary


def test_transcript_capture_redacts_credentials_and_never_accepts_prompt_or_audio(tmp_path) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(provider="qwen", transport="direct")
    recorder.record(
        "provider_event",
        transcript="ordinary-record-transcript",
        instructions="SYSTEM PROMPT SENTINEL",
        prompt="SYSTEM PROMPT SENTINEL",
        audio="RAW AUDIO SENTINEL",
        api_key="KEY SENTINEL",
    )
    recorder.record_transcript(
        "user",
        "мой api-key=secret-value и Bearer bearer-value",
    )
    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        combined = b"".join(archive.read(name) for name in archive.namelist())
    assert b"SYSTEM PROMPT SENTINEL" not in combined
    assert b"RAW AUDIO SENTINEL" not in combined
    assert b"KEY SENTINEL" not in combined
    assert b"ordinary-record-transcript" not in combined
    assert b"secret-value" not in combined
    assert b"bearer-value" not in combined
    assert b"[REDACTED]" in combined


def test_transcripts_share_the_existing_event_bound(tmp_path) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path, max_events=2)
    recorder.start(provider="yandex", transport="direct")
    recorder.record("response_created", response_id="r1")
    recorder.record_transcript("user", "one", turn_id="turn_001")
    recorder.record_transcript("assistant", "two", response_id="r1")
    status = recorder.status()
    assert status.event_count == 2
    assert status.dropped_event_count == 1


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
    duplicate = client.post(
        "/v1/realtime/test-evidence/start",
        json={"provider": "yandex", "transport": "srs"},
    )
    assert duplicate.status_code == 409
    assert client.get("/v1/realtime/test-evidence/status").json()["active"] is True
    stopped = client.post("/v1/realtime/test-evidence/stop-export")
    assert stopped.status_code == 200
    assert stopped.json()["active"] is False
    assert Path(stopped.json()["export_path"]).exists()
