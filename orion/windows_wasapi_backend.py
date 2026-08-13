from __future__ import annotations

import json
import os
import subprocess
import time
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Callable

from pydantic import BaseModel

try:
    import sounddevice as sd
except ImportError:  # pragma: no cover - optional outside Windows product builds
    sd = None


class WasapiDirection(StrEnum):
    INPUT = "input"
    OUTPUT = "output"


class WasapiEndpoint(BaseModel):
    device_id: str
    name: str
    direction: WasapiDirection = WasapiDirection.OUTPUT
    is_default: bool = False
    active: bool = True


class WasapiEndpointCatalog:
    """Enumerates Windows audio endpoints without blocking Core request threads."""

    def __init__(
        self,
        provider: Callable[[], list[WasapiEndpoint]] | None = None,
        *,
        cache_ttl_s: float = 5.0,
    ) -> None:
        self._provider = provider
        self._cache_ttl_s = cache_ttl_s
        self._cache: list[WasapiEndpoint] = []
        self._cache_at = 0.0
        self._lock = RLock()

    @property
    def available(self) -> bool:
        return self._provider is not None or os.name == "nt"

    def refresh(self) -> list[WasapiEndpoint]:
        result = self._enumerate()
        with self._lock:
            self._cache = [item.model_copy(deep=True) for item in result]
            self._cache_at = time.monotonic()
        return [item.model_copy(deep=True) for item in result]

    def endpoints(self, direction: WasapiDirection | None = None) -> list[WasapiEndpoint]:
        now = time.monotonic()
        with self._lock:
            valid = self._cache and now - self._cache_at < self._cache_ttl_s
            cached = [item.model_copy(deep=True) for item in self._cache] if valid else None
        result = cached if cached is not None else self.refresh()
        if direction is None:
            return result
        return [item for item in result if item.direction is direction]

    def _enumerate(self) -> list[WasapiEndpoint]:
        if self._provider is not None:
            return [item.model_copy(deep=True) for item in self._provider()]
        if os.name != "nt":
            return []
        fast = self._enumerate_sounddevice()
        if fast:
            return fast
        return self._enumerate_pnp_bounded()

    @staticmethod
    def _enumerate_sounddevice() -> list[WasapiEndpoint]:
        if sd is None:
            return []
        try:
            hostapis = sd.query_hostapis()
            devices = sd.query_devices()
            default_input, default_output = sd.default.device
        except Exception:
            return []
        wasapi_hosts = {
            index
            for index, item in enumerate(hostapis)
            if "wasapi" in str(item.get("name", "")).casefold()
        }
        result: list[WasapiEndpoint] = []
        for index, item in enumerate(devices):
            if wasapi_hosts and int(item.get("hostapi", -1)) not in wasapi_hosts:
                continue
            name = str(item.get("name", "Audio endpoint"))
            max_input = int(item.get("max_input_channels", 0))
            max_output = int(item.get("max_output_channels", 0))
            if max_input > 0:
                result.append(
                    WasapiEndpoint(
                        device_id=f"sounddevice:wasapi:input:{index}",
                        name=name,
                        direction=WasapiDirection.INPUT,
                        is_default=index == int(default_input),
                    )
                )
            if max_output > 0:
                result.append(
                    WasapiEndpoint(
                        device_id=f"sounddevice:wasapi:output:{index}",
                        name=name,
                        direction=WasapiDirection.OUTPUT,
                        is_default=index == int(default_output),
                    )
                )
        return result

    @staticmethod
    def _enumerate_pnp_bounded() -> list[WasapiEndpoint]:
        script = (
            "Get-PnpDevice -Class AudioEndpoint -PresentOnly | "
            "Where-Object {$_.Status -eq 'OK'} | "
            "Select-Object InstanceId,FriendlyName | ConvertTo-Json -Compress"
        )
        try:
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                check=False,
                timeout=0.75,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if completed.returncode != 0 or not completed.stdout.strip():
            return []
        try:
            raw = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return []
        rows = raw if isinstance(raw, list) else [raw]
        result: list[WasapiEndpoint] = []
        for row in rows:
            device_id = str(row.get("InstanceId", ""))
            endpoint_direction = direction_from_device_id(device_id)
            if not device_id or endpoint_direction is None:
                continue
            result.append(
                WasapiEndpoint(
                    device_id=device_id,
                    name=str(row.get("FriendlyName", "Audio endpoint")),
                    direction=endpoint_direction,
                )
            )
        return result

    def inputs(self) -> list[WasapiEndpoint]:
        return self.endpoints(WasapiDirection.INPUT)

    def outputs(self) -> list[WasapiEndpoint]:
        return self.endpoints(WasapiDirection.OUTPUT)

    def choose(
        self,
        selector: str | None,
        direction: WasapiDirection = WasapiDirection.OUTPUT,
        *,
        endpoints: list[WasapiEndpoint] | None = None,
    ) -> WasapiEndpoint | None:
        source = endpoints if endpoints is not None else self.endpoints(direction)
        candidates = [item for item in source if item.direction is direction and item.active]
        if not candidates:
            return None
        if not selector or selector == "default":
            return next((item for item in candidates if item.is_default), candidates[0])
        lowered = selector.casefold()
        exact = next((item for item in candidates if item.device_id.casefold() == lowered), None)
        if exact is not None:
            return exact
        by_name = [item for item in candidates if lowered in item.name.casefold()]
        return by_name[0] if by_name else None

    def vr_candidates(self) -> list[WasapiEndpoint]:
        return [item for item in self.outputs() if item.active and looks_like_vr_audio(item)]


class WasapiPlaybackBackend:
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
        endpoint = self._catalog.choose(device_selector, WasapiDirection.OUTPUT)
        if endpoint is None:
            raise RuntimeError(f"WASAPI output endpoint not found: {device_selector}")
        self._play_impl(path, endpoint, volume)
        return endpoint

    def stop(self) -> None:
        self._stop_impl()


def direction_from_device_id(device_id: str) -> WasapiDirection | None:
    lowered = device_id.casefold()
    if "{0.0.0." in lowered:
        return WasapiDirection.OUTPUT
    if "{0.0.1." in lowered:
        return WasapiDirection.INPUT
    return None


def looks_like_vr_audio(endpoint: WasapiEndpoint) -> bool:
    name = endpoint.name.casefold()
    markers = ("pimax", "dream air", "vr", "headset", "oculus", "vive", "index")
    return any(marker in name for marker in markers)


wasapi_endpoint_catalog = WasapiEndpointCatalog()
