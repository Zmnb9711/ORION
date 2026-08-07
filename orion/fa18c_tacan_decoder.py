from __future__ import annotations

from dataclasses import dataclass

from .fa18c_mapping_registry import HornetArgumentMapping
from .fa18c_value_profiles import HornetValueProfileSet, hornet_value_profile_registry


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
    profiles: HornetValueProfileSet | None = None,
) -> HornetTacanSemanticState:
    """Decode TACAN only from a validated ID map and calibrated semantic value profiles."""
    selected_profiles = profiles or hornet_value_profile_registry.current()
    if (
        not mapping_validated
        or mapping is None
        or not mapping.validated
        or not mapping.complete()
        or mapping_version != mapping.version
        or selected_profiles is None
        or selected_profiles.mapping_version != mapping.version
    ):
        return HornetTacanSemanticState(None, None, None)

    power = _semantic(selected_profiles, "tacan_power", raw_arguments.get("tacan_power"))
    tens = _semantic(selected_profiles, "tacan_channel_tens", raw_arguments.get("tacan_channel_tens"))
    ones = _semantic(selected_profiles, "tacan_channel_ones", raw_arguments.get("tacan_channel_ones"))
    xy = _semantic(selected_profiles, "tacan_xy", raw_arguments.get("tacan_xy"))

    enabled = power if isinstance(power, bool) else None
    tens_digit = tens if isinstance(tens, int) and not isinstance(tens, bool) and 0 <= tens <= 9 else None
    ones_digit = ones if isinstance(ones, int) and not isinstance(ones, bool) and 0 <= ones <= 9 else None
    channel = None if tens_digit is None or ones_digit is None else tens_digit * 10 + ones_digit
    band = xy if isinstance(xy, str) and xy in {"X", "Y"} else None
    return HornetTacanSemanticState(enabled, channel, band)


def _semantic(profiles: HornetValueProfileSet, control: str, value: float | None) -> int | str | bool | None:
    profile = profiles.control(control)
    if profile is None:
        return None
    if profile.semantic_values:
        return profile.semantic(value)

    # Backward compatibility for v1 profiles created before semantic labels existed.
    index = profile.nearest_index(value)
    if index is None:
        return None
    if control == "tacan_power":
        return index > 0
    if control in {"tacan_channel_tens", "tacan_channel_ones"}:
        return index if index <= 9 else None
    if control == "tacan_xy":
        return "X" if index == 0 else "Y" if index == 1 else None
    return None
