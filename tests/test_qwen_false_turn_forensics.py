from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from orion.qwen_live_audio_core import QwenLiveAudioService, _audio_session_update
from orion.qwen_live_diagnostics import QwenLiveDiagnostics


START_NS = 5_000_000_000


def _recorder(tmp_path: Path) -> QwenLiveDiagnostics:
    recorder = QwenLiveDiagnostics(
        model="qwen3.5-omni-flash-realtime",
        region="singapore",
        vad_type="server_vad",
        silence_duration_ms=800,
        qwen_input_rate=16_000,
        qwen_output_rate=24_000,
        runtime_dir=tmp_path,
        start_ns=START_NS,
        start_utc=datetime(2026, 8, 22, tzinfo=UTC),
        session_id="false-turn-test",
    )
    recorder.update_audio_metadata(
        input_device="Dream Air MME input",
        output_device="Dream Air MME output",
        input_native_rate=16_000,
        output_native_rate=24_000,
        duplex_rate=None,
        block_frames=640,
        block_duration_ms=40,
    )
    return recorder


def _observe(
    recorder: QwenLiveDiagnostics, offset_ms: int, event: dict[str, object]
) -> None:
    recorder.record_turn_event(event, t_ns=START_NS + offset_ms * 1_000_000)


def test_turn_timeline_correlates_unicode_transcript_playback_and_signal(
    tmp_path: Path,
) -> None:
    recorder = _recorder(tmp_path)
    recorder.record_input_levels(
        t_ns=START_NS + 100_000_000, rms=0.002, peak=0.004
    )
    _observe(
        recorder,
        200,
        {
            "type": "response.created",
            "event_id": "evt-old-response",
            "response": {"id": "resp-old"},
        },
    )
    _observe(
        recorder,
        210,
        {
            "type": "response.audio_transcript.done",
            "event_id": "evt-old-text",
            "response_id": "resp-old",
            "item_id": "assistant-old",
            "output_index": 0,
            "content_index": 0,
            "transcript": "Проверка собственного эха",
        },
    )
    _observe(
        recorder,
        220,
        {
            "type": "response.audio.delta",
            "event_id": "evt-old-audio",
            "response_id": "resp-old",
            "item_id": "assistant-old",
            "delta": "not-retained-provider-pcm",
        },
    )
    recorder.record_audio_delta(
        receive_ns=START_NS + 220_000_000,
        encoded_chars=25,
        decoded_bytes=960,
        source_rate=24_000,
        resample_start_ns=START_NS + 220_100_000,
        resample_end_ns=START_NS + 220_200_000,
        resampled_bytes=960,
        target_rate=24_000,
        response_id="resp-old",
        item_id="assistant-old",
    )
    recorder.record_playback_enqueue(
        t_ns=START_NS + 221_000_000,
        before_bytes=0,
        after_bytes=960,
        sample_rate=24_000,
        added_bytes=960,
    )
    recorder.record_playback_write_start(
        t_ns=START_NS + 225_000_000,
        buffer_after_bytes=480,
        response_audio_bytes=480,
        sample_rate=24_000,
    )

    _observe(
        recorder,
        230,
        {
            "type": "input_audio_buffer.speech_started",
            "event_id": "evt-speech-start",
            "item_id": "item-user-1",
            "audio_start_ms": 230,
        },
    )
    recorder.record_input_levels(
        t_ns=START_NS + 240_000_000, rms=0.10, peak=0.25
    )
    recorder.record_input_levels(
        t_ns=START_NS + 280_000_000, rms=0.20, peak=0.50
    )
    _observe(
        recorder,
        300,
        {
            "type": "input_audio_buffer.speech_stopped",
            "event_id": "evt-speech-stop",
            "item_id": "item-user-1",
            "audio_end_ms": 300,
        },
    )
    _observe(
        recorder,
        305,
        {
            "type": "input_audio_buffer.committed",
            "event_id": "evt-committed",
            "item_id": "item-user-1",
            "previous_item_id": "assistant-old",
        },
    )
    _observe(
        recorder,
        310,
        {
            "type": "conversation.item.created",
            "event_id": "evt-user-item",
            "item": {"id": "item-user-1", "type": "message", "role": "user"},
        },
    )
    _observe(
        recorder,
        320,
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "event_id": "evt-user-transcript",
            "item_id": "item-user-1",
            "content_index": 0,
            "transcript": "Проверка собственного эха",
        },
    )
    recorder.record_write(
        write_start_ns=START_NS + 225_000_000,
        write_end_ns=START_NS + 325_000_000,
        buffer_before_bytes=960,
        buffer_after_bytes=480,
        response_audio_frames=240,
        zero_frames=0,
        frames_written=240,
        sample_rate=24_000,
        underflow=False,
        response_active=True,
    )
    _observe(
        recorder,
        330,
        {
            "type": "response.created",
            "event_id": "evt-new-response",
            "response": {"id": "resp-new"},
        },
    )
    _observe(
        recorder,
        400,
        {
            "type": "response.audio_transcript.done",
            "event_id": "evt-new-text",
            "response_id": "resp-new",
            "item_id": "assistant-new",
            "transcript": "Ответ на проверку.",
        },
    )
    _observe(
        recorder,
        410,
        {
            "type": "response.audio.done",
            "event_id": "evt-new-audio-done",
            "response_id": "resp-new",
            "item_id": "assistant-new",
        },
    )
    _observe(
        recorder,
        420,
        {
            "type": "response.done",
            "event_id": "evt-new-done",
            "response_id": "resp-new",
        },
    )

    summary = recorder.summary(end_ns=START_NS + 500_000_000)
    forensics = summary["false_turn_forensics"]
    assert isinstance(forensics, dict)
    assert forensics["speech_started_count"] == 1
    assert forensics["speech_started_during_playback_count"] == 1
    assert forensics["transcription_completed_count"] == 1
    turns = forensics["turns"]
    assert isinstance(turns, list)
    turn = turns[0]
    assert isinstance(turn, dict)
    assert turn["turn_id"] == "turn_001"
    assert turn["provider_item_id"] == "item-user-1"
    assert turn["speech_started_event_id"] == "evt-speech-start"
    assert turn["speech_stopped_event_id"] == "evt-speech-stop"
    assert turn["transcript"] == "Проверка собственного эха"
    assert turn["response_id"] == "resp-new"
    assert "provider_direct_link_unavailable" in turn["response_correlation"]
    assert "SUSPECTED_PLAYBACK_OVERLAP" in turn["diagnostic_flags"]
    assert (
        "TRANSCRIPT_SIMILAR_TO_RECENT_ASSISTANT_OUTPUT"
        in turn["diagnostic_flags"]
    )
    playback = turn["playback_at_speech_started"]
    assert isinstance(playback, dict)
    assert playback["playback_active"] is True
    assert playback["current_or_recent_response_id"] == "resp-old"
    assert playback["playback_backlog_bytes"] == 480
    assert playback["playback_backlog_ms"] == pytest.approx(10)
    assert playback["write_in_progress"] is True
    signal = turn["speech_interval_signal"]
    assert isinstance(signal, dict)
    assert signal["block_count"] == 2
    assert signal["average_rms"] == pytest.approx(0.15)
    assert signal["maximum_peak"] == pytest.approx(0.5)
    assert signal["silent_block_ratio"] == 0
    similarity = turn["transcript_similarity"]
    assert isinstance(similarity, dict)
    assert similarity["compared_user_transcript"] == "Проверка собственного эха"
    assert (
        similarity["compared_assistant_transcript"]
        == "Проверка собственного эха"
    )
    response_items = forensics["responses"]
    assert isinstance(response_items, list)
    responses = {
        response["response_id"]: response
        for response in response_items
        if isinstance(response, dict)
    }
    assert responses["resp-old"]["provider_audio_duration_ms"] == pytest.approx(20)
    assert responses["resp-old"]["playback_start_ns"] == START_NS + 225_000_000
    assert responses["resp-old"]["playback_last_write_end_ns"] == START_NS + 325_000_000
    assert responses["resp-old"]["playback_duration_ms_estimate"] == pytest.approx(10)

    paths = recorder.finish(end_ns=START_NS + 500_000_000)
    assert paths is not None
    jsonl_path, summary_path = paths
    text = jsonl_path.read_text(encoding="utf-8")
    records = [json.loads(line) for line in text.splitlines()]
    transcript_record = next(
        record for record in records if record["kind"] == "input_audio_transcription"
    )
    assert transcript_record["transcript"] == "Проверка собственного эха"
    assert transcript_record["event_id"] == "evt-user-transcript"
    assert transcript_record["item_id"] == "item-user-1"
    assert "not-retained-provider-pcm" not in text
    assert not list(tmp_path.rglob("*.wav"))
    human = summary_path.read_text(encoding="utf-8")
    assert "TURN TIMELINE:" in human
    assert "Проверка собственного эха" in human


def test_transcription_failure_is_bounded_evidence_and_does_not_crash(
    tmp_path: Path,
) -> None:
    recorder = _recorder(tmp_path)
    _observe(
        recorder,
        10,
        {
            "type": "input_audio_buffer.speech_started",
            "event_id": "evt-start",
            "item_id": "failed-item",
        },
    )
    _observe(
        recorder,
        20,
        {
            "type": "input_audio_buffer.speech_stopped",
            "event_id": "evt-stop",
            "item_id": "failed-item",
        },
    )
    _observe(
        recorder,
        30,
        {
            "type": "conversation.item.input_audio_transcription.failed",
            "event_id": "evt-failed",
            "item_id": "failed-item",
            "content_index": 0,
            "error": {
                "type": "transcription_error",
                "code": "transcription_failed",
                "message": "ASR unavailable",
            },
        },
    )

    forensics = recorder.summary(end_ns=START_NS + 40_000_000)[
        "false_turn_forensics"
    ]
    assert isinstance(forensics, dict)
    assert forensics["transcription_failed_count"] == 1
    turns = forensics["turns"]
    assert isinstance(turns, list)
    turn = turns[0]
    assert isinstance(turn, dict)
    assert turn["transcription_success"] is False
    assert turn["provider_item_id"] == "failed-item"
    assert turn["transcription_error"] == {
        "type": "transcription_error",
        "code": "transcription_failed",
        "message": "ASR unavailable",
    }


def test_response_ids_close_exact_response_and_unmatched_response_is_visible(
    tmp_path: Path,
) -> None:
    recorder = _recorder(tmp_path)
    _observe(
        recorder,
        10,
        {"type": "response.created", "response": {"id": "response-a"}},
    )
    _observe(
        recorder,
        20,
        {"type": "response.created", "response": {"id": "response-b"}},
    )
    _observe(
        recorder,
        30,
        {"type": "response.done", "response_id": "response-a"},
    )

    forensics = recorder.summary(end_ns=START_NS + 40_000_000)[
        "false_turn_forensics"
    ]
    assert isinstance(forensics, dict)
    assert forensics["unexpected_response_without_correlated_input_count"] == 2
    response_items = forensics["responses"]
    assert isinstance(response_items, list)
    assert all(isinstance(response, dict) for response in response_items)
    responses = {
        response["response_id"]: response
        for response in response_items
        if isinstance(response, dict)
    }
    assert responses["response-a"]["response_done_ns"] == START_NS + 30_000_000
    assert "response_done_ns" not in responses["response-b"]


def test_no_playback_snapshot_is_false_and_diagnostic_flags_are_observational(
    tmp_path: Path,
) -> None:
    recorder = _recorder(tmp_path)
    _observe(
        recorder,
        10,
        {
            "type": "input_audio_buffer.speech_started",
            "event_id": "evt-start",
            "item_id": "quiet-item",
        },
    )

    timeline = recorder.summary(end_ns=START_NS + 20_000_000)["turn_timeline"]
    assert isinstance(timeline, list)
    turn = timeline[0]
    assert isinstance(turn, dict)
    playback = turn["playback_at_speech_started"]
    assert isinstance(playback, dict)
    assert playback["playback_active"] is False
    assert turn["diagnostic_flags"] == []
    assert recorder.response_active is False


def test_turn_observation_failure_cannot_escape_into_qwen_session() -> None:
    class BrokenDiagnostics:
        def __init__(self) -> None:
            self.failure_count = 0

        def record_turn_event(self, event: object, *, t_ns: int) -> None:
            raise RuntimeError("diagnostics broke")

        def record_playback_write_start(self, **kwargs: object) -> None:
            raise RuntimeError("playback diagnostics broke")

        def record_turn_forensics_failure(
            self, *, t_ns: int, error: Exception
        ) -> None:
            self.failure_count += 1

    diagnostics = BrokenDiagnostics()
    QwenLiveAudioService._record_turn_event_safely(
        diagnostics,  # type: ignore[arg-type]
        {"type": "input_audio_buffer.speech_started"},
        t_ns=START_NS,
    )
    assert diagnostics.failure_count == 1
    QwenLiveAudioService._record_playback_write_start_safely(
        diagnostics,  # type: ignore[arg-type]
        t_ns=START_NS,
        buffer_after_bytes=0,
        response_audio_bytes=960,
        sample_rate=24_000,
    )
    assert diagnostics.failure_count == 2


def test_session_enables_only_provider_side_input_transcription() -> None:
    payload = _audio_session_update("qwen3.5-omni-flash-realtime", "Tina")
    session = payload["session"]
    assert session["input_audio_transcription"] == {
        "model": "qwen3-asr-flash-realtime"
    }
    assert session["modalities"] == ["text", "audio"]
    assert session["voice"] == "Tina"
    assert session["input_audio_format"] == "pcm"
    assert session["output_audio_format"] == "pcm"
    assert session["turn_detection"] == {
        "type": "server_vad",
        "threshold": 0.5,
        "silence_duration_ms": 800,
    }
