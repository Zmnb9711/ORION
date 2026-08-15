from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class LauncherCoreClient:
    """Single HTTP/JSON boundary between Launcher UI and independent Core."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        timeout: float = 5.0,
    ) -> Any:
        if not path.startswith("/"):
            path = "/" + path
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
        except (OSError, urllib.error.URLError) as exc:
            raise RuntimeError(f"ORION Core API unavailable: {exc}") from exc
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"ORION Core returned invalid JSON for {method} {path}: {exc}") from exc
