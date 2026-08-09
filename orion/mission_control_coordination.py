from __future__ import annotations

from pydantic import BaseModel, Field

from orion.jtac_assets import JtacAsset, available_jtac_assets
from orion.jtac_runtime import JtacDesignationMethod
from orion.tactical_situation import TacticalThreat, TacticalThreatKind, get_tactical_situation


class MissionControlAssignment(BaseModel):
    target_id: str
    target_name: str
    target_kind: TacticalThreatKind
    tactical_priority: float = Field(ge=0, le=100)
    designator_id: str
    designator_name: str
    designation_method: JtacDesignationMethod
    supports_laser: bool = False
    supports_smoke: bool = False


class MissionControlCoordinationPlan(BaseModel):
    assignments: list[MissionControlAssignment] = Field(default_factory=list)
    unassigned_target_ids: list[str] = Field(default_factory=list)
    available_designators: int = 0


def _asset_rank(asset: JtacAsset) -> tuple[bool, bool, bool, str]:
    return (
        not asset.explicit_fac_role,
        not asset.supports_laser,
        not asset.supports_smoke,
        asset.name.casefold(),
    )


def _method_for(target: TacticalThreat, asset: JtacAsset) -> JtacDesignationMethod | None:
    if target.kind is TacticalThreatKind.SAM:
        return JtacDesignationMethod.LASER if asset.supports_laser else None
    if asset.supports_laser:
        return JtacDesignationMethod.LASER
    if asset.supports_smoke:
        return JtacDesignationMethod.SMOKE
    return None


def build_mission_control_coordination_plan(*, limit: int = 5) -> MissionControlCoordinationPlan:
    situation = get_tactical_situation(limit=limit)
    surface = [
        threat
        for threat in situation.priority_threats
        if threat.kind in {TacticalThreatKind.SAM, TacticalThreatKind.GROUND, TacticalThreatKind.NAVAL}
    ]
    surface.sort(key=lambda item: (item.tactical_priority, item.score, -item.range_nm), reverse=True)

    assets = [asset for asset in available_jtac_assets() if asset.supports_laser or asset.supports_smoke]
    assets.sort(key=_asset_rank)
    remaining = list(assets)

    assignments: list[MissionControlAssignment] = []
    unassigned: list[str] = []
    for target in surface:
        selected: JtacAsset | None = None
        method: JtacDesignationMethod | None = None
        for candidate in remaining:
            candidate_method = _method_for(target, candidate)
            if candidate_method is not None:
                selected = candidate
                method = candidate_method
                break
        if selected is None or method is None:
            unassigned.append(target.unit_id)
            continue
        remaining.remove(selected)
        assignments.append(
            MissionControlAssignment(
                target_id=target.unit_id,
                target_name=target.name,
                target_kind=target.kind,
                tactical_priority=target.tactical_priority,
                designator_id=selected.unit_id,
                designator_name=selected.name,
                designation_method=method,
                supports_laser=selected.supports_laser,
                supports_smoke=selected.supports_smoke,
            )
        )

    return MissionControlCoordinationPlan(
        assignments=assignments,
        unassigned_target_ids=unassigned,
        available_designators=len(assets),
    )
