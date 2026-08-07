from __future__ import annotations

from pydantic import BaseModel, Field


class HornetCockpitState(BaseModel):
    aircraft_id: str = "fa-18c"
    mapping_version: str | None = None
    mapping_validated: bool = False
    raw_arguments: dict[str, float | None] = Field(default_factory=dict)

    tacan_enabled: bool | None = None
    tacan_channel: int | None = None
    tacan_band: str | None = None
    comm1_preset: int | None = None
    comm1_frequency: float | None = None
    comm2_preset: int | None = None
    comm2_frequency: float | None = None

    left_ddi_brightness_raw: float | None = None
    right_ddi_brightness_raw: float | None = None
    mpcd_brightness_raw: float | None = None


def normalize_hornet_cockpit_state(payload: object) -> HornetCockpitState | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("aircraft_id") not in (None, "fa-18c"):
        return None

    raw = payload.get("raw_arguments")
    raw_arguments: dict[str, float | None] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if value is None:
                raw_arguments[str(key)] = None
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                raw_arguments[str(key)] = float(value)

    state = HornetCockpitState(
        mapping_version=_string_or_none(payload.get("mapping_version")),
        mapping_validated=payload.get("mapping_validated") is True,
        raw_arguments=raw_arguments,
        tacan_enabled=_bool_or_none(payload.get("tacan_enabled")),
        tacan_channel=_int_or_none(payload.get("tacan_channel")),
        tacan_band=_string_or_none(payload.get("tacan_band")),
        comm1_preset=_int_or_none(payload.get("comm1_preset")),
        comm1_frequency=_float_or_none(payload.get("comm1_frequency")),
        comm2_preset=_int_or_none(payload.get("comm2_preset")),
        comm2_frequency=_float_or_none(payload.get("comm2_frequency")),
        left_ddi_brightness_raw=_raw(raw_arguments, "left_ddi_brightness"),
        right_ddi_brightness_raw=_raw(raw_arguments, "right_ddi_brightness"),
        mpcd_brightness_raw=_raw(raw_arguments, "mpcd_brightness"),
    )

    # Semantic decoding of clickable arguments is intentionally disabled until
    # the corresponding DCS argument map has been verified on a live Hornet.
    # Once mapping_validated is true, dedicated decoders can be added here
    # without changing the rest of Voice Core.
    return state


def cockpit_state_for_voice(payload: object) -> dict[str, object] | None:
    state = normalize_hornet_cockpit_state(payload)
    if state is None:
        return None
    result = state.model_dump(exclude_none=True)
    result["raw_arguments"] = state.raw_arguments
    return result


def _raw(raw: dict[str, float | None], key: str) -> float | None:
    value = raw.get(key)
    return value if isinstance(value, float) else None


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _bool_or_none(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _int_or_none(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _float_or_none(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None
