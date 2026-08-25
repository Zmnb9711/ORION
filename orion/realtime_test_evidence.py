"""Explicit, privacy-bounded realtime field-test evidence recorder."""

from __future__ import annotations

import json
import os
import re
import threading
import zipfile
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


_ALLOWED_FIELDS = {
    "active_turn_id",
    "aircraft_type",
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
    "packet_id",
    "provider_event_id",
    "provider_item_id",
    "realtime_session_id",
    "response_created_to_first_audio_ms",
    "response_id",
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
        self._dropped = 0
        self._user_transcript_count = 0
        self._assistant_transcript_count = 0
        self._current_context_version: str | None = None
        self._last_export_path: Path | None = None

    def start(
        self,
        *,
        provider: str,
        transport: str,
        build_sha: str | None = None,
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

    def status(self) -> RealtimeTestEvidenceStatus:
        with self._lock:
            return self._status_locked()

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
            dropped = self._dropped
            user_transcript_count = self._user_transcript_count
            assistant_transcript_count = self._assistant_transcript_count
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

            manifest = (
                "ORION realtime test evidence\n"
                "format_version=2\n"
                f"test_session_id={session_id}\n"
                "members=manifest.txt,session-summary.txt,events.jsonl\n"
                "raw_audio_included=false\n"
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
            )
            summary = (
                f"test_session_id={session_id}\n"
                f"started_at={started_at.isoformat(timespec='milliseconds')}\n"
                f"stopped_at={stopped_at.isoformat(timespec='milliseconds')}\n"
                f"orion_build_sha={build_sha}\n"
                f"provider={provider}\n"
                f"transport={transport}\n"
                f"event_count={len(events)}\n"
                f"dropped_event_count={dropped}\n"
                f"user_transcript_count={user_transcript_count}\n"
                f"assistant_transcript_count={assistant_transcript_count}\n"
            )
            jsonl = "".join(
                json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
                for item in events
            )
            self._write_zip(
                output,
                {
                    "manifest.txt": manifest,
                    "session-summary.txt": summary,
                    "events.jsonl": jsonl,
                },
            )
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

    @staticmethod
    def _write_zip(output: Path, members: dict[str, str]) -> None:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(members):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                archive.writestr(info, members[name].encode("utf-8"))


realtime_test_evidence = RealtimeTestEvidenceRecorder()
