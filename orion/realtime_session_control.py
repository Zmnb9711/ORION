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
    def __init__(self, core_json: CoreJson) -> None:
        self._core_json = core_json
        self._lock = Lock()

    def status(self) -> Mapping[str, object]:
        return self._core_json("/v1/realtime/live/status")

    def request_start(self, payload_factory: StartPayloadFactory) -> RealtimeControlResult:
        if not self._lock.acquire(blocking=False):
            return RealtimeControlResult("start", False, None, "transition", "Realtime command already in progress", "transition_in_progress")
        try:
            current = self.status()
            if str(current.get("state", "")).casefold() in {"starting", "connected", "streaming"}:
                return RealtimeControlResult(
                    "start", False, str(current.get("provider") or "") or None,
                    str(current.get("state")), "A realtime provider is already active", "already_active"
                )
            result = self._core_json("/v1/realtime/live/start", method="POST", payload=payload_factory())
            return self._result("start", result)
        finally:
            self._lock.release()

    def request_stop(self) -> RealtimeControlResult:
        if not self._lock.acquire(blocking=False):
            return RealtimeControlResult("stop", False, None, "transition", "Realtime command already in progress", "transition_in_progress")
        try:
            result = self._core_json("/v1/realtime/live/stop", method="POST")
            return self._result("stop", result)
        finally:
            self._lock.release()

    @staticmethod
    def _result(action: str, result: Mapping[str, object]) -> RealtimeControlResult:
        return RealtimeControlResult(
            action, True, str(result.get("provider") or "") or None,
            str(result.get("state", "unknown")), str(result.get("message", ""))
        )
