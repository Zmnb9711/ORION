from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock

from pydantic import BaseModel, Field

from orion.windows_wasapi_backend import WasapiDirection, WasapiEndpoint, wasapi_endpoint_catalog


class AudioEndpointSelection(BaseModel):
    input_device_id: str = "default"
    output_device_id: str = "default"


class AudioEndpointState(BaseModel):
    selection: AudioEndpointSelection = Field(default_factory=AudioEndpointSelection)
    resolved_input: WasapiEndpoint | None = None
    resolved_output: WasapiEndpoint | None = None
    endpoint_count: int = 0
    message: str = ""


class AudioDeviceConfigService:
    """Core-owned persistent Windows audio endpoint selection."""

    def __init__(self, runtime_dir: Path | None = None) -> None:
        base = runtime_dir or Path(os.environ.get("ORION_RUNTIME_DIR", "runtime"))
        self._path = base / "audio-device-selection.json"
        self._lock = RLock()
        self._selection = self._load()

    def _load(self) -> AudioEndpointSelection:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            return AudioEndpointSelection.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValueError):
            return AudioEndpointSelection()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(self._selection.model_dump_json(indent=2), encoding="utf-8")

    def select(self, selection: AudioEndpointSelection) -> AudioEndpointState:
        endpoints = wasapi_endpoint_catalog.endpoints()
        self._validate(selection.input_device_id, WasapiDirection.INPUT, endpoints)
        self._validate(selection.output_device_id, WasapiDirection.OUTPUT, endpoints)
        with self._lock:
            self._selection = selection.model_copy(deep=True)
            self._save()
        return self.state(endpoints=endpoints)

    @staticmethod
    def _validate(selector: str, direction: WasapiDirection, endpoints: list[WasapiEndpoint]) -> None:
        if selector == "default":
            return
        if not any(item.device_id == selector and item.direction is direction and item.active for item in endpoints):
            raise ValueError(f"Selected {direction.value} audio endpoint is unavailable: {selector}")

    def state(self, *, endpoints: list[WasapiEndpoint] | None = None) -> AudioEndpointState:
        current = endpoints if endpoints is not None else wasapi_endpoint_catalog.endpoints()
        with self._lock:
            selection = self._selection.model_copy(deep=True)
        input_endpoint = wasapi_endpoint_catalog.choose(
            selection.input_device_id,
            WasapiDirection.INPUT,
            endpoints=current,
        )
        output_endpoint = wasapi_endpoint_catalog.choose(
            selection.output_device_id,
            WasapiDirection.OUTPUT,
            endpoints=current,
        )
        missing = []
        if selection.input_device_id != "default" and input_endpoint is None:
            missing.append("input")
        if selection.output_device_id != "default" and output_endpoint is None:
            missing.append("output")
        return AudioEndpointState(
            selection=selection,
            resolved_input=input_endpoint,
            resolved_output=output_endpoint,
            endpoint_count=len(current),
            message="Audio endpoint selection ready" if not missing else f"Selected {'/'.join(missing)} endpoint unavailable",
        )

    def reset(self) -> AudioEndpointState:
        with self._lock:
            self._selection = AudioEndpointSelection()
            self._save()
        return self.state()


audio_device_config = AudioDeviceConfigService()
