from __future__ import annotations

import hmac
import threading
from collections.abc import Callable


class CoreLifecycleController:
    """Process-local, token-bound graceful shutdown boundary for ORION Core."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token: str | None = None
        self._request_exit: Callable[[], None] | None = None

    def bind(self, token: str | None, request_exit: Callable[[], None]) -> None:
        with self._lock:
            self._token = token or None
            self._request_exit = request_exit if token else None

    def unbind(self) -> None:
        with self._lock:
            self._token = None
            self._request_exit = None

    def request_shutdown(self, token: str | None) -> bool:
        with self._lock:
            expected = self._token
            request_exit = self._request_exit
        if expected is None or request_exit is None or token is None:
            return False
        if not hmac.compare_digest(token, expected):
            return False
        request_exit()
        return True


core_lifecycle = CoreLifecycleController()
