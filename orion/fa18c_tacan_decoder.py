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
    """Decode TACAN only from a validated ID map and calibrated raw-value detents."""
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

    power = _profile_index(selected_profiles, "tacan_power", raw_arguments.get("tacan_power"))
    tens = _profile_index(selected_profiles, "tacan_channel_tens", raw_arguments.get("tacan_channel_tens"))
    ones = _profile_index(selected_profiles, "tacan_channel_ones", raw_arguments.get("tacan_channel_ones"))
    xy = _profile_index(selected_profiles, "tacan_xy", raw_arguments.get("tacan_xy"))

    # The calibration sequence defines detents in semantic order:
    # power: OFF then operating position; tens/ones: 0..9; X/Y: X then Y.
    enabled = None if power is None else power > 0
    channel = None if tens is None or ones is None or tens > 9 or ones > 9 else tens * 10 + ones
    band = None if xy is None or xy > 1 else ("X" if xy == 0 else "Y")
    return HornetTacanSemanticState(enabled, channel, band)


def _profile_index(profiles: HornetValueProfileSet, control: str, value: float | None) -> int | None:
    profile = profiles.control(control)
    if profile is None:
        return None
    return profile.nearest_index(value)
