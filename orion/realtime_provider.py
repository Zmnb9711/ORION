from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class RealtimeProviderState(StrEnum):
    DISABLED = "disabled"
    CONNECTING = "connecting"
    READY = "ready"
    ERROR = "error"
    FALLBACK = "fallback"


@dataclass(slots=True, frozen=True)
class RealtimeToolDefinition:
    name: str
    provider_name: str
    description: str
    parameters: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class RealtimeSmokeResult:
    ok: bool
    provider: str
    state: RealtimeProviderState
    message: str
    tool_name: str | None = None
    tool_output: dict[str, object] | None = None
    assistant_text: str | None = None
    latency_ms: float | None = None


class RealtimeProvider(Protocol):
    """Replaceable cloud/local realtime provider boundary."""

    provider_id: str

    def test_connection(self) -> RealtimeSmokeResult:
        ...

    def test_tool_call(self) -> RealtimeSmokeResult:
        ...
