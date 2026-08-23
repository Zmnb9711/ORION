from __future__ import annotations

import math
import queue
import threading
from array import array
from collections import deque
from dataclasses import dataclass


ANALYSIS_RATE_HZ = 16_000
CORRELATION_STRIDE_SAMPLES = 8
DEFAULT_HISTORY_SECONDS = 3.0
DEFAULT_WINDOW_MS = 1_000.0
DEFAULT_LAG_MIN_MS = 0.0
DEFAULT_LAG_MAX_MS = 500.0
MAX_PENDING_ANALYSES = 8
_ENERGY_EPSILON = 1.0 / 32768.0


@dataclass(frozen=True)
class _TimedPcmBlock:
    start_ns: int
    sample_rate: int
    pcm: bytes

    @property
    def frame_count(self) -> int:
        return len(self.pcm) // 2

    @property
    def duration_ns(self) -> int:
        return round(self.frame_count * 1_000_000_000 / self.sample_rate)

    @property
    def end_ns(self) -> int:
        return self.start_ns + self.duration_ns


class _BoundedPcmHistory:
    def __init__(self, max_duration_ns: int) -> None:
        self._max_duration_ns = max_duration_ns
        self._blocks: deque[_TimedPcmBlock] = deque()
        self._stored_duration_ns = 0

    def append(self, block: _TimedPcmBlock, *, retain_from_start: bool) -> None:
        if block.sample_rate <= 0 or not block.pcm or len(block.pcm) % 2:
            return
        max_frames = max(
            1, round(self._max_duration_ns * block.sample_rate / 1_000_000_000)
        )
        if block.frame_count > max_frames:
            if retain_from_start:
                pcm = block.pcm[: max_frames * 2]
                start_ns = block.start_ns
            else:
                pcm = block.pcm[-max_frames * 2 :]
                removed_frames = block.frame_count - max_frames
                start_ns = block.start_ns + round(
                    removed_frames * 1_000_000_000 / block.sample_rate
                )
            block = _TimedPcmBlock(start_ns, block.sample_rate, pcm)
        self._blocks.append(block)
        self._stored_duration_ns += block.duration_ns
        while self._blocks and self._stored_duration_ns > self._max_duration_ns:
            excess_ns = self._stored_duration_ns - self._max_duration_ns
            oldest = self._blocks[0]
            if oldest.duration_ns <= excess_ns:
                self._blocks.popleft()
                self._stored_duration_ns -= oldest.duration_ns
                continue
            remove_frames = min(
                oldest.frame_count - 1,
                max(1, math.ceil(excess_ns * oldest.sample_rate / 1_000_000_000)),
            )
            retained = _TimedPcmBlock(
                oldest.start_ns
                + round(remove_frames * 1_000_000_000 / oldest.sample_rate),
                oldest.sample_rate,
                oldest.pcm[remove_frames * 2 :],
            )
            self._blocks[0] = retained
            self._stored_duration_ns -= oldest.duration_ns - retained.duration_ns

    def snapshot(self) -> tuple[_TimedPcmBlock, ...]:
        return tuple(self._blocks)

    def clear(self) -> None:
        self._blocks.clear()
        self._stored_duration_ns = 0


@dataclass(frozen=True)
class _AnalysisRequest:
    request_id: int
    event_ns: int
    microphone: tuple[_TimedPcmBlock, ...]
    playback: tuple[_TimedPcmBlock, ...]


def unavailable_correlation_result(reason: str) -> dict[str, object]:
    return {
        "analysis_valid": False,
        "availability_reason": reason,
        "analysis_rate_hz": ANALYSIS_RATE_HZ,
        "correlation_stride_samples": CORRELATION_STRIDE_SAMPLES,
        "correlation_feature_rate_hz": (ANALYSIS_RATE_HZ // CORRELATION_STRIDE_SAMPLES),
        "analysis_window_ms": DEFAULT_WINDOW_MS,
        "lag_search_min_ms": DEFAULT_LAG_MIN_MS,
        "lag_search_max_ms": DEFAULT_LAG_MAX_MS,
        "valid_sample_count": 0,
        "valid_window_ms": 0.0,
        "mic_rms": None,
        "mic_peak": None,
        "playback_ref_rms": None,
        "playback_ref_peak": None,
        "max_normalized_correlation": None,
        "best_lag_ms": None,
        "mic_to_playback_energy_ratio": None,
        "optimal_playback_gain": None,
        "residual_double_talk_score": None,
    }


def _render_timeline(
    blocks: tuple[_TimedPcmBlock, ...],
    *,
    start_ns: int,
    sample_count: int,
) -> tuple[list[float], bytearray]:
    values = [0.0] * sample_count
    valid = bytearray(sample_count)
    if sample_count <= 0:
        return values, valid
    for block in blocks:
        overlap_start_ns = max(start_ns, block.start_ns)
        overlap_end_ns = min(
            start_ns + round(sample_count * 1_000_000_000 / ANALYSIS_RATE_HZ),
            block.end_ns,
        )
        if overlap_end_ns <= overlap_start_ns:
            continue
        samples = array("h")
        samples.frombytes(block.pcm)
        target_start = max(
            0,
            math.ceil((overlap_start_ns - start_ns) * ANALYSIS_RATE_HZ / 1_000_000_000),
        )
        target_end = min(
            sample_count,
            math.ceil((overlap_end_ns - start_ns) * ANALYSIS_RATE_HZ / 1_000_000_000),
        )
        for target_index in range(target_start, target_end):
            sample_ns = start_ns + round(
                target_index * 1_000_000_000 / ANALYSIS_RATE_HZ
            )
            source_position = (
                (sample_ns - block.start_ns) * block.sample_rate / 1_000_000_000
            )
            left = max(0, min(len(samples) - 1, int(source_position)))
            right = min(left + 1, len(samples) - 1)
            fraction = max(0.0, min(1.0, source_position - left))
            sample = samples[left] + (samples[right] - samples[left]) * fraction
            values[target_index] = sample / 32768.0
            valid[target_index] = 1
    return values, valid


def _candidate_metrics(
    microphone: list[float],
    microphone_valid: bytearray,
    playback: list[float],
    playback_valid: bytearray,
    *,
    window_start: int,
    lag_samples: int,
) -> tuple[float | None, int]:
    count = 0
    sum_mic = 0.0
    sum_playback = 0.0
    sum_mic_sq = 0.0
    sum_playback_sq = 0.0
    sum_product = 0.0
    for mic_index in range(window_start, len(microphone), CORRELATION_STRIDE_SAMPLES):
        playback_index = mic_index - lag_samples
        if (
            playback_index < 0
            or not microphone_valid[mic_index]
            or not playback_valid[playback_index]
        ):
            continue
        mic = microphone[mic_index]
        reference = playback[playback_index]
        count += 1
        sum_mic += mic
        sum_playback += reference
        sum_mic_sq += mic * mic
        sum_playback_sq += reference * reference
        sum_product += mic * reference
    if count < 100:
        return None, count
    covariance = sum_product - (sum_mic * sum_playback / count)
    mic_variance = sum_mic_sq - (sum_mic * sum_mic / count)
    playback_variance = sum_playback_sq - (sum_playback * sum_playback / count)
    denominator = math.sqrt(max(0.0, mic_variance * playback_variance))
    if denominator <= _ENERGY_EPSILON * _ENERGY_EPSILON * count:
        return None, count
    return max(-1.0, min(1.0, covariance / denominator)), count


def analyze_timed_pcm(
    microphone_blocks: tuple[_TimedPcmBlock, ...],
    playback_blocks: tuple[_TimedPcmBlock, ...],
    *,
    event_ns: int,
) -> dict[str, object]:
    """Return scalar diagnostic metrics; PCM never leaves this function."""

    if not microphone_blocks:
        return unavailable_correlation_result("insufficient microphone history")
    if not playback_blocks:
        return unavailable_correlation_result("insufficient playback history")
    window_samples = round(DEFAULT_WINDOW_MS * ANALYSIS_RATE_HZ / 1000)
    lag_min_samples = round(DEFAULT_LAG_MIN_MS * ANALYSIS_RATE_HZ / 1000)
    lag_max_samples = round(DEFAULT_LAG_MAX_MS * ANALYSIS_RATE_HZ / 1000)
    total_samples = window_samples + lag_max_samples
    timeline_start_ns = event_ns - round(
        total_samples * 1_000_000_000 / ANALYSIS_RATE_HZ
    )
    microphone, microphone_valid = _render_timeline(
        microphone_blocks,
        start_ns=timeline_start_ns,
        sample_count=total_samples,
    )
    playback, playback_valid = _render_timeline(
        playback_blocks,
        start_ns=timeline_start_ns,
        sample_count=total_samples,
    )
    coarse_step = max(CORRELATION_STRIDE_SAMPLES, round(4 * ANALYSIS_RATE_HZ / 1000))
    coarse_lags = range(lag_min_samples, lag_max_samples + 1, coarse_step)
    best_correlation: float | None = None
    best_lag = lag_min_samples
    best_count = 0
    for lag in coarse_lags:
        correlation, count = _candidate_metrics(
            microphone,
            microphone_valid,
            playback,
            playback_valid,
            window_start=lag_max_samples,
            lag_samples=lag,
        )
        if correlation is not None and (
            best_correlation is None or correlation > best_correlation
        ):
            best_correlation = correlation
            best_lag = lag
            best_count = count
    if best_correlation is None:
        result = unavailable_correlation_result(
            "insufficient overlapping or non-silent history"
        )
        mic_values = [
            microphone[index]
            for index in range(lag_max_samples, total_samples)
            if microphone_valid[index]
        ]
        playback_values = [
            playback[index]
            for index in range(lag_max_samples, total_samples)
            if playback_valid[index]
        ]
        if mic_values:
            result["mic_rms"] = math.sqrt(
                sum(value * value for value in mic_values) / len(mic_values)
            )
            result["mic_peak"] = max(abs(value) for value in mic_values)
        if playback_values:
            result["playback_ref_rms"] = math.sqrt(
                sum(value * value for value in playback_values) / len(playback_values)
            )
            result["playback_ref_peak"] = max(abs(value) for value in playback_values)
        playback_result_rms = result["playback_ref_rms"]
        mic_result_rms = result["mic_rms"]
        if (
            isinstance(playback_result_rms, (int, float))
            and playback_result_rms <= _ENERGY_EPSILON
        ):
            result["availability_reason"] = "playback reference silent"
        elif (
            isinstance(mic_result_rms, (int, float))
            and mic_result_rms <= _ENERGY_EPSILON
        ):
            result["availability_reason"] = "microphone silent"
        return result
    fine_radius = coarse_step * 2
    fine_start = max(lag_min_samples, best_lag - fine_radius)
    fine_end = min(lag_max_samples, best_lag + fine_radius)
    for lag in range(fine_start, fine_end + 1, CORRELATION_STRIDE_SAMPLES):
        correlation, count = _candidate_metrics(
            microphone,
            microphone_valid,
            playback,
            playback_valid,
            window_start=lag_max_samples,
            lag_samples=lag,
        )
        if correlation is not None and correlation > best_correlation:
            best_correlation = correlation
            best_lag = lag
            best_count = count

    mic_values: list[float] = []
    playback_values: list[float] = []
    for mic_index in range(lag_max_samples, total_samples, CORRELATION_STRIDE_SAMPLES):
        playback_index = mic_index - best_lag
        if (
            playback_index < 0
            or not microphone_valid[mic_index]
            or not playback_valid[playback_index]
        ):
            continue
        mic_values.append(microphone[mic_index])
        playback_values.append(playback[playback_index])
    if not mic_values or not playback_values:
        return unavailable_correlation_result("insufficient overlapping history")
    mic_square = sum(value * value for value in mic_values)
    playback_square = sum(value * value for value in playback_values)
    mic_rms = math.sqrt(mic_square / len(mic_values))
    playback_rms = math.sqrt(playback_square / len(playback_values))
    if playback_rms <= _ENERGY_EPSILON:
        return unavailable_correlation_result("playback reference silent")
    if mic_rms <= _ENERGY_EPSILON:
        return unavailable_correlation_result("microphone silent")
    gain = (
        sum(
            mic * reference
            for mic, reference in zip(mic_values, playback_values, strict=True)
        )
        / playback_square
    )
    residual_square = sum(
        (mic - gain * reference) ** 2
        for mic, reference in zip(mic_values, playback_values, strict=True)
    )
    residual_rms = math.sqrt(residual_square / len(mic_values))
    return {
        "analysis_valid": True,
        "availability_reason": "available",
        "analysis_rate_hz": ANALYSIS_RATE_HZ,
        "correlation_stride_samples": CORRELATION_STRIDE_SAMPLES,
        "correlation_feature_rate_hz": (ANALYSIS_RATE_HZ // CORRELATION_STRIDE_SAMPLES),
        "analysis_window_ms": DEFAULT_WINDOW_MS,
        "lag_search_min_ms": DEFAULT_LAG_MIN_MS,
        "lag_search_max_ms": DEFAULT_LAG_MAX_MS,
        "valid_sample_count": best_count,
        "valid_window_ms": (
            best_count * CORRELATION_STRIDE_SAMPLES * 1000 / ANALYSIS_RATE_HZ
        ),
        "mic_rms": mic_rms,
        "mic_peak": max(abs(value) for value in mic_values),
        "playback_ref_rms": playback_rms,
        "playback_ref_peak": max(abs(value) for value in playback_values),
        "max_normalized_correlation": best_correlation,
        "best_lag_ms": best_lag * 1000 / ANALYSIS_RATE_HZ,
        "mic_to_playback_energy_ratio": mic_rms / playback_rms,
        "optimal_playback_gain": gain,
        "residual_double_talk_score": residual_rms / mic_rms,
    }


class PlaybackMicCorrelationProbe:
    """Bounded, diagnostic-only PCM history and background scalar analysis."""

    def __init__(self, history_seconds: float = DEFAULT_HISTORY_SECONDS) -> None:
        max_duration_ns = round(history_seconds * 1_000_000_000)
        self._microphone = _BoundedPcmHistory(max_duration_ns)
        self._playback = _BoundedPcmHistory(max_duration_ns)
        self._requests: queue.Queue[_AnalysisRequest | None] = queue.Queue(
            maxsize=MAX_PENDING_ANALYSES
        )
        self._results: queue.SimpleQueue[tuple[int, dict[str, object]]] = (
            queue.SimpleQueue()
        )
        self._next_request_id = 1
        self._worker: threading.Thread | None = None

    def record_microphone(self, pcm: bytes, *, sample_rate: int, end_ns: int) -> None:
        if sample_rate <= 0:
            return
        frames = len(pcm) // 2
        start_ns = end_ns - round(frames * 1_000_000_000 / sample_rate)
        self._microphone.append(
            _TimedPcmBlock(start_ns, sample_rate, pcm), retain_from_start=False
        )

    def record_playback(self, pcm: bytes, *, sample_rate: int, start_ns: int) -> None:
        if sample_rate <= 0:
            return
        self._playback.append(
            _TimedPcmBlock(start_ns, sample_rate, pcm), retain_from_start=True
        )

    def submit(self, *, event_ns: int) -> int | None:
        if self._worker is None:
            self._worker = threading.Thread(
                target=self._run,
                daemon=True,
                name="orion-qwen-correlation-diagnostics",
            )
            self._worker.start()
        request_id = self._next_request_id
        request = _AnalysisRequest(
            request_id,
            event_ns,
            self._microphone.snapshot(),
            self._playback.snapshot(),
        )
        try:
            self._requests.put_nowait(request)
        except queue.Full:
            return None
        self._next_request_id += 1
        return request_id

    def collect(self) -> list[tuple[int, dict[str, object]]]:
        results: list[tuple[int, dict[str, object]]] = []
        while True:
            try:
                results.append(self._results.get_nowait())
            except queue.Empty:
                return results

    def close(self) -> list[tuple[int, dict[str, object]]]:
        worker = self._worker
        if worker is not None:
            self._requests.put(None)
            worker.join()
            self._worker = None
        return self.collect()

    def reset(self) -> None:
        self._microphone.clear()
        self._playback.clear()

    def _run(self) -> None:
        while True:
            request = self._requests.get()
            if request is None:
                return
            try:
                result = analyze_timed_pcm(
                    request.microphone,
                    request.playback,
                    event_ns=request.event_ns,
                )
            except Exception as exc:
                result = unavailable_correlation_result(
                    f"analysis failure: {type(exc).__name__}"
                )
            self._results.put((request.request_id, result))
