from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


_SENSITIVE_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "credential",
    "password",
    "secret",
    "token",
)


def sanitize(value: Any, *, key: str = "") -> Any:
    normalized = key.casefold().replace("-", "_")
    if any(part in normalized for part in _SENSITIVE_PARTS):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {str(item_key): sanitize(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize(item) for item in value]
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    return value
