from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

from pydantic import BaseModel


class WasapiEndpoint(BaseModel):
    device_id: str
    name: str
    is_default: bool = False
    active: bool = True


class WasapiEndpointCatalog:
    """Enumerates Windows render endpoints without coupling ORION Core to COM objects.

    Native enumeration is delegated to a local helper/PowerShell command. Tests can inject
    deterministic endpoint providers on any platform.
    """

    def __init__(self, provider: Callable[[], list[WasapiEndpoint]] | None = None) -> None:
        self._provider = provider

    @property
    def available(self) -> bool:
        return self._provider is not None or os.name == "nt"

    def endpoints(self) -> list[WasapiEndpoint]:
        if self._provider is not None:
            return [item.model_copy(deep=True) for item in self._provider()]
        if os.name != "nt":
            return []
        # Windows exposes stable PnP identifiers even when a full CoreAudio COM helper is not
        # installed. This discovery is sufficient for selection/configuration; exact playback
        # routing is performed by an injected WASAPI player implementation.
        script = (
            "Get-PnpDevice -Class AudioEndpoint -PresentOnly | "
            "Where-Object {$_.Status -eq 'OK'} | "
            "Select-Object InstanceId,FriendlyName | ConvertTo-Json -Compress"
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return []
        import json

        raw = json.loads(completed.stdout)
        rows = raw if isinstance(raw, list) else [raw]
        return [
            WasapiEndpoint(device_id=str(row.get("InstanceId", "")), name=str(row.get("FriendlyName", "Audio endpoint")))
            for row in rows
            if row.get("InstanceId")
        ]

    def choose(self, selector: str | None) -> WasapiEndpoint | None:
        endpoints = [item for item in self.endpoints() if item.active]
        if not endpoints:
            return None
        if not selector or selector == "default":
            return next((item for item in endpoints if item.is_default), endpoints[0])
        lowered = selector.casefold()
        exact = next((item for item in endpoints if item.device_id.casefold() == lowered), None)
        if exact is not None:
            return exact
        by_name = [item for item in endpoints if lowered in item.name.casefold()]
        return by_name[0] if by_name else None


class WasapiPlaybackBackend:
    """Explicit-device playback boundary.

    The concrete player is injected so production can use pycaw, sounddevice, a small native
    helper, or another WASAPI implementation without changing the worker state machine.
    """

    def __init__(
        self,
        catalog: WasapiEndpointCatalog,
        play_impl: Callable[[Path, WasapiEndpoint, float], None],
        stop_impl: Callable[[], None],
    ) -> None:
        self._catalog = catalog
        self._play_impl = play_impl
        self._stop_impl = stop_impl

    def play_wav(self, path: Path, device_selector: str = "default", volume: float = 1.0) -> WasapiEndpoint:
        if not path.exists():
            raise FileNotFoundError(path)
        endpoint = self._catalog.choose(device_selector)
        if endpoint is None:
            raise RuntimeError(f"WASAPI output endpoint not found: {device_selector}")
        self._play_impl(path, endpoint, volume)
        return endpoint

    def stop(self) -> None:
        self._stop_impl()


def looks_like_vr_audio(endpoint: WasapiEndpoint) -> bool:
    name = endpoint.name.casefold()
    markers = ("pimax", "dream air", "vr", "headset", "oculus", "vive", "index")
    return any(marker in name for marker in markers)
