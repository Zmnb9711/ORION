"""Bounded, analysis-only playback/microphone correlation diagnostics."""

from __future__ import annotations

from array import array
from collections import deque
from dataclasses import asdict, dataclass
import math
import queue
import statistics
import sys
import threading
import time
from typing import Callable, Sequence

INPUT_RATE = 44_100
OUTPUT_RATE = 44_100
ANALYSIS_DECIMATION = 9
ANALYSIS_RATE = INPUT_RATE // ANALYSIS_DECIMATION
PLAYBACK_REFERENCE_HISTORY_MS = 1_000
MAX_LAG_SEARCH_MS = 500
PLAYBACK_ACTIVE_TAIL_MS = 100
SPEECH_START_PRE_MS = 200
SPEECH_START_POST_MS = 300
BASELINE_INTERVAL_MS = 100
DIAGNOSTIC_QUEUE_MAX = 256
SCALAR_HISTORY_MAX = 4_096
MIN_CORRELATION_SAMPLES = 16
MIN_ANALYSIS_RMS = 1.0
_ENERGY_EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class SignalFit:
    signed_correlation: float | None
    absolute_correlation: float | None
    reference_rms: float
    microphone_rms: float
    energy_ratio: float | None
    echo_fit_gain: float | None
    residual_rms: float | None
    residual_ratio: float | None


@dataclass(frozen=True, slots=True)
class PlaybackReference:
    timestamp: float
    response_id: str
    epoch: int
    sequence: int
    samples: array


@dataclass(frozen=True, slots=True)
class PlaybackJob:
    timestamp: float
    response_id: str
    epoch: int
    sequence: int
    pcm: bytes


@dataclass(frozen=True, slots=True)
class MicrophoneJob:
    timestamp: float
    pcm: bytes


@dataclass(frozen=True, slots=True)
class SpeechStartJob:
    timestamp: float
    wall_timestamp: str
    item_id: str | None
    current_response_id: str | None
    current_epoch: int | None


@dataclass(frozen=True, slots=True)
class MicrophoneAnalysis:
    timestamp: float
    playback_active: bool
    matched_response_id: str | None
    matched_epoch: int | None
    best_corr: float | None
    best_abs_corr: float | None
    best_lag_ms: float | None
    mic_rms: float
    playback_ref_rms: float | None
    energy_ratio: float | None
    echo_fit_gain: float | None
    residual_rms: float | None
    residual_ratio: float | None
    reference_coverage_ms: float


def pcm16_analysis_samples(pcm: bytes, decimation: int = ANALYSIS_DECIMATION) -> array:
    """Return a diagnostic-only decimated copy of little-endian PCM16."""

    if len(pcm) % 2:
        raise ValueError("PCM16 data must contain complete samples.")
    if decimation < 1:
        raise ValueError("Decimation must be at least one.")
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples[::decimation]


def signal_rms(samples: Sequence[int]) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(float(value) * value for value in samples) / len(samples))


def analyze_signal_pair(
    reference: Sequence[int], microphone: Sequence[int]
) -> SignalFit:
    """Fit centered playback to microphone samples without classifying behavior."""

    sample_count = min(len(reference), len(microphone))
    if sample_count < MIN_CORRELATION_SAMPLES:
        return SignalFit(None, None, 0.0, 0.0, None, None, None, None)
    ref = reference[:sample_count]
    mic = microphone[:sample_count]
    reference_rms = signal_rms(ref)
    microphone_rms = signal_rms(mic)
    energy_ratio = (
        microphone_rms / reference_rms
        if reference_rms > _ENERGY_EPSILON
        else None
    )
    if reference_rms <= MIN_ANALYSIS_RMS or microphone_rms <= MIN_ANALYSIS_RMS:
        return SignalFit(
            None,
            None,
            reference_rms,
            microphone_rms,
            energy_ratio,
            None,
            None,
            None,
        )
    reference_mean = sum(ref) / sample_count
    microphone_mean = sum(mic) / sample_count
    dot = 0.0
    reference_energy = 0.0
    microphone_energy = 0.0
    for reference_value, microphone_value in zip(ref, mic, strict=True):
        centered_reference = reference_value - reference_mean
        centered_microphone = microphone_value - microphone_mean
        dot += centered_reference * centered_microphone
        reference_energy += centered_reference * centered_reference
        microphone_energy += centered_microphone * centered_microphone
    if reference_energy <= _ENERGY_EPSILON or microphone_energy <= _ENERGY_EPSILON:
        return SignalFit(
            None,
            None,
            reference_rms,
            microphone_rms,
            energy_ratio,
            None,
            None,
            None,
        )
    signed_correlation = dot / math.sqrt(reference_energy * microphone_energy)
    echo_fit_gain = dot / reference_energy
    residual_energy = 0.0
    for reference_value, microphone_value in zip(ref, mic, strict=True):
        residual = (microphone_value - microphone_mean) - echo_fit_gain * (
            reference_value - reference_mean
        )
        residual_energy += residual * residual
    residual_rms = math.sqrt(residual_energy / sample_count)
    centered_microphone_rms = math.sqrt(microphone_energy / sample_count)
    residual_ratio = residual_rms / centered_microphone_rms
    return SignalFit(
        signed_correlation,
        abs(signed_correlation),
        reference_rms,
        microphone_rms,
        energy_ratio,
        echo_fit_gain,
        residual_rms,
        residual_ratio,
    )


def scalar_distribution(values: Sequence[float]) -> dict[str, float | None]:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return {"min": None, "median": None, "max": None}
    return {
        "min": round(min(finite), 6),
        "median": round(statistics.median(finite), 6),
        "max": round(max(finite), 6),
    }


class CorrelationProbe:
    """Non-blocking producer API with a bounded diagnostic worker."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        queue_size: int = DIAGNOSTIC_QUEUE_MAX,
    ) -> None:
        self.clock = clock
        self._queue: queue.Queue[PlaybackJob | MicrophoneJob | SpeechStartJob | object]
        self._queue = queue.Queue(maxsize=queue_size)
        self._sentinel = object()
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._accepting = False
        self._playback_history: deque[PlaybackReference] = deque()
        self._microphone_history: deque[MicrophoneAnalysis] = deque()
        self._pending_speech_starts: list[SpeechStartJob] = []
        self._speech_start_snapshots: list[dict[str, object]] = []
        self._speech_corr: deque[float] = deque(maxlen=SCALAR_HISTORY_MAX)
        self._speech_abs_corr: deque[float] = deque(maxlen=SCALAR_HISTORY_MAX)
        self._speech_lag: deque[float] = deque(maxlen=SCALAR_HISTORY_MAX)
        self._speech_residual: deque[float] = deque(maxlen=SCALAR_HISTORY_MAX)
        self._playback_baseline_corr: deque[float] = deque(maxlen=SCALAR_HISTORY_MAX)
        self._idle_baseline_corr: deque[float] = deque(maxlen=SCALAR_HISTORY_MAX)
        self._last_baseline_timestamp: float | None = None
        self.playback_baseline_samples = 0
        self.idle_baseline_samples = 0
        self.diagnostic_jobs_enqueued = 0
        self.diagnostic_jobs_processed = 0
        self.diagnostic_jobs_dropped = 0
        self.diagnostic_jobs_failed = 0

    def start(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._accepting = True
            self._worker = threading.Thread(
                target=self._run,
                name="yandex-correlation-probe",
                daemon=True,
            )
            self._worker.start()

    def submit_playback(
        self,
        pcm: bytes,
        *,
        timestamp: float,
        response_id: str,
        epoch: int,
        sequence: int,
    ) -> bool:
        return self._submit(
            PlaybackJob(timestamp, response_id, epoch, sequence, pcm)
        )

    def submit_microphone(self, pcm: bytes, *, timestamp: float) -> bool:
        return self._submit(MicrophoneJob(timestamp, pcm))

    def submit_speech_start(
        self,
        *,
        timestamp: float,
        wall_timestamp: str,
        item_id: str | None,
        current_response_id: str | None,
        current_epoch: int | None,
    ) -> bool:
        return self._submit(
            SpeechStartJob(
                timestamp,
                wall_timestamp,
                item_id,
                current_response_id,
                current_epoch,
            )
        )

    def _submit(self, job: PlaybackJob | MicrophoneJob | SpeechStartJob) -> bool:
        with self._lock:
            if not self._accepting:
                self.diagnostic_jobs_dropped += 1
                return False
            try:
                self._queue.put_nowait(job)
            except queue.Full:
                self.diagnostic_jobs_dropped += 1
                return False
            self.diagnostic_jobs_enqueued += 1
            return True

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job is self._sentinel:
                break
            try:
                if isinstance(job, PlaybackJob):
                    self._process_playback(job)
                elif isinstance(job, MicrophoneJob):
                    self._process_microphone(job)
                elif isinstance(job, SpeechStartJob):
                    self._process_speech_start(job)
                with self._lock:
                    self.diagnostic_jobs_processed += 1
            except Exception:
                with self._lock:
                    self.diagnostic_jobs_failed += 1
        with self._lock:
            self._finalize_ready(float("inf"), force=True)
            self._playback_history.clear()
            self._accepting = False

    def _process_playback(self, job: PlaybackJob) -> None:
        samples = pcm16_analysis_samples(job.pcm)
        reference = PlaybackReference(
            job.timestamp,
            job.response_id,
            job.epoch,
            job.sequence,
            samples,
        )
        with self._lock:
            self._playback_history.append(reference)
            cutoff = job.timestamp - PLAYBACK_REFERENCE_HISTORY_MS / 1000
            while (
                self._playback_history
                and self._playback_history[0].timestamp < cutoff
            ):
                self._playback_history.popleft()

    def _process_microphone(self, job: MicrophoneJob) -> None:
        samples = pcm16_analysis_samples(job.pcm)
        with self._lock:
            result = self._match_microphone(job.timestamp, samples)
            self._microphone_history.append(result)
            history_cutoff = job.timestamp - (
                PLAYBACK_REFERENCE_HISTORY_MS + SPEECH_START_PRE_MS
            ) / 1000
            while (
                self._microphone_history
                and self._microphone_history[0].timestamp < history_cutoff
            ):
                self._microphone_history.popleft()
            if (
                self._last_baseline_timestamp is None
                or (job.timestamp - self._last_baseline_timestamp) * 1000
                >= BASELINE_INTERVAL_MS
            ):
                self._record_baseline(result)
                self._last_baseline_timestamp = job.timestamp
            self._finalize_ready(job.timestamp)

    def _match_microphone(
        self, timestamp: float, samples: Sequence[int]
    ) -> MicrophoneAnalysis:
        microphone_rms = signal_rms(samples)
        recent_reference = any(
            0 <= (timestamp - reference.timestamp) * 1000 <= PLAYBACK_ACTIVE_TAIL_MS
            for reference in self._playback_history
        )
        best_reference: PlaybackReference | None = None
        best_fit: SignalFit | None = None
        best_lag_ms: float | None = None
        for reference in self._playback_history:
            lag_ms = (timestamp - reference.timestamp) * 1000
            if lag_ms < 0 or lag_ms > MAX_LAG_SEARCH_MS:
                continue
            fit = analyze_signal_pair(reference.samples, samples)
            if fit.absolute_correlation is None:
                continue
            if (
                best_fit is None
                or best_fit.absolute_correlation is None
                or fit.absolute_correlation > best_fit.absolute_correlation
            ):
                best_reference = reference
                best_fit = fit
                best_lag_ms = lag_ms
        if best_reference is None or best_fit is None:
            return MicrophoneAnalysis(
                timestamp,
                recent_reference,
                None,
                None,
                None,
                None,
                None,
                microphone_rms,
                None,
                None,
                None,
                None,
                None,
                0.0,
            )
        return MicrophoneAnalysis(
            timestamp,
            recent_reference,
            best_reference.response_id,
            best_reference.epoch,
            _rounded(best_fit.signed_correlation),
            _rounded(best_fit.absolute_correlation),
            round(best_lag_ms, 3) if best_lag_ms is not None else None,
            round(best_fit.microphone_rms, 3),
            round(best_fit.reference_rms, 3),
            _rounded(best_fit.energy_ratio),
            _rounded(best_fit.echo_fit_gain),
            round(best_fit.residual_rms, 3)
            if best_fit.residual_rms is not None
            else None,
            _rounded(best_fit.residual_ratio),
            round(len(best_reference.samples) / ANALYSIS_RATE * 1000, 3),
        )

    def _record_baseline(self, result: MicrophoneAnalysis) -> None:
        if result.playback_active:
            self.playback_baseline_samples += 1
            if result.best_corr is not None:
                self._playback_baseline_corr.append(result.best_corr)
        else:
            self.idle_baseline_samples += 1
            if result.best_corr is not None:
                self._idle_baseline_corr.append(result.best_corr)

    def _process_speech_start(self, job: SpeechStartJob) -> None:
        with self._lock:
            self._pending_speech_starts.append(job)
            latest = (
                self._microphone_history[-1].timestamp
                if self._microphone_history
                else job.timestamp
            )
            self._finalize_ready(latest)

    def _finalize_ready(self, latest_timestamp: float, *, force: bool = False) -> None:
        remaining: list[SpeechStartJob] = []
        for speech_start in self._pending_speech_starts:
            ready_at = speech_start.timestamp + SPEECH_START_POST_MS / 1000
            if force or latest_timestamp >= ready_at:
                self._finalize_snapshot(speech_start)
            else:
                remaining.append(speech_start)
        self._pending_speech_starts = remaining

    def _finalize_snapshot(self, speech_start: SpeechStartJob) -> None:
        window_start = speech_start.timestamp - SPEECH_START_PRE_MS / 1000
        window_end = speech_start.timestamp + SPEECH_START_POST_MS / 1000
        candidates = [
            item
            for item in self._microphone_history
            if window_start <= item.timestamp <= window_end
        ]
        correlated = [item for item in candidates if item.best_abs_corr is not None]
        best = max(correlated, key=lambda item: item.best_abs_corr or 0.0, default=None)
        representative = best or min(
            candidates,
            key=lambda item: abs(item.timestamp - speech_start.timestamp),
            default=None,
        )
        abs_correlations = [
            item.best_abs_corr
            for item in correlated
            if item.best_abs_corr is not None
        ]
        residuals = [
            item.residual_ratio
            for item in correlated
            if item.residual_ratio is not None
        ]
        mic_rms_values = [item.mic_rms for item in candidates]
        snapshot: dict[str, object] = {
            "item_id": speech_start.item_id,
            "timestamp": speech_start.wall_timestamp,
            "playback_active": bool(
                speech_start.current_response_id
                or any(item.playback_active for item in candidates)
            ),
            "current_response_id": speech_start.current_response_id,
            "current_playback_epoch": speech_start.current_epoch,
            "matched_response_id": best.matched_response_id if best else None,
            "matched_epoch": best.matched_epoch if best else None,
            "best_corr": best.best_corr if best else None,
            "best_abs_corr": best.best_abs_corr if best else None,
            "best_lag_ms": best.best_lag_ms if best else None,
            "mic_rms": representative.mic_rms if representative else None,
            "playback_ref_rms": best.playback_ref_rms if best else None,
            "energy_ratio": best.energy_ratio if best else None,
            "echo_fit_gain": best.echo_fit_gain if best else None,
            "residual_rms": best.residual_rms if best else None,
            "residual_ratio": best.residual_ratio if best else None,
            "reference_coverage_ms": best.reference_coverage_ms if best else 0.0,
            "correlation_available": best is not None,
            "context_pre_ms": SPEECH_START_PRE_MS,
            "context_post_ms": SPEECH_START_POST_MS,
            "context_samples": len(candidates),
            "context_max_abs_corr": max(abs_correlations)
            if abs_correlations
            else None,
            "context_median_abs_corr": round(statistics.median(abs_correlations), 6)
            if abs_correlations
            else None,
            "context_min_residual_ratio": min(residuals) if residuals else None,
            "context_median_residual_ratio": round(statistics.median(residuals), 6)
            if residuals
            else None,
            "mic_rms_trend": round(mic_rms_values[-1] - mic_rms_values[0], 3)
            if len(mic_rms_values) >= 2
            else None,
        }
        self._speech_start_snapshots.append(snapshot)
        if best is not None:
            if best.best_corr is not None:
                self._speech_corr.append(best.best_corr)
            if best.best_abs_corr is not None:
                self._speech_abs_corr.append(best.best_abs_corr)
            if best.best_lag_ms is not None:
                self._speech_lag.append(best.best_lag_ms)
            if best.residual_ratio is not None:
                self._speech_residual.append(best.residual_ratio)

    def close(self, timeout: float = 1.5) -> None:
        with self._lock:
            self._accepting = False
            worker = self._worker
        if worker is not None and worker.is_alive():
            while True:
                try:
                    self._queue.put_nowait(self._sentinel)
                    break
                except queue.Full:
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        continue
                    with self._lock:
                        self.diagnostic_jobs_dropped += 1
            if worker is not threading.current_thread():
                worker.join(timeout)
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
            with self._lock:
                self.diagnostic_jobs_dropped += 1
        with self._lock:
            self._finalize_ready(float("inf"), force=True)
            self._playback_history.clear()

    def wait_until_processed(self, timeout: float = 1.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                complete = (
                    self.diagnostic_jobs_processed
                    + self.diagnostic_jobs_failed
                    + self.diagnostic_jobs_dropped
                    >= self.diagnostic_jobs_enqueued
                )
            if complete and self._queue.empty():
                return
            time.sleep(0.001)
        raise TimeoutError("Correlation probe did not process queued diagnostics in time.")

    def report(self) -> dict[str, object]:
        with self._lock:
            return {
                "probe_enabled": True,
                "analysis_only": True,
                "input_rate_hz": INPUT_RATE,
                "output_rate_hz": OUTPUT_RATE,
                "analysis_rate_hz": ANALYSIS_RATE,
                "analysis_decimation": ANALYSIS_DECIMATION,
                "minimum_correlation_samples": MIN_CORRELATION_SAMPLES,
                "minimum_analysis_rms": MIN_ANALYSIS_RMS,
                "playback_reference_history_ms": PLAYBACK_REFERENCE_HISTORY_MS,
                "max_lag_search_ms": MAX_LAG_SEARCH_MS,
                "speech_start_context_pre_ms": SPEECH_START_PRE_MS,
                "speech_start_context_post_ms": SPEECH_START_POST_MS,
                "speech_start_snapshots_count": len(self._speech_start_snapshots),
                "speech_start_snapshots_pending": len(self._pending_speech_starts),
                "playback_baseline_samples": self.playback_baseline_samples,
                "idle_baseline_samples": self.idle_baseline_samples,
                "diagnostic_queue_capacity": self._queue.maxsize,
                "diagnostic_jobs_enqueued": self.diagnostic_jobs_enqueued,
                "diagnostic_jobs_processed": self.diagnostic_jobs_processed,
                "diagnostic_jobs_dropped": self.diagnostic_jobs_dropped,
                "diagnostic_jobs_failed": self.diagnostic_jobs_failed,
                "raw_reference_samples_retained_in_memory": sum(
                    len(reference.samples) for reference in self._playback_history
                ),
                "speech_start_best_corr": scalar_distribution(self._speech_corr),
                "speech_start_best_abs_corr": scalar_distribution(
                    self._speech_abs_corr
                ),
                "speech_start_best_lag_ms": scalar_distribution(self._speech_lag),
                "speech_start_residual_ratio": scalar_distribution(
                    self._speech_residual
                ),
                "playback_baseline_corr": scalar_distribution(
                    self._playback_baseline_corr
                ),
                "idle_baseline_corr": scalar_distribution(self._idle_baseline_corr),
                "speech_start_snapshots": [
                    dict(snapshot) for snapshot in self._speech_start_snapshots
                ],
            }

    def latest_analysis(self) -> dict[str, object] | None:
        with self._lock:
            if not self._microphone_history:
                return None
            return asdict(self._microphone_history[-1])


def _rounded(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None
