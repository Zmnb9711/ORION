from __future__ import annotations

import re
from typing import Any

MAX_PREVIEW_LENGTH = 240

_AUTHORIZATION = re.compile(
    r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;\"']+"
)
_NAMED_SECRET = re.compile(
    r"(?i)((?:api[_-]?key|token|secret|password|credential)\s*[:=]\s*[\"']?)"
    r"[^\s,;\"']+"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_LONG_TOKEN = re.compile(r"(?<![0-9a-fA-F])[A-Za-z0-9_-]{32,}(?![0-9a-fA-F])")


def redact_text(value: str) -> str:
    value = _AUTHORIZATION.sub("[REDACTED_CREDENTIAL]", value)
    value = _NAMED_SECRET.sub("[REDACTED_CREDENTIAL]", value)
    value = _BEARER.sub("Bearer [REDACTED]", value)
    return _LONG_TOKEN.sub("[REDACTED]", value)


def bounded_preview(value: Any, *, limit: int = MAX_PREVIEW_LENGTH) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).replace("\x00", " ").split())
    redacted = redact_text(normalized)
    if not redacted:
        return None
    return redacted[:limit]
