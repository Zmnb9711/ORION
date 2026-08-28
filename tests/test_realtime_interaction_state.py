from __future__ import annotations

import pytest

from orion.realtime_interaction_state import RealtimeInteractionState


class _Clock:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> int:
        return self.value


def test_turn_response_and_first_audio_are_correlated_without_content() -> None:
    clock = _Clock()
    state = RealtimeInteractionState(clock_ns=clock)
    assert state.safe_to_refresh
    assert state.speech_started() == "turn_001"
    assert not state.safe_to_refresh
    clock.value = 1_000_000_000
    assert state.speech_stopped() == "turn_001"
    clock.value = 1_100_000_000
    assert state.response_started("response-1") == "turn_001"
    clock.value = 2_000_000_000
    first = state.first_audio("response-1")
    assert first is not None
    assert first.turn_id == "turn_001"
    assert first.response_created_to_first_audio_ms == pytest.approx(900)
    assert first.speech_stopped_to_first_audio_ms == pytest.approx(1000)
    assert state.first_audio("response-1") is None
    assert state.response_done("response-1") == "turn_001"
    assert state.safe_to_refresh


def test_latency_summary_is_bounded_and_uses_nearest_rank_p90() -> None:
    clock = _Clock()
    state = RealtimeInteractionState(clock_ns=clock, latency_window=3)
    for index, delay_ms in enumerate((100, 200, 300, 400), start=1):
        state.speech_started()
        state.speech_stopped()
        response_id = f"r{index}"
        state.response_started(response_id)
        clock.value += delay_ms * 1_000_000
        assert state.first_audio(response_id) is not None
        state.response_done(response_id)
    summary = state.latency_summary()
    assert summary.sample_count == 3
    assert summary.latest_ms == pytest.approx(400)
    assert summary.median_ms == pytest.approx(300)
    assert summary.p90_ms == pytest.approx(400)
    assert summary.maximum_ms == pytest.approx(400)


def test_manually_committed_turn_without_provider_response_becomes_idle() -> None:
    state = RealtimeInteractionState()
    assert state.speech_started() == "turn_001"
    assert state.speech_stopped() == "turn_001"
    assert not state.safe_to_refresh
    assert state.complete_current_turn_without_response() == "turn_001"
    assert state.safe_to_refresh
