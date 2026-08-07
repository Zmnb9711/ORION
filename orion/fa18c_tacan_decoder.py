from __future__ import annotations

from dataclasses import dataclass

from .fa18c_mapping_registry import HornetArgumentMapping


@dataclass(frozen=True)
class HornetTacanSemanticState:
    enabled: bool | None
    channel: int | None
    band: str | None


def decode_tacan(
    raw_arguments: dict[str, float | None],
    *,
    mapping_version: str | None,
    mapping_validated: bool,
    mapping: HornetArgumentMapping | None,
) -> HornetTacanSemanticState:
    """Decode Hornet TACAN controls only when DCS and ORION agree on a validated map.

    Calibration establishes *which* clickable arguments belong to the TACAN controls.
    The value decoder remains deliberately conservative: selector positions must be close
    to discrete detents, otherwise the corresponding semantic field is left unknown.
    """
    if (
        not mapping_validated
        or mapping is None
        or not mapping.validated
        or not mapping.complete()
        or mapping_version != mapping.version
    ):
        return HornetTacanSemanticState(None, None, None)

    power = _detent(raw_arguments.get("tacan_power"), maximum=4)
    tens = _digit(raw_arguments.get("tacan_channel_tens"))
    ones = _digit(raw_arguments.get("tacan_channel_ones"))
    xy = _detent(raw_arguments.get("tacan_xy"), maximum=1)

    enabled = None if power is None else power > 0
    channel = None if tens is None or ones is None else tens * 10 + ones
    band = None if xy is None else ("X" if xy == 0 else "Y")
    return HornetTacanSemanticState(enabled, channel, band)


def _digit(value: float | None) -> int | None:
    return _detent(value, maximum=9)


def _detent(value: float | None, *, maximum: int) -> int | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    numeric = float(value)
    if numeric < -0.05 or numeric > 1.05:
        return None
    scaled = numeric * maximum
    nearest = round(scaled)
    if abs(scaled - nearest) > 0.2:
        return None
    return max(0, min(maximum, int(nearest)))
