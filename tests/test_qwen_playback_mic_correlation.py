from __future__ import annotations

import base64
import json
import math
from array import array
from pathlib import Path

import pytest

from orion.qwen_audio_correlation import PlaybackMicCorrelationProbe
from orion.qwen_live_diagnostics import QwenLiveDiagnostics


RATE = 16_000
DURATION_MS = 1_600
FRAMES = RATE * DURATION_MS // 1_000
END_NS = DURATION_MS * 1_000_000


def _noise(seed: int, frames: int = FRAMES) -> array[int]:
    state = seed
    values = array("h")
    for _ in range(frames):
        state = (1_664_525 * state + 1_013_904_223) & 0xFFFFFFFF
        values.append(((state >> 16) & 0xFFFF) - 32_768)
    return values


def _scaled(values: array[int], gain: float) -> array[int]:
    return array(
        "h",
        (max(-32_768, min(32_767, round(value * gain))) for value in values),
    )


def _analyze(playback: array[int], microphone: array[int]) -> dict[str, object]:
    probe = PlaybackMicCorrelationProbe()
    probe.record_playback(playback.tobytes(), sample_rate=RATE, start_ns=0)
    probe.record_microphone(microphone.tobytes(), sample_rate=RATE, end_ns=END_NS)
    request_id = probe.submit(event_ns=END_NS)
    assert request_id is not None
    results = dict(probe.close())
    probe.reset()
    return results[request_id]


def _metric(result: dict[str, object], name: str) -> float:
    value = result[name]
    assert isinstance(value, (int, float)) and not isinstance(value, bool)
    return float(value)


def test_identical_signal_has_near_unity_zero_lag_correlation() -> None:
    signal = _noise(1)

    result = _analyze(signal, signal)

    assert result["analysis_valid"] is True
    assert result["max_normalized_correlation"] == pytest.approx(1.0, abs=1e-9)
    assert result["best_lag_ms"] == pytest.approx(0.0, abs=0.5)
    assert result["residual_double_talk_score"] == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("delay_ms", [120, 500])
def test_known_playback_to_microphone_delay_is_recovered(delay_ms: int) -> None:
    playback = _noise(2)
    delay_frames = RATE * delay_ms // 1_000
    microphone = array("h", [0]) * delay_frames
    microphone.extend(playback[: FRAMES - delay_frames])

    result = _analyze(playback, microphone)

    assert result["analysis_valid"] is True
    assert _metric(result, "max_normalized_correlation") > 0.99
    assert result["best_lag_ms"] == pytest.approx(delay_ms, abs=0.6)


def test_amplitude_scaled_echo_keeps_high_normalized_correlation() -> None:
    playback = _noise(3)

    result = _analyze(playback, _scaled(playback, 0.18))

    assert _metric(result, "max_normalized_correlation") > 0.999
    assert result["optimal_playback_gain"] == pytest.approx(0.18, abs=0.001)


def test_unrelated_deterministic_signals_have_low_correlation() -> None:
    result = _analyze(_noise(4), _noise(5))

    assert result["analysis_valid"] is True
    assert abs(_metric(result, "max_normalized_correlation")) < 0.15


def test_double_talk_has_higher_residual_than_scaled_echo() -> None:
    playback = _noise(6)
    echo = _scaled(playback, 0.3)
    independent = _scaled(_noise(7), 0.25)
    double_talk = array(
        "h",
        (
            max(-32_768, min(32_767, echo_sample + independent_sample))
            for echo_sample, independent_sample in zip(echo, independent, strict=True)
        ),
    )

    echo_result = _analyze(playback, echo)
    double_talk_result = _analyze(playback, double_talk)

    assert _metric(double_talk_result, "max_normalized_correlation") > 0.5
    assert _metric(double_talk_result, "residual_double_talk_score") > (
        _metric(echo_result, "residual_double_talk_score") + 0.4
    )


def test_physical_24khz_playback_is_normalized_to_16khz_for_analysis() -> None:
    def waveform(rate: int) -> array[int]:
        return array(
            "h",
            (
                round(
                    12_000 * math.sin(2 * math.pi * 317 * index / rate)
                    + 5_000 * math.sin(2 * math.pi * 701 * index / rate)
                )
                for index in range(rate * DURATION_MS // 1_000)
            ),
        )

    probe = PlaybackMicCorrelationProbe()
    probe.record_playback(waveform(24_000).tobytes(), sample_rate=24_000, start_ns=0)
    probe.record_microphone(waveform(RATE).tobytes(), sample_rate=RATE, end_ns=END_NS)
    request_id = probe.submit(event_ns=END_NS)
    assert request_id is not None
    result = dict(probe.close())[request_id]

    assert result["analysis_rate_hz"] == 16_000
    assert _metric(result, "max_normalized_correlation") > 0.999
    assert result["best_lag_ms"] == pytest.approx(0.0, abs=0.5)


def test_silence_is_safe_and_marked_unavailable() -> None:
    silence = array("h", [0]) * FRAMES

    result = _analyze(silence, silence)

    assert result["analysis_valid"] is False
    assert result["max_normalized_correlation"] is None
    assert result["mic_to_playback_energy_ratio"] is None
    assert not any(
        isinstance(value, float) and math.isnan(value) for value in result.values()
    )


def test_near_zero_playback_reference_is_safe() -> None:
    near_zero = array("h", [1]) * FRAMES

    result = _analyze(near_zero, _noise(8))

    assert result["analysis_valid"] is False
    assert result["availability_reason"] == "playback reference silent"
    assert result["mic_to_playback_energy_ratio"] is None


def test_insufficient_playback_history_is_reported_without_failure() -> None:
    probe = PlaybackMicCorrelationProbe()
    microphone = _noise(9)
    probe.record_microphone(microphone.tobytes(), sample_rate=RATE, end_ns=END_NS)

    request_id = probe.submit(event_ns=END_NS)
    assert request_id is not None
    result = dict(probe.close())[request_id]

    assert result["analysis_valid"] is False
    assert result["availability_reason"] == "insufficient playback history"


def _diagnostics(tmp_path: Path) -> QwenLiveDiagnostics:
    return QwenLiveDiagnostics(
        model="qwen3.5-omni-flash-realtime",
        region="singapore",
        vad_type="server_vad",
        silence_duration_ms=800,
        qwen_input_rate=RATE,
        qwen_output_rate=24_000,
        runtime_dir=tmp_path,
        start_ns=0,
    )


def test_diagnostics_persist_scalars_but_never_raw_audio(tmp_path: Path) -> None:
    diagnostics = _diagnostics(tmp_path)
    playback = _noise(10)
    microphone = _scaled(playback, 0.2)
    playback_pcm = playback.tobytes()
    microphone_pcm = microphone.tobytes()
    diagnostics.record_microphone_analysis_pcm(
        pcm=microphone_pcm,
        sample_rate=RATE,
        end_ns=END_NS,
    )
    diagnostics.record_playback_write_start(
        t_ns=0,
        buffer_after_bytes=0,
        response_audio_bytes=len(playback_pcm),
        sample_rate=RATE,
        pcm=playback_pcm,
    )
    diagnostics.record_turn_event(
        {
            "type": "input_audio_buffer.speech_started",
            "event_id": "evt-start",
            "item_id": "user-item",
        },
        t_ns=END_NS,
    )
    diagnostics.record_turn_event(
        {
            "type": "input_audio_buffer.speech_stopped",
            "event_id": "evt-stop",
            "item_id": "user-item",
        },
        t_ns=END_NS,
    )
    diagnostics.record_turn_event(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "event_id": "evt-transcript",
            "item_id": "user-item",
            "transcript": "test",
        },
        t_ns=END_NS,
    )

    paths = diagnostics.finish(end_ns=END_NS + 1)

    assert paths is not None
    jsonl_path, summary_path = paths
    persisted = jsonl_path.read_text(encoding="utf-8")
    summary_text = summary_path.read_text(encoding="utf-8")
    assert base64.b64encode(playback_pcm).decode("ascii") not in persisted
    assert base64.b64encode(microphone_pcm).decode("ascii") not in persisted
    assert base64.b64encode(playback_pcm).decode("ascii") not in summary_text
    assert base64.b64encode(microphone_pcm).decode("ascii") not in summary_text
    assert '"pcm":' not in persisted
    assert '"samples": [' not in persisted
    assert "PLAYBACK/MIC CORRELATION AT SPEECH START:" in summary_text
    assert not list(tmp_path.rglob("*.wav"))
    assert not list(tmp_path.rglob("*.pcm"))
    summary_record = json.loads(persisted.splitlines()[-1])
    correlation = summary_record["turn_timeline"][0]["playback_microphone_correlation"]
    assert correlation["analysis_valid"] is True
    assert correlation["max_normalized_correlation"] > 0.999
    turn = summary_record["turn_timeline"][0]
    assert "playback_microphone_correlation_at_speech_stopped" in turn
    assert "playback_microphone_correlation_at_transcription" in turn


def test_response_and_fifo_observability_uses_side_ledger_only(tmp_path: Path) -> None:
    diagnostics = _diagnostics(tmp_path)
    pcm = _noise(11, 320).tobytes()
    diagnostics.record_turn_event(
        {
            "type": "response.created",
            "event_id": "evt-created",
            "response": {"id": "resp-1", "status": "in_progress"},
        },
        t_ns=100,
    )
    diagnostics.record_turn_event(
        {
            "type": "response.audio.delta",
            "event_id": "evt-delta",
            "response_id": "resp-1",
            "item_id": "assistant-1",
        },
        t_ns=200,
    )
    diagnostics.record_audio_delta(
        receive_ns=200,
        encoded_chars=10,
        decoded_bytes=len(pcm),
        source_rate=24_000,
        resample_start_ns=201,
        resample_end_ns=202,
        resampled_bytes=len(pcm),
        target_rate=24_000,
        response_id="resp-1",
        item_id="assistant-1",
    )
    diagnostics.record_playback_write_start(
        t_ns=300,
        buffer_after_bytes=0,
        response_audio_bytes=len(pcm),
        sample_rate=24_000,
        pcm=pcm,
    )
    diagnostics.record_write(
        write_start_ns=300,
        write_end_ns=400,
        buffer_before_bytes=len(pcm),
        buffer_after_bytes=0,
        response_audio_frames=len(pcm) // 2,
        zero_frames=0,
        frames_written=len(pcm) // 2,
        sample_rate=24_000,
        underflow=False,
        response_active=True,
    )
    diagnostics.record_turn_event(
        {
            "type": "response.done",
            "event_id": "evt-done",
            "response": {
                "id": "resp-1",
                "status": "completed",
                "status_details": {"type": "completed"},
                "output": [
                    {
                        "id": "assistant-1",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [{"audio": "must-not-be-copied"}],
                    }
                ],
            },
        },
        t_ns=500,
    )

    response_timeline = diagnostics.summary(end_ns=600)["response_timeline"]
    assert isinstance(response_timeline, list)
    response = response_timeline[0]
    assert isinstance(response, dict)

    assert response["playback_bytes_queued"] == len(pcm)
    assert response["playback_bytes_physically_written"] == len(pcm)
    assert response["playback_last_stream_write_sequence"] == 1
    assert response["response_status"] == "completed"
    assert response["response_status_details"] == {"type": "completed"}
    assert response["output_items"] == [
        {
            "id": "assistant-1",
            "type": "message",
            "status": "completed",
            "role": "assistant",
        }
    ]
    assert "content" not in response["output_items"][0]
