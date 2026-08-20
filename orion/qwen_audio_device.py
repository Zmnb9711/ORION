from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal


AudioDirection = Literal["input", "output"]


@dataclass(slots=True, frozen=True)
class AudioRateRejection:
    rate: int
    error_type: str
    message: str


@dataclass(slots=True, frozen=True)
class AudioDeviceRatePlan:
    direction: AudioDirection
    logical_device_id: str
    device_index: int
    device_name: str
    host_api: str
    default_rate: int | None
    attempted_rates: tuple[int, ...]
    rejected_rates: tuple[AudioRateRejection, ...]
    physical_rate: int
    protocol_rate: int

    @property
    def resampling_required(self) -> bool:
        return self.physical_rate != self.protocol_rate


class AudioDeviceRateError(RuntimeError):
    def __init__(
        self,
        *,
        direction: AudioDirection,
        logical_device_id: str,
        device_index: int,
        device_name: str,
        default_rate: int | None,
        attempted_rates: tuple[int, ...],
        rejected_rates: tuple[AudioRateRejection, ...],
    ) -> None:
        reasons = "; ".join(
            f"{item.rate} Hz: {item.error_type}: {item.message}"
            for item in rejected_rates
        )
        super().__init__(
            f"Selected {direction.upper()} audio endpoint cannot be opened: "
            f"{device_name} [index={device_index}, id={logical_device_id}]; "
            f"reported default={default_rate}; attempted rates={attempted_rates}; "
            f"validation errors={reasons}"
        )
        self.direction = direction
        self.logical_device_id = logical_device_id
        self.device_index = device_index
        self.device_name = device_name
        self.default_rate = default_rate
        self.attempted_rates = attempted_rates
        self.rejected_rates = rejected_rates


def _reported_rate(value: object) -> int | None:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric <= 0:
        return None
    return max(1, round(numeric))


def _candidate_rates(
    default_rate: int | None,
    direction: AudioDirection,
) -> tuple[int, ...]:
    fallbacks = (
        (48_000, 44_100, 16_000)
        if direction == "input"
        else (48_000, 44_100, 24_000)
    )
    ordered = (() if default_rate is None else (default_rate,)) + fallbacks
    return tuple(dict.fromkeys(ordered))


def negotiate_audio_device_rate(
    sd: Any,
    *,
    direction: AudioDirection,
    logical_device_id: str,
    device_index: int,
    protocol_rate: int,
    extra_settings: object,
) -> AudioDeviceRatePlan:
    try:
        device = dict(sd.query_devices(device_index))
    except Exception as exc:
        raise RuntimeError(
            f"Selected {direction.upper()} audio endpoint is unavailable: "
            f"index={device_index}, id={logical_device_id}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    device_name = str(device.get("name") or logical_device_id)
    channel_key = (
        "max_input_channels" if direction == "input" else "max_output_channels"
    )
    if int(device.get(channel_key, 0) or 0) < 1:
        raise RuntimeError(
            f"Selected {direction.upper()} audio endpoint has no {direction} channels: "
            f"{device_name} [index={device_index}, id={logical_device_id}]"
        )

    host_api = "unknown"
    try:
        host_api_index = int(device.get("hostapi", -1))
        host_api_info = sd.query_hostapis(host_api_index)
        host_api = str(host_api_info.get("name") or host_api_index)
    except Exception:
        host_api = str(device.get("hostapi", "unknown"))

    default_rate = _reported_rate(device.get("default_samplerate"))
    candidates = _candidate_rates(default_rate, direction)
    checker = (
        sd.check_input_settings
        if direction == "input"
        else sd.check_output_settings
    )
    attempted: list[int] = []
    rejected: list[AudioRateRejection] = []
    for rate in candidates:
        attempted.append(rate)
        try:
            checker(
                device=device_index,
                channels=1,
                dtype="int16",
                samplerate=rate,
                extra_settings=extra_settings,
            )
        except Exception as exc:
            rejected.append(
                AudioRateRejection(
                    rate=rate,
                    error_type=type(exc).__name__,
                    message=str(exc)[:240],
                )
            )
            continue
        return AudioDeviceRatePlan(
            direction=direction,
            logical_device_id=logical_device_id,
            device_index=device_index,
            device_name=device_name,
            host_api=host_api,
            default_rate=default_rate,
            attempted_rates=tuple(attempted),
            rejected_rates=tuple(rejected),
            physical_rate=rate,
            protocol_rate=protocol_rate,
        )

    raise AudioDeviceRateError(
        direction=direction,
        logical_device_id=logical_device_id,
        device_index=device_index,
        device_name=device_name,
        default_rate=default_rate,
        attempted_rates=tuple(attempted),
        rejected_rates=tuple(rejected),
    )
