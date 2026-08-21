from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock

from pydantic import BaseModel, Field

from orion.portaudio_devices import (
    PortAudioEndpoint,
    PortAudioEndpointIdentity,
    portaudio_endpoint_catalog,
    resolve_portaudio_endpoint,
)
from orion.windows_wasapi_backend import WasapiDirection


class AudioEndpointSelection(BaseModel):
    input_device_id: str = "default"
    output_device_id: str = "default"
    input_identity: PortAudioEndpointIdentity | None = None
    output_identity: PortAudioEndpointIdentity | None = None


class AudioEndpointState(BaseModel):
    selection: AudioEndpointSelection = Field(default_factory=AudioEndpointSelection)
    resolved_input: PortAudioEndpoint | None = None
    resolved_output: PortAudioEndpoint | None = None
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
        endpoints = portaudio_endpoint_catalog.endpoints()
        input_endpoint = resolve_portaudio_endpoint(
            endpoints,
            selection.input_device_id,
            WasapiDirection.INPUT,
        )
        output_endpoint = resolve_portaudio_endpoint(
            endpoints,
            selection.output_device_id,
            WasapiDirection.OUTPUT,
        )
        persisted = AudioEndpointSelection(
            input_device_id=(
                "default"
                if selection.input_device_id == "default"
                else input_endpoint.device_id
            ),
            output_device_id=(
                "default"
                if selection.output_device_id == "default"
                else output_endpoint.device_id
            ),
            input_identity=(
                None
                if selection.input_device_id == "default"
                else input_endpoint.identity()
            ),
            output_identity=(
                None
                if selection.output_device_id == "default"
                else output_endpoint.identity()
            ),
        )
        with self._lock:
            self._selection = persisted
            self._save()
        return self.state(endpoints=endpoints)

    def state(
        self,
        *,
        endpoints: list[PortAudioEndpoint] | None = None,
    ) -> AudioEndpointState:
        current = (
            endpoints
            if endpoints is not None
            else portaudio_endpoint_catalog.endpoints()
        )
        with self._lock:
            selection = self._selection.model_copy(deep=True)
        errors: list[str] = []
        try:
            input_endpoint = resolve_portaudio_endpoint(
                current,
                selection.input_device_id,
                WasapiDirection.INPUT,
                identity=selection.input_identity,
            )
        except ValueError as exc:
            input_endpoint = None
            errors.append(str(exc))
        try:
            output_endpoint = resolve_portaudio_endpoint(
                current,
                selection.output_device_id,
                WasapiDirection.OUTPUT,
                identity=selection.output_identity,
            )
        except ValueError as exc:
            output_endpoint = None
            errors.append(str(exc))

        migrated = selection.model_copy(deep=True)
        if input_endpoint is not None and selection.input_device_id != "default":
            migrated.input_device_id = input_endpoint.device_id
            migrated.input_identity = input_endpoint.identity()
        if output_endpoint is not None and selection.output_device_id != "default":
            migrated.output_device_id = output_endpoint.device_id
            migrated.output_identity = output_endpoint.identity()
        if migrated != selection:
            with self._lock:
                self._selection = migrated.model_copy(deep=True)
                self._save()
            selection = migrated

        return AudioEndpointState(
            selection=selection,
            resolved_input=input_endpoint,
            resolved_output=output_endpoint,
            endpoint_count=len(current),
            message=(
                "PortAudio endpoint selection ready"
                if not errors
                else "; ".join(errors)
            ),
        )

    def reset(self) -> AudioEndpointState:
        with self._lock:
            self._selection = AudioEndpointSelection()
            self._save()
        return self.state()


audio_device_config = AudioDeviceConfigService()
