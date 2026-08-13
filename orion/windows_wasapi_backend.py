from __future__ import annotations

import os
import subprocess
from enum import StrEnum
from pathlib import Path
from typing import Callable

from pydantic import BaseModel


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
    """Enumerates stable Windows MMDevice endpoints without Core COM ownership."""

    def __init__(self, provider: Callable[[], list[WasapiEndpoint]] | None = None) -> None:
        self._provider = provider

    @property
    def available(self) -> bool:
        return self._provider is not None or os.name == "nt"

    def endpoints(self, direction: WasapiDirection | None = None) -> list[WasapiEndpoint]:
        if self._provider is not None:
            result = [item.model_copy(deep=True) for item in self._provider()]
        elif os.name != "nt":
            result = []
        else:
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
                result = []
            else:
                import json

                try:
                    raw = json.loads(completed.stdout)
                except json.JSONDecodeError:
                    raw = []
                rows = raw if isinstance(raw, list) else [raw]
                result = []
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
        if direction is None:
            return result
        return [item for item in result if item.direction is direction]

    def inputs(self) -> list[WasapiEndpoint]:
        return self.endpoints(WasapiDirection.INPUT)

    def outputs(self) -> list[WasapiEndpoint]:
        return self.endpoints(WasapiDirection.OUTPUT)

    def choose(self, selector: str | None, direction: WasapiDirection = WasapiDirection.OUTPUT) -> WasapiEndpoint | None:
        endpoints = [item for item in self.endpoints(direction) if item.active]
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
