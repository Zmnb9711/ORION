from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import Lock

CoreJson = Callable[..., Mapping[str, object]]
StartPayloadFactory = Callable[[], dict[str, object]]


@dataclass(slots=True, frozen=True)
class RealtimeControlResult:
    action: str
    executed: bool
    provider: str | None
    state: str
    message: str
    ignored_reason: str | None = None


class RealtimeSessionController:
    _ACTIVE_OR_REQUIRES_STOP = {"starting", "connected", "streaming", "error"}

    def __init__(self, core_json: CoreJson) -> None:
        self._core_json = core_json
        self._lock = Lock()

    def status(self) -> Mapping[str, object]:
        return self._core_json("/v1/realtime/live/status")

    def request_start(self, payload_factory: StartPayloadFactory) -> RealtimeControlResult:
        if not self._lock.acquire(blocking=False):
            return RealtimeControlResult("start", False, None, "transition", "Realtime command already in progress", "transition_in_progress")
        try:
            return self._request_start_locked(payload_factory)
        finally:
            self._lock.release()

    def request_stop(self) -> RealtimeControlResult:
        if not self._lock.acquire(blocking=False):
            return RealtimeControlResult("stop", False, None, "transition", "Realtime command already in progress", "transition_in_progress")
        try:
            return self._request_stop_locked()
        finally:
            self._lock.release()

    def toggle(self, payload_factory: StartPayloadFactory) -> RealtimeControlResult:
        """Toggle the one Core-owned provider/transport session from actual Core state."""

        if not self._lock.acquire(blocking=False):
            return RealtimeControlResult(
                "toggle",
                False,
                None,
                "transition",
                "Realtime command already in progress",
                "transition_in_progress",
            )
        try:
            current = self.status()
            state = str(current.get("state", "stopped")).casefold()
            if state in self._ACTIVE_OR_REQUIRES_STOP:
                return self._request_stop_locked()
            return self._request_start_locked(payload_factory, current=current)
        finally:
            self._lock.release()

    def _request_start_locked(
        self,
        payload_factory: StartPayloadFactory,
        *,
        current: Mapping[str, object] | None = None,
    ) -> RealtimeControlResult:
        status = self.status() if current is None else current
        if str(status.get("state", "")).casefold() in self._ACTIVE_OR_REQUIRES_STOP:
            return RealtimeControlResult(
                "start",
                False,
                str(status.get("provider") or "") or None,
                str(status.get("state")),
                "A realtime provider must be stopped before starting",
                "already_active" if str(status.get("state", "")).casefold() != "error" else "error_requires_stop",
            )
        result = self._core_json(
            "/v1/realtime/live/start",
            method="POST",
            payload=payload_factory(),
        )
        return self._result("start", result)

    def _request_stop_locked(self) -> RealtimeControlResult:
        result = self._core_json("/v1/realtime/live/stop", method="POST")
        return self._result("stop", result)

    @staticmethod
    def _result(action: str, result: Mapping[str, object]) -> RealtimeControlResult:
        return RealtimeControlResult(
            action, True, str(result.get("provider") or "") or None,
            str(result.get("state", "unknown")), str(result.get("message", ""))
        )
