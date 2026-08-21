from __future__ import annotations

import importlib
import math
import threading
import time
from collections.abc import Callable
from types import ModuleType

from pydantic import BaseModel

from orion.windows_wasapi_backend import WasapiDirection


class PortAudioEndpointIdentity(BaseModel):
    direction: WasapiDirection
    device_index: int
    device_name: str
    host_api_index: int
    host_api_name: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: int | None

    def matches(
        self,
        endpoint: PortAudioEndpoint,
        *,
        include_device_index: bool = True,
    ) -> bool:
        return (
            (not include_device_index or endpoint.device_index == self.device_index)
            and endpoint.direction is self.direction
            and endpoint.device_name.casefold() == self.device_name.casefold()
            and endpoint.host_api_index == self.host_api_index
            and endpoint.host_api_name.casefold() == self.host_api_name.casefold()
            and endpoint.max_input_channels == self.max_input_channels
            and endpoint.max_output_channels == self.max_output_channels
            and endpoint.default_samplerate == self.default_samplerate
        )


class PortAudioEndpoint(PortAudioEndpointIdentity):
    device_id: str
    name: str
    is_default: bool = False
    active: bool = True

    def identity(self) -> PortAudioEndpointIdentity:
        return PortAudioEndpointIdentity.model_validate(
            self.model_dump(
                include={
                    "direction",
                    "device_index",
                    "device_name",
                    "host_api_index",
                    "host_api_name",
                    "max_input_channels",
                    "max_output_channels",
                    "default_samplerate",
                }
            )
        )


class PortAudioEndpointResolutionError(ValueError):
    pass


def portaudio_device_id(
    direction: WasapiDirection,
    host_api_index: int,
    device_index: int,
) -> str:
    return (
        f"sounddevice:portaudio:{direction.value}:"
        f"{host_api_index}:{device_index}"
    )


def _reported_rate(value: object) -> int | None:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric <= 0:
        return None
    return max(1, round(numeric))


def enumerate_portaudio_endpoints(sd: object) -> list[PortAudioEndpoint]:
    devices = list(sd.query_devices())  # type: ignore[attr-defined]
    host_apis = list(sd.query_hostapis())  # type: ignore[attr-defined]
    try:
        default_input, default_output = sd.default.device  # type: ignore[attr-defined]
    except (AttributeError, TypeError, ValueError):
        default_input, default_output = -1, -1

    result: list[PortAudioEndpoint] = []
    for device_index, raw in enumerate(devices):
        device = dict(raw)
        host_api_index = int(device.get("hostapi", -1))
        host_api_name = (
            str(host_apis[host_api_index].get("name", host_api_index))
            if 0 <= host_api_index < len(host_apis)
            else str(host_api_index)
        )
        name = str(device.get("name") or f"PortAudio device {device_index}")
        max_input = int(device.get("max_input_channels", 0) or 0)
        max_output = int(device.get("max_output_channels", 0) or 0)
        default_rate = _reported_rate(device.get("default_samplerate"))
        common = {
            "device_index": device_index,
            "device_name": name,
            "name": name,
            "host_api_index": host_api_index,
            "host_api_name": host_api_name,
            "max_input_channels": max_input,
            "max_output_channels": max_output,
            "default_samplerate": default_rate,
        }
        if max_input > 0:
            direction = WasapiDirection.INPUT
            result.append(
                PortAudioEndpoint(
                    **common,
                    direction=direction,
                    device_id=portaudio_device_id(
                        direction, host_api_index, device_index
                    ),
                    is_default=device_index == int(default_input),
                )
            )
        if max_output > 0:
            direction = WasapiDirection.OUTPUT
            result.append(
                PortAudioEndpoint(
                    **common,
                    direction=direction,
                    device_id=portaudio_device_id(
                        direction, host_api_index, device_index
                    ),
                    is_default=device_index == int(default_output),
                )
            )
    return result


def _legacy_wasapi_index(
    selector: str,
    direction: WasapiDirection,
) -> int | None:
    prefix = f"sounddevice:wasapi:{direction.value}:"
    if not selector.casefold().startswith(prefix):
        return None
    try:
        return int(selector[len(prefix) :])
    except ValueError:
        return None


def resolve_portaudio_endpoint(
    endpoints: list[PortAudioEndpoint],
    selector: str,
    direction: WasapiDirection,
    *,
    identity: PortAudioEndpointIdentity | None = None,
) -> PortAudioEndpoint:
    candidates = [
        item for item in endpoints if item.direction is direction and item.active
    ]
    if not candidates:
        raise PortAudioEndpointResolutionError(
            f"No active PortAudio {direction.value} endpoints are available"
        )

    if selector == "default":
        return next((item for item in candidates if item.is_default), candidates[0])

    if identity is not None:
        if identity.direction is not direction:
            raise PortAudioEndpointResolutionError(
                f"Selected PortAudio endpoint direction mismatch: persisted "
                f"{identity.direction.value}, requested {direction.value}"
            )
        expected_selector = portaudio_device_id(
            direction,
            identity.host_api_index,
            identity.device_index,
        )
        if selector != expected_selector:
            raise PortAudioEndpointResolutionError(
                f"Selected PortAudio {direction.value} endpoint ID does not match "
                f"its persisted identity: {selector} != {expected_selector}"
            )
        indexed = next(
            (
                item
                for item in candidates
                if item.device_index == identity.device_index
            ),
            None,
        )
        if indexed is not None and identity.matches(indexed):
            return indexed
        if indexed is None:
            raise PortAudioEndpointResolutionError(
                f"Selected PortAudio {direction.value} endpoint index is stale or "
                f"unavailable: #{identity.device_index} "
                f"{identity.device_name} [{identity.host_api_name}]; "
                "refresh devices and select it again"
            )
        raise PortAudioEndpointResolutionError(
            f"Selected PortAudio {direction.value} endpoint identity no longer "
            f"matches index #{identity.device_index}: expected "
            f"{identity.device_name} [{identity.host_api_name}]; "
            f"found {indexed.device_name} [{indexed.host_api_name}]; "
            "refresh devices and select it again"
        )

    exact = next((item for item in candidates if item.device_id == selector), None)
    if exact is not None:
        return exact

    legacy_index = _legacy_wasapi_index(selector, direction)
    if legacy_index is not None:
        legacy = [
            item
            for item in candidates
            if item.device_index == legacy_index
            and "wasapi" in item.host_api_name.casefold()
        ]
        if len(legacy) == 1:
            return legacy[0]
        reason = "unavailable" if not legacy else "ambiguous"
        raise PortAudioEndpointResolutionError(
            f"Legacy WASAPI {direction.value} selection is {reason}; "
            "reselect the exact PortAudio endpoint"
        )

    raise PortAudioEndpointResolutionError(
        f"Selected PortAudio {direction.value} endpoint is unavailable: {selector}"
    )


def portaudio_extra_settings(
    sd: object,
    endpoint: PortAudioEndpoint,
) -> tuple[object | None, str]:
    if "wasapi" not in endpoint.host_api_name.casefold():
        return None, "host_default"
    return sd.WasapiSettings(exclusive=False), "wasapi_shared"  # type: ignore[attr-defined]


class PortAudioEndpointCatalog:
    def __init__(
        self,
        provider: Callable[[], list[PortAudioEndpoint]] | None = None,
        *,
        sounddevice_module: ModuleType | None = None,
        cache_ttl_s: float = 5.0,
    ) -> None:
        self._provider = provider
        self._sd = sounddevice_module
        self._cache_ttl_s = cache_ttl_s
        self._cache: list[PortAudioEndpoint] = []
        self._cache_at = 0.0
        self._lock = threading.RLock()

    def _sounddevice(self) -> ModuleType:
        if self._sd is None:
            self._sd = importlib.import_module("sounddevice")
        return self._sd

    def refresh(self) -> list[PortAudioEndpoint]:
        source = (
            self._provider()
            if self._provider is not None
            else enumerate_portaudio_endpoints(self._sounddevice())
        )
        result = [item.model_copy(deep=True) for item in source]
        with self._lock:
            self._cache = [item.model_copy(deep=True) for item in result]
            self._cache_at = time.monotonic()
        return result

    def endpoints(
        self,
        direction: WasapiDirection | None = None,
    ) -> list[PortAudioEndpoint]:
        now = time.monotonic()
        with self._lock:
            valid = self._cache and now - self._cache_at < self._cache_ttl_s
            cached = (
                [item.model_copy(deep=True) for item in self._cache]
                if valid
                else None
            )
        result = cached if cached is not None else self.refresh()
        if direction is None:
            return result
        return [item for item in result if item.direction is direction]

    def inputs(self) -> list[PortAudioEndpoint]:
        return self.endpoints(WasapiDirection.INPUT)

    def outputs(self) -> list[PortAudioEndpoint]:
        return self.endpoints(WasapiDirection.OUTPUT)


portaudio_endpoint_catalog = PortAudioEndpointCatalog()
