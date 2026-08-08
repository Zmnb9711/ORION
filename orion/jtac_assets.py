from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from orion.mission import Coalition, MissionUnit, UnitCategory
from orion.mission_store import mission_store


class JtacAssetAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class JtacAsset(BaseModel):
    unit_id: str
    name: str
    category: UnitCategory
    type_name: str | None = None
    supports_laser: bool = False
    supports_smoke: bool = False
    explicit_fac_role: bool = False
    availability: JtacAssetAvailability = JtacAssetAvailability.AVAILABLE


# Ground units are only treated as JTAC/FAC when the mission explicitly identifies
# their role. A generic HMMWV/M113/infantry unit is not enough evidence by itself.
_FAC_ROLE_MARKERS = ("jtac", "fac", "forward air controller")

# These DCS aircraft/helicopter families are legitimate potential airborne laser
# designators. Availability is still evaluated for the concrete mission unit.
_AIR_LASER_CAPABLE_TYPES = (
    "oh-58",
    "kiowa",
    "ah-64",
    "apache",
    "ka-50",
)


def available_jtac_assets(coalition: Coalition = Coalition.BLUE) -> list[JtacAsset]:
    assets: list[JtacAsset] = []
    for unit in mission_store.units(coalition=coalition, alive_only=True):
        asset = _as_asset(unit)
        if asset is not None and asset.availability is JtacAssetAvailability.AVAILABLE:
            assets.append(asset)
    return assets


def select_jtac_asset(*, requested_asset_id: str | None = None, coalition: Coalition = Coalition.BLUE) -> JtacAsset | None:
    assets = available_jtac_assets(coalition)
    if requested_asset_id:
        return next((asset for asset in assets if asset.unit_id == requested_asset_id), None)

    # Prefer an explicitly tasked FAC/JTAC, then a stable ground designator, then
    # a capable airborne designator. This preserves useful airborne fallback while
    # avoiding accidental promotion of unrelated ground vehicles to JTAC status.
    assets.sort(
        key=lambda item: (
            not item.explicit_fac_role,
            item.category is not UnitCategory.GROUND,
            item.name.casefold(),
        )
    )
    return assets[0] if assets else None


def _as_asset(unit: MissionUnit) -> JtacAsset | None:
    name_text = unit.name.casefold()
    type_text = (unit.type_name or "").casefold()
    explicit_fac_role = any(marker in name_text for marker in _FAC_ROLE_MARKERS)

    if unit.category is UnitCategory.GROUND:
        if not explicit_fac_role:
            return None
        return JtacAsset(
            unit_id=unit.unit_id,
            name=unit.name,
            category=unit.category,
            type_name=unit.type_name,
            supports_laser=True,
            supports_smoke=True,
            explicit_fac_role=True,
        )

    if unit.category in {UnitCategory.AIRCRAFT, UnitCategory.HELICOPTER}:
        laser_capable = any(marker in type_text for marker in _AIR_LASER_CAPABLE_TYPES)
        if not laser_capable and not explicit_fac_role:
            return None
        return JtacAsset(
            unit_id=unit.unit_id,
            name=unit.name,
            category=unit.category,
            type_name=unit.type_name,
            supports_laser=laser_capable or explicit_fac_role,
            supports_smoke=explicit_fac_role,
            explicit_fac_role=explicit_fac_role,
        )

    return None
