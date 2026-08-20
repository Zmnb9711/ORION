from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from collections.abc import Callable, Mapping


CoreJson = Callable[..., Mapping[str, object]]
StartPayloadFactory = Callable[[], dict[str, object]]


@dataclass(slots=True, frozen=True)
class QwenControlResult:
    action: str
    executed: bool
    state: str
    message: str
    ignored_reason: str | None = None


class QwenSessionController:
    """Serializes Launcher and hardware commands onto the one Core lifecycle."""

    def __init__(self, core_json: CoreJson) -> None:
        self._core_json = core_json
        self._lock = Lock()
        self._in_flight: str | None = None

    def status(self) -> Mapping[str, object]:
        return self._core_json("/v1/realtime/qwen/live")

    def request_start(self, payload_factory: StartPayloadFactory) -> QwenControlResult:
        return self._operate("start", payload_factory)

    def request_stop(self) -> QwenControlResult:
        return self._operate("stop", None)

    def toggle(self, payload_factory: StartPayloadFactory) -> QwenControlResult:
        if not self._lock.acquire(blocking=False):
            return self._transition_result("toggle")
        try:
            self._in_flight = "toggle"
            status = self.status()
            state = str(status.get("state", "unknown")).casefold()
            if state in {"starting"}:
                return QwenControlResult(
                    action="toggle",
                    executed=False,
                    state=state,
                    message="Qwen startup is still in progress",
                    ignored_reason="starting",
                )
            if state in {"connected", "streaming"}:
                return self._operate_locked("stop", None)
            return self._operate_locked("start", payload_factory)
        finally:
            self._in_flight = None
            self._lock.release()

    def _operate(self, action: str, payload_factory: StartPayloadFactory | None) -> QwenControlResult:
        if not self._lock.acquire(blocking=False):
            return self._transition_result(action)
        try:
            return self._operate_locked(action, payload_factory)
        finally:
            self._lock.release()

    def _transition_result(self, action: str) -> QwenControlResult:
        return QwenControlResult(
            action=action,
            executed=False,
            state="transition",
            message=f"Qwen {self._in_flight or 'command'} is already in progress",
            ignored_reason="transition_in_progress",
        )

    def _operate_locked(self, action: str, payload_factory: StartPayloadFactory | None) -> QwenControlResult:
        previous = self._in_flight
        self._in_flight = action
        try:
            if action == "start":
                status = self.status()
                current = str(status.get("state", "unknown")).casefold()
                if current in {"starting", "connected", "streaming"}:
                    return QwenControlResult(
                        action=action,
                        executed=False,
                        state=current,
                        message="The Core-owned Qwen session is already active",
                        ignored_reason="already_active",
                    )
                if payload_factory is None:
                    raise ValueError("Qwen start payload is unavailable")
                result = self._core_json(
                    "/v1/realtime/qwen/live/start",
                    method="POST",
                    payload=payload_factory(),
                )
            else:
                result = self._core_json("/v1/realtime/qwen/live/stop", method="POST")
            state = str(result.get("state", "unknown")).casefold()
            return QwenControlResult(
                action=action,
                executed=True,
                state=state,
                message=str(result.get("message", "")),
            )
        finally:
            self._in_flight = previous
