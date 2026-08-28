"""Explicit, privacy-bounded realtime field-test evidence recorder."""

from __future__ import annotations

import json
import hashlib
import io
import os
import re
import threading
import wave
import zipfile
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orion.interaction_contracts import PresentationMode, SemanticResponse


_ALLOWED_FIELDS = {
    "active_turn_id",
    "aircraft_type",
    "attempt_number",
    "boundary",
    "boundary_gap_ms",
    "boundary_owner",
    "byte_count",
    "clean",
    "close_code",
    "context_coalesced_count",
    "context_deferred_count",
    "context_fresh",
    "context_generation",
    "context_state",
    "context_update_count",
    "context_version",
    "event_id",
    "latency_latest_ms",
    "latency_maximum_ms",
    "latency_median_ms",
    "latency_p90_ms",
    "latency_sample_count",
    "local_close_owner",
    "internal_response",
    "output_modality",
    "packet_id",
    "pcm_bytes",
    "frames",
    "provider_event_id",
    "provider_item_id",
    "provider_media_generated",
    "provider_media_reached_transport",
    "client_event_id",
    "client_item_event_id",
    "client_response_event_id",
    "completion_latency_ms",
    "elapsed_ms",
    "duration_ms",
    "effective_style",
    "effective_voice",
    "error_type",
    "failure_category",
    "fact_origin",
    "first_provider_audio_latency_ms",
    "first_srs_tx_latency_ms",
    "interacted",
    "interrupted",
    "input_commit_queued",
    "http_status",
    "presentation_mode",
    "probe_case_id",
    "probe_run_id",
    "probe_selection",
    "requested_style",
    "requested_voice",
    "reason",
    "retry_exhausted",
    "retry_scheduled",
    "restoration",
    "session_id_after",
    "session_id_before",
    "session_identity_unchanged",
    "session_update_latency_ms",
    "yandex_session_id",
    "realtime_session_id",
    "response_created_to_first_audio_ms",
    "response_id",
    "reused_as_visible_response",
    "queue_to_first_tx_ms",
    "queue_to_complete_ms",
    "speech_stopped_to_first_audio_ms",
    "status",
    "turn_id",
}


@dataclass(frozen=True, slots=True)
class RealtimeTestEvidenceStatus:
    active: bool
    test_session_id: str | None = None
    started_at: str | None = None
    provider: str | None = None
    transport: str | None = None
    event_count: int = 0
    dropped_event_count: int = 0
    user_transcript_count: int = 0
    assistant_transcript_count: int = 0
    build_sha: str | None = None
    build_branch: str | None = None
    build_version: str | None = None
    last_export_path: str | None = None


class RealtimeTestEvidenceRecorder:
    """Collect scalar timing/state evidence only after an explicit start."""

    def __init__(
        self,
        runtime_dir: Path | None = None,
        *,
        max_events: int = 5000,
    ) -> None:
        if max_events <= 0:
            raise ValueError("Realtime test evidence event limit must be positive")
        self._runtime_dir = runtime_dir
        self._events: deque[dict[str, object]] = deque(maxlen=max_events)
        self._lock = threading.RLock()
        self._active = False
        self._test_session_id: str | None = None
        self._started_at: datetime | None = None
        self._provider: str | None = None
        self._transport: str | None = None
        self._build_sha: str | None = None
        self._build_branch: str | None = None
        self._build_version: str | None = None
        self._dropped = 0
        self._user_transcript_count = 0
        self._assistant_transcript_count = 0
        self._current_context_version: str | None = None
        self._last_export_path: Path | None = None
        self._probe_cases: dict[str, dict[str, object]] = {}
        self._probe_response_cases: dict[str, str] = {}
        self._hybrid_runs: dict[str, dict[str, object]] = {}
        self._hybrid_audio: dict[str, bytes] = {}
        self._live_golden_runs: dict[str, dict[str, object]] = {}
        self._live_golden_audio: dict[str, bytes] = {}

    def start(
        self,
        *,
        provider: str,
        transport: str,
        build_sha: str | None = None,
        build_branch: str | None = None,
        build_version: str | None = None,
    ) -> RealtimeTestEvidenceStatus:
        provider_value = self._identifier(provider, "provider")
        transport_value = self._identifier(transport, "transport")
        with self._lock:
            if self._active:
                raise ValueError("A realtime test session is already active")
            self._events.clear()
            self._dropped = 0
            self._user_transcript_count = 0
            self._assistant_transcript_count = 0
            self._current_context_version = None
            self._probe_cases.clear()
            self._probe_response_cases.clear()
            self._hybrid_runs.clear()
            self._hybrid_audio.clear()
            self._live_golden_runs.clear()
            self._live_golden_audio.clear()
            self._active = True
            self._test_session_id = uuid4().hex
            self._started_at = datetime.now(UTC)
            self._provider = provider_value
            self._transport = transport_value
            candidate_sha = (
                build_sha or os.environ.get("ORION_BUILD_SHA") or "unknown"
            ).strip()
            self._build_sha = (
                candidate_sha
                if candidate_sha == "unknown"
                or re.fullmatch(r"[0-9a-fA-F]{7,40}", candidate_sha)
                else "unknown"
            )
            candidate_branch = (
                build_branch or os.environ.get("ORION_BUILD_BRANCH") or "unknown"
            ).strip()
            self._build_branch = (
                candidate_branch
                if candidate_branch == "unknown"
                or re.fullmatch(r"[A-Za-z0-9._/-]{1,160}", candidate_branch)
                else "unknown"
            )
            candidate_version = (
                build_version or os.environ.get("ORION_BUILD_VERSION") or "unknown"
            ).strip()
            self._build_version = candidate_version[:80] or "unknown"
            return self._status_locked()

    def record(self, event: str, **fields: object) -> None:
        with self._lock:
            if not self._active or self._test_session_id is None:
                return
            safe_event = event.strip()
            if not safe_event or len(safe_event) > 100:
                return
            if not re.fullmatch(r"[A-Za-z0-9_.:-]+", safe_event):
                return
            safe: dict[str, object] = {
                "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "test_session_id": self._test_session_id,
                "event": safe_event,
                "provider": self._provider,
                "transport": self._transport,
            }
            for key, value in fields.items():
                if key not in _ALLOWED_FIELDS:
                    continue
                if value is None or isinstance(value, (bool, int, float, str)):
                    if isinstance(value, str):
                        if re.search(r"(?i)\b(?:authorization|api-key|bearer)\b", value):
                            continue
                        value = value[:200]
                    safe[key] = value
            context_version = safe.get("context_version")
            if isinstance(context_version, str) and context_version:
                self._current_context_version = context_version
            if len(self._events) == self._events.maxlen:
                self._dropped += 1
            self._events.append(safe)
            response_id = safe.get("response_id")
            if event in {"srs_tx_started", "tx_completed"} and isinstance(response_id, str):
                case_id = self._probe_response_cases.get(response_id)
                case = self._probe_cases.get(case_id or "")
                if case is not None and event == "srs_tx_started" and "first_srs_tx_at" not in case:
                    case["first_srs_tx_at"] = safe["timestamp"]
                    started = self._parse_timestamp(case.get("request_started_at"))
                    sent = self._parse_timestamp(safe["timestamp"])
                    if started is not None and sent is not None:
                        case["first_srs_tx_latency_ms"] = round(
                            (sent - started).total_seconds() * 1000,
                            3,
                        )
                elif case is not None and event == "tx_completed":
                    case["srs_tx_completed_at"] = safe["timestamp"]

    def record_transcript(
        self,
        role: str,
        transcript: str,
        *,
        turn_id: str | None = None,
        response_id: str | None = None,
        event_id: str | None = None,
        provider_item_id: str | None = None,
        context_version: str | None = None,
    ) -> None:
        """Record one provider-finalized transcript only in explicit test mode."""

        if role not in {"user", "assistant"}:
            raise ValueError("Realtime test transcript role must be user or assistant")
        text = self._sanitize_transcript(transcript)
        if not text:
            return
        with self._lock:
            if not self._active or self._test_session_id is None:
                return
            safe: dict[str, object] = {
                "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "test_session_id": self._test_session_id,
                "event": f"{role}_transcript",
                "provider": self._provider,
                "transport": self._transport,
                "transcript": text,
            }
            identifiers = {
                "turn_id": turn_id,
                "response_id": response_id,
                "event_id": event_id,
                "provider_item_id": provider_item_id,
                "context_version": context_version or self._current_context_version,
            }
            for key, value in identifiers.items():
                if value:
                    safe[key] = str(value)[:200]
            if len(self._events) == self._events.maxlen:
                self._dropped += 1
            self._events.append(safe)
            if role == "user":
                self._user_transcript_count += 1
            else:
                self._assistant_transcript_count += 1

    def record_probe_request(
        self,
        *,
        probe_run_id: str,
        probe_case_id: str,
        response: SemanticResponse,
        expected_presentation: str,
        requested_voice: str | None,
        requested_style: str | None,
        client_item_event_id: str,
        client_response_event_id: str,
    ) -> None:
        """Store bounded synthetic expected semantics in the existing recorder."""

        with self._lock:
            if not self._active:
                return
            now = datetime.now(UTC).isoformat(timespec="milliseconds")
            case = {
                "probe_run_id": self._identifier(probe_run_id, "probe run", max_length=40),
                "probe_case_id": self._identifier(probe_case_id, "probe case", max_length=80),
                "interaction_id": str(response.interaction_id),
                "semantic_response_id": str(response.response_id),
                "presentation_mode": response.presentation_mode.value,
                "fact_origin": "synthetic_probe",
                "authoritative_facts": [
                    {
                        "key": str(fact.key),
                        "value": fact.value,
                        "unit": fact.unit,
                    }
                    for fact in response.authoritative_facts
                ],
                "derived_results": [
                    {
                        "key": str(fact.key),
                        "value": fact.value,
                        "unit": fact.unit,
                    }
                    for fact in response.derived_results
                ],
                "recommendation": response.recommendation,
                "unavailable_inputs": [
                    {"key": str(issue.key), "status": issue.status.value}
                    for issue in response.unavailable_inputs
                ],
                "verbatim_text": response.verbatim_text,
                "expected_presentation": expected_presentation[:4000],
                "requested_voice": requested_voice,
                "requested_style": requested_style,
                "presentation_method": "conversation_item_plus_response_create",
                "per_response_instructions": True,
                "conversation_item_injection": True,
                "explicit_response_create": True,
                "session_update_required": requested_voice is not None,
                "client_item_event_id": client_item_event_id,
                "client_response_event_id": client_response_event_id,
                "request_started_at": now,
                "result": "PENDING",
            }
            self._probe_cases[probe_case_id] = case
        self.record(
            "ia1_presentation_requested",
            probe_run_id=probe_run_id,
            probe_case_id=probe_case_id,
            presentation_mode=response.presentation_mode.value,
            fact_origin="synthetic_probe",
            requested_voice=requested_voice,
            requested_style=requested_style,
            client_item_event_id=client_item_event_id,
            client_response_event_id=client_response_event_id,
        )

    def record_probe_response_created(
        self,
        *,
        probe_case_id: str,
        response_id: str,
        provider_event_id: str,
    ) -> None:
        with self._lock:
            case = self._probe_cases.get(probe_case_id)
            if case is None:
                return
            now = datetime.now(UTC).isoformat(timespec="milliseconds")
            case["yandex_response_id"] = response_id[:200]
            case["response_created_at"] = now
            self._probe_response_cases[response_id] = probe_case_id
            started = self._parse_timestamp(case.get("request_started_at"))
            created = self._parse_timestamp(now)
            if started is not None and created is not None:
                case["response_created_latency_ms"] = round(
                    (created - started).total_seconds() * 1000,
                    3,
                )
        self.record(
            "ia1_response_created",
            probe_case_id=probe_case_id,
            response_id=response_id,
            provider_event_id=provider_event_id,
        )

    def record_probe_first_audio(self, response_id: str) -> None:
        with self._lock:
            case_id = self._probe_response_cases.get(response_id)
            case = self._probe_cases.get(case_id or "")
            if case is None or "first_provider_audio_at" in case:
                return
            now = datetime.now(UTC).isoformat(timespec="milliseconds")
            case["first_provider_audio_at"] = now
            started = self._parse_timestamp(case.get("request_started_at"))
            first = self._parse_timestamp(now)
            if started is not None and first is not None:
                case["first_provider_audio_latency_ms"] = round(
                    (first - started).total_seconds() * 1000,
                    3,
                )

    def record_probe_transcript(
        self,
        *,
        probe_case_id: str,
        response_id: str,
        transcript: str,
        response: SemanticResponse,
    ) -> None:
        observed = self._sanitize_transcript(transcript)
        with self._lock:
            case = self._probe_cases.get(probe_case_id)
            if case is None:
                return
            case["observed_transcript"] = observed
            if response.presentation_mode is PresentationMode.VERBATIM:
                expected = response.verbatim_text or ""
                case["verbatim_exact_match"] = observed == expected
                case["verbatim_normalized_match"] = (
                    self._normalize_verbatim(observed)
                    == self._normalize_verbatim(expected)
                )
                case["result"] = (
                    "PASS"
                    if case["verbatim_exact_match"]
                    else (
                        "REVIEW_REQUIRED"
                        if case["verbatim_normalized_match"]
                        else "FAIL"
                    )
                )
            else:
                preserved = self._naturalize_tokens_preserved(response, observed)
                case["naturalize_tokens_preserved"] = preserved
                case["result"] = "REVIEW_REQUIRED" if preserved else "FAIL"
        self.record(
            "ia1_probe_transcript_evaluated",
            probe_case_id=probe_case_id,
            response_id=response_id,
            status=str(case["result"]),
        )

    def record_probe_completion(
        self,
        *,
        probe_run_id: str,
        probe_case_id: str,
        response_id: str,
        status: str,
        interrupted: bool,
        completion_latency_ms: float,
    ) -> None:
        with self._lock:
            case = self._probe_cases.get(probe_case_id)
            if case is None:
                return
            case["response_status"] = status[:80]
            case["interrupted"] = interrupted
            case["completion_latency_ms"] = round(completion_latency_ms, 3)
            case["completed_at"] = datetime.now(UTC).isoformat(timespec="milliseconds")
            if case.get("result") == "PENDING":
                case["result"] = "REVIEW_REQUIRED" if status == "completed" else "FAIL"
        self.record(
            "ia1_probe_case_completed",
            probe_run_id=probe_run_id,
            probe_case_id=probe_case_id,
            response_id=response_id,
            status=status,
            interrupted=interrupted,
            completion_latency_ms=completion_latency_ms,
        )

    def status(self) -> RealtimeTestEvidenceStatus:
        with self._lock:
            return self._status_locked()

    @property
    def current_context_version(self) -> str | None:
        with self._lock:
            return self._current_context_version

    def record_hybrid_run(
        self,
        *,
        run_id: str,
        main_session_id: str,
        probe_session_id: str,
        context_version_before: str | None,
    ) -> None:
        with self._lock:
            if not self._active:
                return
            self._hybrid_runs[run_id] = {
                "run_id": self._identifier(run_id, "hybrid run", max_length=40),
                "fact_origin": "synthetic_probe",
                "main_session_id": main_session_id[:200],
                "probe_session_id": probe_session_id[:200],
                "session_isolated": bool(probe_session_id and probe_session_id != main_session_id),
                "context_version_before": context_version_before or "NOT OBSERVABLE",
                "context_version_after": "NOT OBSERVABLE",
                "cases": [],
                "config_observations": [],
                "acoustic_review": "NOT OBSERVABLE",
            }

    def record_hybrid_config(
        self,
        run_id: str,
        case_id: str,
        voice: str,
        role: str,
        observations: list[dict[str, str]],
    ) -> None:
        with self._lock:
            run = self._hybrid_runs.get(run_id)
            if run is None:
                return
            configs = run["config_observations"]
            if isinstance(configs, list):
                configs.append(
                    {
                        "case_id": case_id[:80],
                        "requested_voice": voice[:40],
                        "requested_role": role[:40],
                        "observed": [
                            {
                                "voice": str(item.get("voice") or "")[:40],
                                "role": str(item.get("role") or "")[:40],
                            }
                            for item in observations[:20]
                        ],
                    }
                )

    def record_hybrid_audio(
        self,
        *,
        run_id: str,
        case_id: str,
        backend: str,
        response_id: str,
        pcm44: bytes,
    ) -> None:
        """Store only explicitly supplied, bounded synthetic probe output audio."""

        max_pcm_bytes = 44_100 * 2 * 20
        if not pcm44 or len(pcm44) % 2 or len(pcm44) > max_pcm_bytes:
            raise ValueError("Hybrid probe audio must be bounded PCM16 mono (20 seconds max)")
        with self._lock:
            if not self._active or run_id not in self._hybrid_runs:
                return
            if sum(map(len, self._hybrid_audio.values())) + len(pcm44) > 40 * 1024 * 1024:
                raise ValueError("Hybrid probe audio exceeded the 40 MiB session bound")
            safe_case = self._identifier(case_id, "hybrid case", max_length=80)
            safe_backend = self._identifier(backend, "hybrid backend", max_length=20)
            name = f"ia11-audio/{safe_case}-{safe_backend}.wav"
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(44_100)
                output.writeframes(pcm44)
            wav = buffer.getvalue()
            self._hybrid_audio[name] = wav
            run = self._hybrid_runs[run_id]
            artifacts = run.setdefault("audio_artifacts", [])
            if isinstance(artifacts, list):
                artifacts.append(
                    {
                        "case_id": safe_case,
                        "backend": safe_backend,
                        "response_id": response_id[:200],
                        "filename": name,
                        "sha256": hashlib.sha256(wav).hexdigest(),
                        "bytes": len(wav),
                        "sample_rate": 44_100,
                        "channels": 1,
                        "sample_width_bytes": 2,
                        "source": "synthetic_provider_output_entering_srs",
                    }
                )

    def record_hybrid_case(
        self,
        *,
        run_id: str,
        case: object,
        backend: str,
        response_id: str,
        transcript: str,
        evaluation: dict[str, object],
        provider_timing: dict[str, float],
        queue_latency_ms: float,
        tx_timing: dict[str, float],
    ) -> None:
        with self._lock:
            run = self._hybrid_runs.get(run_id)
            if run is None:
                return
            cases = run["cases"]
            if not isinstance(cases, list):
                return
            cases.append(
                {
                    "case_id": str(getattr(case, "case_id", "unknown"))[:80],
                    "backend": backend[:20],
                    "finalized_text": self._sanitize_transcript(str(getattr(case, "finalized_text", "")), max_length=1000),
                    "observed_transcript": self._sanitize_transcript(transcript, max_length=1000) or "NOT OBSERVABLE",
                    "voice": str(getattr(case, "voice", ""))[:40],
                    "role": str(getattr(case, "role", ""))[:40],
                    "response_id": response_id[:200],
                    "text_validation": evaluation,
                    "acoustic_review": "NOT OBSERVABLE",
                    "request_to_first_audio_ms": round(float(provider_timing.get("provider_first_audio_ms", 0.0)), 3),
                    "request_to_audio_complete_ms": round(float(provider_timing.get("provider_complete_ms", 0.0)), 3),
                    "request_to_srs_queue_ms": round(queue_latency_ms, 3),
                    "srs_queue_to_first_tx_ms": round(float(tx_timing.get("queue_to_first_tx_ms", 0.0)), 3),
                    "srs_queue_to_tx_complete_ms": round(float(tx_timing.get("queue_to_complete_ms", 0.0)), 3),
                }
            )

    def record_hybrid_isolation(
        self,
        *,
        run_id: str,
        main_session_id: str,
        probe_session_id: str,
        context_version_before: str | None,
        context_version_after: str | None,
    ) -> None:
        with self._lock:
            run = self._hybrid_runs.get(run_id)
            if run is None:
                return
            run["main_session_id_after"] = main_session_id[:200]
            run["probe_session_id_after"] = probe_session_id[:200]
            run["session_isolated"] = bool(probe_session_id and probe_session_id != main_session_id)
            run["context_version_before"] = context_version_before or "NOT OBSERVABLE"
            run["context_version_after"] = context_version_after or "NOT OBSERVABLE"
            run["context_unchanged"] = (
                context_version_before == context_version_after
                if context_version_before is not None and context_version_after is not None
                else "NOT OBSERVABLE"
            )

    def record_hybrid_review(self, run_id: str, result: str) -> None:
        with self._lock:
            run = self._hybrid_runs.get(run_id)
            if run is not None:
                run["acoustic_review"] = result[:40]

    def record_live_golden_run(
        self,
        *,
        run_id: str,
        main_session_id: str,
        mode: str,
        communication_profile: str,
        config_fingerprint: str,
        corpus: tuple[dict[str, object], ...],
        capture_audio: bool,
    ) -> None:
        """Register one bounded real-speech Golden field session."""

        with self._lock:
            if not self._active:
                return
            safe_run = self._identifier(run_id, "live Golden run", max_length=40)
            self._live_golden_runs[safe_run] = {
                "run_id": safe_run,
                "mode": self._sanitize_transcript(mode, max_length=80),
                "atc_context_origin": "CONTROLLED GOLDEN ATC FIXTURE",
                "main_realtime_session_id": main_session_id[:200],
                "second_microphone_owner": False,
                "second_realtime_session": False,
                "qwen_realtime_to_srs_transport": False,
                "provider_response_suppressed": True,
                "communication_profile": communication_profile[:80],
                "profile_independent_from_input_language": True,
                "config_fingerprint_sha256": config_fingerprint[:64],
                "capture_response_audio": capture_audio,
                "corpus": [self._safe_structured(item) for item in corpus[:8]],
                "cases": [],
                "state": "running",
                "failure": None,
            }

    def record_live_golden_case(
        self,
        *,
        run_id: str,
        record: dict[str, object],
    ) -> None:
        with self._lock:
            run = self._live_golden_runs.get(run_id)
            if run is None:
                return
            cases = run.get("cases")
            if isinstance(cases, list) and len(cases) < 8:
                cases.append(self._safe_structured(record))

    def record_live_golden_review(
        self,
        *,
        run_id: str,
        case_id: str,
        result: str,
    ) -> None:
        with self._lock:
            run = self._live_golden_runs.get(run_id)
            if run is None:
                return
            cases = run.get("cases")
            if not isinstance(cases, list):
                return
            for case in reversed(cases):
                if isinstance(case, dict) and case.get("case_id") == case_id:
                    case["acoustic_review"] = result[:40]
                    return

    def finish_live_golden_run(
        self,
        *,
        run_id: str,
        state: str,
        failure: str | None = None,
    ) -> None:
        with self._lock:
            run = self._live_golden_runs.get(run_id)
            if run is None:
                return
            run["state"] = state[:40]
            run["failure"] = (
                self._sanitize_transcript(failure, max_length=240)
                if failure
                else None
            )

    def record_live_golden_audio(
        self,
        *,
        run_id: str,
        case_id: str,
        response_id: str,
        pcm44: bytes,
    ) -> dict[str, object] | None:
        """Store finalized SpeechKit PCM entering SRS, never microphone or RX audio."""

        max_pcm_bytes = 44_100 * 2 * 30
        if not pcm44 or len(pcm44) % 2 or len(pcm44) > max_pcm_bytes:
            raise ValueError("Live Golden audio must be bounded PCM16 mono (30 seconds max)")
        with self._lock:
            run = self._live_golden_runs.get(run_id)
            if not self._active or run is None:
                return None
            if sum(map(len, self._live_golden_audio.values())) + len(pcm44) > 40 * 1024 * 1024:
                raise ValueError("Live Golden audio exceeded the 40 MiB session bound")
            safe_case = self._identifier(case_id, "live Golden case", max_length=80)
            name = f"live-golden-audio/{safe_case}.wav"
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(44_100)
                output.writeframes(pcm44)
            wav = buffer.getvalue()
            samples = memoryview(pcm44).cast("h")
            peak = max((abs(int(sample)) for sample in samples), default=0)
            artifact = {
                "case_id": safe_case,
                "response_id": response_id[:200],
                "filename": name,
                "sha256": hashlib.sha256(wav).hexdigest(),
                "pcm_sha256": hashlib.sha256(pcm44).hexdigest(),
                "bytes": len(wav),
                "pcm_bytes": len(pcm44),
                "sample_rate_hz": 44_100,
                "channels": 1,
                "sample_width_bytes": 2,
                "non_empty": True,
                "peak_absolute_sample": peak,
                "clipping_detected": peak >= 32_767,
                "source": "speechkit_finalized_pcm_entering_srs",
                "receiver_side_recording": False,
            }
            self._live_golden_audio[name] = wav
            artifacts = run.setdefault("audio_artifacts", [])
            if isinstance(artifacts, list):
                artifacts.append(artifact)
            return dict(artifact)

    def record_hybrid_recovery(self, run_id: str, result: dict[str, object]) -> None:
        with self._lock:
            run = self._hybrid_runs.get(run_id)
            if run is None:
                return
            run["noncritical_interruption_recovery"] = {
                "cancel_sent": bool(result.get("cancel_sent")),
                "cancelled_status": str(result.get("cancelled_status") or "NOT OBSERVABLE")[:40],
                "recovery_text_validation": result.get("recovery_text_validation", "NOT OBSERVABLE"),
                "critical_case_interrupted": bool(result.get("critical_case_interrupted")),
            }

    def stop_and_export(self) -> Path:
        with self._lock:
            if not self._active or self._started_at is None or self._test_session_id is None:
                raise ValueError("No realtime test session is active")
            stopped_at = datetime.now(UTC)
            events = tuple(dict(item) for item in self._events)
            session_id = self._test_session_id
            started_at = self._started_at
            provider = self._provider or "unknown"
            transport = self._transport or "unknown"
            build_sha = self._build_sha or "unknown"
            build_branch = self._build_branch or "unknown"
            build_version = self._build_version or "unknown"
            dropped = self._dropped
            user_transcript_count = self._user_transcript_count
            assistant_transcript_count = self._assistant_transcript_count
            probe_cases = tuple(dict(item) for item in self._probe_cases.values())
            hybrid_runs = tuple(dict(item) for item in self._hybrid_runs.values())
            hybrid_audio = dict(self._hybrid_audio)
            live_golden_runs = tuple(
                dict(item) for item in self._live_golden_runs.values()
            )
            live_golden_audio = dict(self._live_golden_audio)
            self._active = False

            root = self._runtime_dir or Path(os.environ.get("ORION_RUNTIME_DIR", "runtime"))
            output_dir = root / "test-evidence"
            output_dir.mkdir(parents=True, exist_ok=True)
            stamp = stopped_at.strftime("%Y%m%d-%H%M%S")
            output = output_dir / f"ORION-Test-Evidence-{stamp}.zip"
            suffix = 1
            while output.exists():
                output = output_dir / f"ORION-Test-Evidence-{stamp}-{suffix}.zip"
                suffix += 1

            members = "manifest.txt,session-summary.txt,events.jsonl"
            if probe_cases:
                members += ",ia1-summary.json"
            if hybrid_runs:
                members += ",ia11-summary.json"
            if hybrid_audio:
                members += "," + ",".join(sorted(hybrid_audio))
            if live_golden_runs:
                members += ",live-golden-summary.json"
            if live_golden_audio:
                members += "," + ",".join(sorted(live_golden_audio))
            manifest = (
                "ORION realtime test evidence\n"
                f"format_version={5 if live_golden_runs else (4 if hybrid_runs else 3)}\n"
                f"test_session_id={session_id}\n"
                f"members={members}\n"
                f"raw_audio_included={str(bool(hybrid_audio or live_golden_audio)).lower()}\n"
                f"synthetic_probe_audio_included={str(bool(hybrid_audio)).lower()}\n"
                f"live_golden_response_audio_included={str(bool(live_golden_audio)).lower()}\n"
                "microphone_audio_included=false\n"
                "unrelated_srs_audio_included=false\n"
                f"transcripts_included={str(bool(user_transcript_count or assistant_transcript_count)).lower()}\n"
                f"user_transcripts_included={str(bool(user_transcript_count)).lower()}\n"
                f"assistant_transcripts_included={str(bool(assistant_transcript_count)).lower()}\n"
                f"user_transcript_observability={'CAPTURED' if user_transcript_count else 'NOT OBSERVABLE'}\n"
                f"assistant_transcript_observability={'CAPTURED' if assistant_transcript_count else 'NOT OBSERVABLE'}\n"
                "system_instructions_included=false\n"
                "structured_exact_coordinates_included=false\n"
                "spoken_coordinates_may_appear_in_explicit_transcripts=true\n"
                "credentials_included=false\n"
                "external_dcs_srs_logs_included=false\n"
                f"ia1_probe_cases={len(probe_cases)}\n"
                f"ia11_probe_runs={len(hybrid_runs)}\n"
                f"ia11_audio_artifacts={len(hybrid_audio)}\n"
                f"live_golden_runs={len(live_golden_runs)}\n"
                f"live_golden_audio_artifacts={len(live_golden_audio)}\n"
            )
            summary = (
                f"test_session_id={session_id}\n"
                f"started_at={started_at.isoformat(timespec='milliseconds')}\n"
                f"stopped_at={stopped_at.isoformat(timespec='milliseconds')}\n"
                f"orion_build_sha={build_sha}\n"
                f"orion_build_branch={build_branch}\n"
                f"orion_build_version={build_version}\n"
                f"provider={provider}\n"
                f"transport={transport}\n"
                f"event_count={len(events)}\n"
                f"dropped_event_count={dropped}\n"
                f"user_transcript_count={user_transcript_count}\n"
                f"assistant_transcript_count={assistant_transcript_count}\n"
            )
            for case in probe_cases:
                case_id = str(case.get("probe_case_id") or "unknown")
                summary += (
                    f"ia1_case.{case_id}.mode={case.get('presentation_mode', 'NOT OBSERVABLE')}\n"
                    f"ia1_case.{case_id}.result={case.get('result', 'NOT OBSERVABLE')}\n"
                    f"ia1_case.{case_id}.response_latency_ms={case.get('first_provider_audio_latency_ms', 'NOT OBSERVABLE')}\n"
                    f"ia1_case.{case_id}.srs_tx_latency_ms={case.get('first_srs_tx_latency_ms', 'NOT OBSERVABLE')}\n"
                    f"ia1_case.{case_id}.interrupted={case.get('interrupted', 'NOT OBSERVABLE')}\n"
                )
            jsonl = "".join(
                json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
                for item in events
            )
            archive_members: dict[str, str | bytes] = {
                "manifest.txt": manifest,
                "session-summary.txt": summary,
                "events.jsonl": jsonl,
            }
            if probe_cases:
                archive_members["ia1-summary.json"] = json.dumps(
                    {"fact_origin": "synthetic_probe", "cases": probe_cases},
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ) + "\n"
            if hybrid_runs:
                archive_members["ia11-summary.json"] = json.dumps(
                    {
                        "scope": "IA-1.1 hybrid presentation feasibility probe",
                        "audio_privacy": {
                            "synthetic_provider_output_only": True,
                            "microphone_audio": False,
                            "radio_received_audio": False,
                        },
                        "runs": hybrid_runs,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ) + "\n"
            archive_members.update(hybrid_audio)
            if live_golden_runs:
                archive_members["live-golden-summary.json"] = json.dumps(
                    {
                        "scope": "Live Golden Conversation Mode A",
                        "classification": "FIELD EVIDENCE — HUMAN REVIEW REQUIRED",
                        "audio_privacy": {
                            "speechkit_response_entering_srs_only": True,
                            "microphone_audio": False,
                            "radio_received_audio": False,
                            "receiver_side_recording": False,
                        },
                        "runs": live_golden_runs,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ) + "\n"
            archive_members.update(live_golden_audio)
            self._write_zip(output, archive_members)
            self._last_export_path = output.resolve()
            return self._last_export_path

    def _status_locked(self) -> RealtimeTestEvidenceStatus:
        return RealtimeTestEvidenceStatus(
            active=self._active,
            test_session_id=self._test_session_id if self._active else None,
            started_at=(
                self._started_at.isoformat(timespec="milliseconds")
                if self._active and self._started_at is not None
                else None
            ),
            provider=self._provider if self._active else None,
            transport=self._transport if self._active else None,
            event_count=len(self._events) if self._active else 0,
            dropped_event_count=self._dropped if self._active else 0,
            user_transcript_count=self._user_transcript_count if self._active else 0,
            assistant_transcript_count=(
                self._assistant_transcript_count if self._active else 0
            ),
            build_sha=self._build_sha if self._active else None,
            build_branch=self._build_branch if self._active else None,
            build_version=self._build_version if self._active else None,
            last_export_path=(
                str(self._last_export_path) if self._last_export_path is not None else None
            ),
        )

    @staticmethod
    def _identifier(value: str, label: str, *, max_length: int = 40) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > max_length:
            raise ValueError(f"Realtime test {label} is invalid")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", normalized):
            raise ValueError(f"Realtime test {label} contains unsupported characters")
        return normalized

    @staticmethod
    def _sanitize_transcript(value: str, *, max_length: int = 8000) -> str:
        normalized = value.strip()[:max_length]
        if not normalized:
            return ""
        patterns = (
            r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+",
            r"(?i)\b(?:api[ _-]?key|authorization|eam[ _-]?password)\s*[:=]\s*\S+",
        )
        for pattern in patterns:
            normalized = re.sub(pattern, "[REDACTED]", normalized)
        return normalized

    @classmethod
    def _safe_structured(cls, value: object, *, depth: int = 0) -> object:
        if depth > 8:
            return "BOUND_EXCEEDED"
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return cls._sanitize_transcript(value, max_length=4000)
        if isinstance(value, dict):
            result: dict[str, object] = {}
            for key, item in list(value.items())[:80]:
                safe_key = str(key)[:80]
                if re.search(r"(?i)(?:api.?key|authorization|credential|password|secret)", safe_key):
                    continue
                result[safe_key] = cls._safe_structured(item, depth=depth + 1)
            return result
        if isinstance(value, (list, tuple)):
            return [cls._safe_structured(item, depth=depth + 1) for item in value[:100]]
        return cls._sanitize_transcript(str(value), max_length=200)

    @staticmethod
    def _parse_timestamp(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _normalize_verbatim(value: str) -> str:
        value = re.sub(r"[^\w\s.-]", " ", value.casefold())
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _naturalize_tokens_preserved(response: SemanticResponse, observed: str) -> bool:
        normalized = observed.casefold()
        checks: list[bool] = []
        for fact in response.authoritative_facts:
            checks.append(str(fact.value).casefold() in normalized)
        for issue in response.unavailable_inputs:
            if not any(
                token in normalized
                for token in ("unavailable", "unknown", "недоступ", "неизвест")
            ) and re.search(r"\b\d{1,3}\s*[xy]\b", normalized):
                return False
        if response.recommendation:
            tokens = [
                token.casefold()
                for token in re.findall(
                    r"[A-Za-zА-Яа-я0-9-]+", response.recommendation
                )
                if len(token) > 2 or any(character.isdigit() for character in token)
            ]
            checks.extend(
                token in normalized
                for token in tokens
                if any(character.isdigit() for character in token)
            )
        return all(checks) if checks else bool(response.unavailable_inputs)

    @staticmethod
    def _write_zip(output: Path, members: dict[str, str | bytes]) -> None:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(members):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                value = members[name]
                archive.writestr(info, value.encode("utf-8") if isinstance(value, str) else value)


realtime_test_evidence = RealtimeTestEvidenceRecorder()
