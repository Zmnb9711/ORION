from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel


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


class RealtimeLiveStatus(BaseModel):
    """Provider-neutral, credential-free view of one live voice session."""

    provider: str | None = None
    state: str = "stopped"
    phase: str = "idle"
    message: str = "Realtime voice is stopped"
    session_id: str | None = None
    input_name: str | None = None
    output_name: str | None = None
    input_rate: int | None = None
    output_rate: int | None = None
    input_chunks: int = 0
    output_chunks: int = 0
    last_error: str | None = None


class RealtimeLiveProvider(Protocol):
    """Minimal lifecycle boundary; transport and PCM remain provider-specific."""

    provider_id: str

    def start_live(self, payload: dict[str, Any]) -> RealtimeLiveStatus: ...

    def live_status(self) -> RealtimeLiveStatus: ...

    def stop_live(self) -> RealtimeLiveStatus: ...
