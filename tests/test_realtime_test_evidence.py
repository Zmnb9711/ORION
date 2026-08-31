from __future__ import annotations

import json
import io
import wave
import zipfile
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import orion.realtime_test_evidence_api as evidence_api
from orion.app import app
from orion.build_identity import BuildIdentity
from orion.realtime_test_evidence import (
    RealtimeTestEvidenceRecorder,
    realtime_test_evidence,
)
from orion.yandex_srs_live_core import RadioSttProvider, yandex_srs_live


def test_explicit_test_session_exports_bounded_sanitized_evidence(tmp_path) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    status = recorder.start(
        provider="yandex",
        transport="srs",
        radio_stt_provider="yandex_realtime_legacy",
        build_sha="abcdef1",
    )
    assert status.active and status.test_session_id
    assert status.radio_stt_provider == "yandex_realtime_legacy"
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
        summary = archive.read("session-summary.txt").decode("utf-8")
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
    assert "radio_stt_provider=yandex_realtime_legacy" in summary
    assert not recorder.status().active


def test_recorder_is_noop_until_explicitly_started(tmp_path) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.record("response_created", response_id="not-retained")
    recorder.record_transcript("user", "must not persist", turn_id="turn_001")
    assert recorder.status().event_count == 0
    assert recorder.status().user_transcript_count == 0


def test_srs_tx_state_evidence_retains_only_bounded_safe_scalars(tmp_path) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(provider="yandex", transport="srs")
    recorder.record(
        "srs_tx_state_snapshot",
        is_sending=True,
        sending_on=1,
        is_encrypted=0,
        snapshot_age_ms=0.0,
        active_orion_turn_id="srs-ptt-000001",
        transition=True,
        suppressed_snapshot_count=4,
        valid_snapshot_count=35,
        authorization="must-not-survive",
    )
    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        raw = archive.read("events.jsonl").decode("utf-8")
    event = json.loads(raw)
    assert event["is_sending"] is True
    assert event["sending_on"] == 1
    assert event["snapshot_age_ms"] == 0.0
    assert event["active_orion_turn_id"] == "srs-ptt-000001"
    assert event["suppressed_snapshot_count"] == 4
    assert "must-not-survive" not in raw


def test_speechkit_input_wav_is_exact_and_explicitly_opted_in(tmp_path) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    pcm_blocks = (b"\x01\x00" * 320, b"\x02\x00" * 320)
    status = recorder.start(
        provider="yandex",
        transport="srs",
        radio_stt_provider="speechkit_v3_external_eou",
        capture_speechkit_stt_input_audio=True,
    )
    assert status.speechkit_stt_input_capture_enabled is True
    assert recorder.begin_speechkit_stt_input("srs-ptt-000001") is True
    assert all(
        recorder.append_speechkit_stt_input("srs-ptt-000001", block)
        for block in pcm_blocks
    )
    assert recorder.finalize_speechkit_stt_input(
        "srs-ptt-000001",
        expected_pcm_bytes=sum(map(len, pcm_blocks)),
    )

    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        name = "speechkit-stt-input/srs-ptt-000001.wav"
        assert name in archive.namelist()
        wav_bytes = archive.read(name)
        manifest = archive.read("manifest.txt").decode("utf-8")
        summary = archive.read("session-summary.txt").decode("utf-8")
    with wave.open(io.BytesIO(wav_bytes), "rb") as captured:
        assert captured.getframerate() == 16_000
        assert captured.getnchannels() == 1
        assert captured.getsampwidth() == 2
        assert captured.readframes(captured.getnframes()) == b"".join(pcm_blocks)
    assert "format_version=6" in manifest
    assert "speechkit_stt_input_audio_opt_in=true" in manifest
    assert "speechkit_stt_input_audio_included=true" in manifest
    assert "radio_received_audio_included=true" in manifest
    assert "speechkit_stt_input_capture_scope=accepted_target_channel_turns" in manifest
    assert "unrelated_srs_audio_included=NOT OBSERVABLE" in manifest
    assert "credentials_included=false" in manifest
    assert "speechkit_stt_input_audio_artifacts=1" in summary


def test_speechkit_input_audio_is_absent_by_default(tmp_path) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(provider="yandex", transport="srs")
    assert recorder.begin_speechkit_stt_input("srs-ptt-000001") is False
    assert recorder.append_speechkit_stt_input(
        "srs-ptt-000001", b"\x01\x00" * 320
    ) is False
    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        assert not any(
            name.startswith("speechkit-stt-input/") for name in archive.namelist()
        )
        manifest = archive.read("manifest.txt").decode("utf-8")
    assert "speechkit_stt_input_audio_opt_in=false" in manifest
    assert "speechkit_stt_input_audio_included=false" in manifest
    assert "radio_received_audio_included=false" in manifest


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


def test_manual_commit_wakeup_observability_is_scalar_and_privacy_bounded(
    tmp_path,
) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(provider="yandex", transport="srs")
    recorder.record(
        "provider_wakeup_create_requested",
        turn_id="turn_001",
        internal_response=True,
        output_modality="text",
        reused_as_visible_response=False,
    )
    recorder.record(
        "provider_wakeup_pcm_generated",
        response_id="wake-up-1",
        byte_count=320,
        provider_media_generated=True,
        provider_media_reached_transport=False,
    )
    output = recorder.stop_and_export()

    with zipfile.ZipFile(output) as archive:
        events = [
            json.loads(line)
            for line in archive.read("events.jsonl").decode("utf-8").splitlines()
        ]
        combined = b"".join(archive.read(name) for name in archive.namelist())

    assert events[0]["output_modality"] == "text"
    assert events[0]["internal_response"] is True
    assert events[1]["provider_media_generated"] is True
    assert events[1]["provider_media_reached_transport"] is False
    assert events[1]["byte_count"] == 320
    assert b"Authorization" not in combined
    assert b"input_audio_buffer.append" not in combined


def test_core_api_exposes_explicit_start_status_and_stop_export(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(realtime_test_evidence, "_runtime_dir", tmp_path)
    if realtime_test_evidence.status().active:
        realtime_test_evidence.stop_and_export()
    client = TestClient(app)
    started = client.post(
        "/v1/realtime/test-evidence/start",
        json={
            "provider": "yandex",
            "transport": "srs",
            "capture_speechkit_stt_input_audio": True,
        },
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


def test_core_evidence_captures_actual_speechkit_selector_and_resolved_build_sha(
    tmp_path, monkeypatch
) -> None:  # noqa: ANN001
    current_sha = "255f2007abd44885d24d8dd2e45974d2873e4b14"
    monkeypatch.setattr(realtime_test_evidence, "_runtime_dir", tmp_path)
    monkeypatch.setattr(
        evidence_api,
        "load_build_identity",
        lambda: BuildIdentity(
            current_sha,
            "dev/adr004-post-389",
            "0.2.0-alpha",
            "frozen_marker",
        ),
    )
    monkeypatch.setattr(
        yandex_srs_live,
        "status",
        lambda: SimpleNamespace(radio_stt_provider=RadioSttProvider.SPEECHKIT_V3),
    )
    if realtime_test_evidence.status().active:
        realtime_test_evidence.stop_and_export()

    client = TestClient(app)
    started = client.post(
        "/v1/realtime/test-evidence/start",
        json={
            "provider": "yandex",
            "transport": "srs",
            "capture_speechkit_stt_input_audio": True,
        },
    )
    assert started.status_code == 200
    assert started.json()["build_sha"] == current_sha
    assert started.json()["radio_stt_provider"] == "speechkit_v3_external_eou"
    assert started.json()["speechkit_stt_input_capture_enabled"] is True

    stopped = client.post("/v1/realtime/test-evidence/stop-export")
    with zipfile.ZipFile(stopped.json()["export_path"]) as archive:
        summary = archive.read("session-summary.txt").decode("utf-8")
        manifest = archive.read("manifest.txt").decode("utf-8")
    assert f"orion_build_sha={current_sha}" in summary
    assert "radio_stt_provider=speechkit_v3_external_eou" in summary
    assert "speechkit_stt_input_audio_opt_in=true" in manifest
    assert "speechkit_stt_input_audio_included=false" in manifest
