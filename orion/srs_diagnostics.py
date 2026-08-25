"""Bounded, scalar-only diagnostics for production SRS transport."""

from __future__ import annotations

import json
import os
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from orion.realtime_test_evidence import realtime_test_evidence

_FORBIDDEN = {
    "api_key",
    "authorization",
    "audio",
    "base64",
    "eam_password",
    "guid",
    "opus",
    "password",
    "pcm",
    "token",
    "transcript",
}


def sanitize_srs_error(value: object, *secrets: str) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")[:1000]
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


class SrsTransportDiagnostics:
    def __init__(
        self,
        session_id: str,
        *,
        secrets: tuple[str, ...] = (),
        runtime_dir: Path | None = None,
    ) -> None:
        self.session_id = session_id
        self._secrets = secrets
        self._events: deque[dict[str, object]] = deque(maxlen=1000)
        self._lock = threading.Lock()
        root = runtime_dir or Path(os.environ.get("ORION_RUNTIME_DIR", "runtime"))
        self.path = root / "srs-radio" / f"srs-radio-{session_id}.jsonl"

    def record(self, event: str, **fields: object) -> None:
        safe: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": sanitize_srs_error(event, *self._secrets),
            "session_id": self.session_id,
        }
        for key, value in fields.items():
            lowered = key.casefold()
            if any(token in lowered for token in _FORBIDDEN):
                continue
            if value is None or isinstance(value, (bool, int, float)):
                safe[key] = value
            elif isinstance(value, str):
                safe[key] = sanitize_srs_error(value, *self._secrets)
        with self._lock:
            self._events.append(safe)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(safe, ensure_ascii=False) + "\n")
        realtime_test_evidence.record(
            str(safe["event"]),
            realtime_session_id=self.session_id,
            transport="srs",
            **{
                key: value
                for key, value in safe.items()
                if key not in {"timestamp", "event", "session_id"}
            },
        )

    def snapshot(self) -> tuple[dict[str, object], ...]:
        with self._lock:
            return tuple(dict(item) for item in self._events)
