from __future__ import annotations

from pydantic import BaseModel

from orion.mission import Coalition, MissionUnit, UnitCategory
from orion.mission_store import mission_store


class JtacAsset(BaseModel):
    unit_id: str
    name: str
    category: UnitCategory
    type_name: str | None = None
    supports_laser: bool = False
    supports_smoke: bool = False


_GROUND_MARKERS = ("jtac", "fac", "humvee", "hmmwv", "m113", "infantry")
_AIR_MARKERS = ("jtac", "fac", "oh-58", "kiowa", "ka-50", "ah-64", "apache")


def available_jtac_assets(coalition: Coalition = Coalition.BLUE) -> list[JtacAsset]:
    assets: list[JtacAsset] = []
    for unit in mission_store.units(coalition=coalition, alive_only=True):
        asset = _as_asset(unit)
        if asset is not None:
            assets.append(asset)
    return assets


def select_jtac_asset(*, requested_asset_id: str | None = None, coalition: Coalition = Coalition.BLUE) -> JtacAsset | None:
    assets = available_jtac_assets(coalition)
    if requested_asset_id:
        return next((asset for asset in assets if asset.unit_id == requested_asset_id), None)
    # Prefer ground FAC/JTAC assets: they are generally stable designators and do
    # not require assumptions about aircraft tasking or cockpit state.
    assets.sort(key=lambda item: (item.category is not UnitCategory.GROUND, item.name.casefold()))
    return assets[0] if assets else None


def _as_asset(unit: MissionUnit) -> JtacAsset | None:
    text = f"{unit.name} {unit.type_name or ''}".casefold()
    if unit.category is UnitCategory.GROUND:
        if not any(marker in text for marker in _GROUND_MARKERS):
            return None
        return JtacAsset(unit_id=unit.unit_id, name=unit.name, category=unit.category, type_name=unit.type_name, supports_laser=True, supports_smoke=True)
    if unit.category in {UnitCategory.AIRCRAFT, UnitCategory.HELICOPTER}:
        if not any(marker in text for marker in _AIR_MARKERS):
            return None
        return JtacAsset(unit_id=unit.unit_id, name=unit.name, category=unit.category, type_name=unit.type_name, supports_laser=True, supports_smoke=True)
    return None
