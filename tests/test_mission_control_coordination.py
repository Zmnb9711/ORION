from unittest.mock import patch

from orion.jtac_assets import JtacAsset, JtacAssetAvailability
from orion.jtac_runtime import JtacDesignationMethod
from orion.mission import UnitCategory
from orion.mission_control_coordination import build_mission_control_coordination_plan
from orion.tactical_situation import TacticalSituationSummary, TacticalThreat, TacticalThreatKind
from orion.threats import ThreatLevel


def _threat(unit_id: str, kind: TacticalThreatKind, priority: float, range_nm: float) -> TacticalThreat:
    return TacticalThreat(
        unit_id=unit_id,
        name=unit_id.upper(),
        kind=kind,
        level=ThreatLevel.HIGH,
        score=priority,
        bearing_deg=90,
        range_nm=range_nm,
        braa=f"090/{range_nm}",
        tactical_priority=priority,
    )


def _asset(unit_id: str, *, laser: bool, smoke: bool, explicit: bool = True) -> JtacAsset:
    return JtacAsset(
        unit_id=unit_id,
        name=unit_id.upper(),
        category=UnitCategory.GROUND,
        supports_laser=laser,
        supports_smoke=smoke,
        explicit_fac_role=explicit,
        availability=JtacAssetAvailability.AVAILABLE,
    )


def test_assigns_distinct_assets_to_multiple_threats() -> None:
    situation = TacticalSituationSummary(
        available=True,
        priority_threats=[
            _threat("sam-1", TacticalThreatKind.SAM, 95, 12),
            _threat("armor-1", TacticalThreatKind.GROUND, 80, 8),
        ],
    )
    assets = [_asset("jtac-1", laser=True, smoke=True), _asset("jtac-2", laser=True, smoke=True)]
    with patch("orion.mission_control_coordination.get_tactical_situation", return_value=situation), patch(
        "orion.mission_control_coordination.available_jtac_assets", return_value=assets
    ):
        plan = build_mission_control_coordination_plan()
    assert [item.target_id for item in plan.assignments] == ["sam-1", "armor-1"]
    assert {item.designator_id for item in plan.assignments} == {"jtac-1", "jtac-2"}


def test_sam_requires_laser_and_preserves_smoke_asset_for_ground_target() -> None:
    situation = TacticalSituationSummary(
        available=True,
        priority_threats=[
            _threat("sam-1", TacticalThreatKind.SAM, 95, 12),
            _threat("armor-1", TacticalThreatKind.GROUND, 80, 8),
        ],
    )
    assets = [_asset("smoke-1", laser=False, smoke=True), _asset("laser-1", laser=True, smoke=False)]
    with patch("orion.mission_control_coordination.get_tactical_situation", return_value=situation), patch(
        "orion.mission_control_coordination.available_jtac_assets", return_value=assets
    ):
        plan = build_mission_control_coordination_plan()
    assignments = {item.target_id: item for item in plan.assignments}
    assert assignments["sam-1"].designator_id == "laser-1"
    assert assignments["sam-1"].designation_method is JtacDesignationMethod.LASER
    assert assignments["armor-1"].designator_id == "smoke-1"
    assert assignments["armor-1"].designation_method is JtacDesignationMethod.SMOKE


def test_reports_unassigned_targets_when_assets_are_exhausted() -> None:
    situation = TacticalSituationSummary(
        available=True,
        priority_threats=[
            _threat("sam-1", TacticalThreatKind.SAM, 95, 12),
            _threat("sam-2", TacticalThreatKind.SAM, 90, 15),
        ],
    )
    with patch("orion.mission_control_coordination.get_tactical_situation", return_value=situation), patch(
        "orion.mission_control_coordination.available_jtac_assets", return_value=[_asset("laser-1", laser=True, smoke=True)]
    ):
        plan = build_mission_control_coordination_plan()
    assert len(plan.assignments) == 1
    assert plan.assignments[0].target_id == "sam-1"
    assert plan.unassigned_target_ids == ["sam-2"]


def test_ignores_air_threats_for_jtac_coordination() -> None:
    situation = TacticalSituationSummary(
        available=True,
        priority_threats=[
            _threat("mig-1", TacticalThreatKind.AIR, 99, 20),
            _threat("armor-1", TacticalThreatKind.GROUND, 75, 7),
        ],
    )
    with patch("orion.mission_control_coordination.get_tactical_situation", return_value=situation), patch(
        "orion.mission_control_coordination.available_jtac_assets", return_value=[_asset("jtac-1", laser=True, smoke=True)]
    ):
        plan = build_mission_control_coordination_plan()
    assert [item.target_id for item in plan.assignments] == ["armor-1"]
