from __future__ import annotations

from dataclasses import dataclass

from .fa18c_mapping_registry import HornetArgumentMapping
from .fa18c_value_profiles import HornetValueProfileSet, hornet_value_profile_registry


@dataclass(frozen=True)
class HornetCommSemanticState:
    comm1_preset: int | None
    comm2_preset: int | None


def decode_comm_presets(
    raw_arguments: dict[str, float | None],
    *,
    mapping_version: str | None,
    mapping_validated: bool,
    mapping: HornetArgumentMapping | None,
    profiles: HornetValueProfileSet | None = None,
) -> HornetCommSemanticState:
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
        return HornetCommSemanticState(None, None)

    return HornetCommSemanticState(
        comm1_preset=_preset(selected_profiles, "comm1_selector", raw_arguments.get("comm1_selector")),
        comm2_preset=_preset(selected_profiles, "comm2_selector", raw_arguments.get("comm2_selector")),
    )


def _preset(profiles: HornetValueProfileSet, control: str, value: float | None) -> int | None:
    profile = profiles.control(control)
    if profile is None:
        return None
    semantic = profile.semantic(value)
    if isinstance(semantic, int) and not isinstance(semantic, bool) and 1 <= semantic <= 20:
        return semantic
    return None
