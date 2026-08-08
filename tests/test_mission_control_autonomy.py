from unittest.mock import patch

from orion.jtac_assets import JtacAsset, JtacAssetAvailability
from orion.mission import UnitCategory
from orion.mission_control_autonomy import MissionControlAction, evaluate_mission_control_autonomy
from orion.mission_control_runtime import MissionControlPicture, MissionControlReadiness
from orion.tactical_situation import TacticalThreat, TacticalThreatKind
from orion.threats import ThreatLevel


def _threat(kind: TacticalThreatKind) -> TacticalThreat:
    return TacticalThreat(
        unit_id="threat-1",
        name="SA-11" if kind is TacticalThreatKind.SAM else "armor",
        kind=kind,
        level=ThreatLevel.HIGH,
        bearing_deg=270,
        range_nm=12,
        braa="270/12",
        score=90,
    )


def _asset(*, unit_id: str = "jtac-1", laser: bool = True, smoke: bool = True, explicit: bool = True) -> JtacAsset:
    return JtacAsset(
        unit_id=unit_id,
        name="Axeman 1-1" if unit_id == "jtac-1" else "Scout 2-1",
        category=UnitCategory.GROUND,
        supports_laser=laser,
        supports_smoke=smoke,
        explicit_fac_role=explicit,
        availability=JtacAssetAvailability.AVAILABLE,
    )


def _picture(kind: TacticalThreatKind) -> MissionControlPicture:
    return MissionControlPicture(
        readiness=MissionControlReadiness.ENGAGED,
        primary_surface_threat=_threat(kind),
        total_threats=1,
    )


def test_unavailable_picture_stays_observe() -> None:
    with patch("orion.mission_control_autonomy.build_mission_control_picture", return_value=MissionControlPicture()):
        decision = evaluate_mission_control_autonomy()
    assert decision.action is MissionControlAction.OBSERVE
    assert decision.requires_pilot_confirmation is False


def test_sam_with_designator_suggests_9line() -> None:
    with patch("orion.mission_control_autonomy.build_mission_control_picture", return_value=_picture(TacticalThreatKind.SAM)), patch(
        "orion.mission_control_autonomy.available_jtac_assets", return_value=[_asset()]
    ):
        decision = evaluate_mission_control_autonomy()
    assert decision.action is MissionControlAction.SUGGEST_9LINE
    assert decision.target_id == "threat-1"
    assert decision.requires_pilot_confirmation is True
    assert decision.available_designators == 1
    assert decision.selected_designator_id == "jtac-1"
    assert decision.selected_designator_supports_laser is True


def test_non_sam_surface_threat_suggests_jtac() -> None:
    with patch("orion.mission_control_autonomy.build_mission_control_picture", return_value=_picture(TacticalThreatKind.GROUND)), patch(
        "orion.mission_control_autonomy.available_jtac_assets", return_value=[_asset()]
    ):
        decision = evaluate_mission_control_autonomy()
    assert decision.action is MissionControlAction.SUGGEST_JTAC
    assert decision.selected_designator_name == "Axeman 1-1"


def test_smoke_only_fac_can_support_jtac_but_not_laser_9line() -> None:
    with patch("orion.mission_control_autonomy.build_mission_control_picture", return_value=_picture(TacticalThreatKind.SAM)), patch(
        "orion.mission_control_autonomy.available_jtac_assets", return_value=[_asset(laser=False, smoke=True)]
    ):
        decision = evaluate_mission_control_autonomy()
    assert decision.action is MissionControlAction.SUGGEST_JTAC
    assert decision.selected_designator_supports_laser is False
    assert decision.selected_designator_supports_smoke is True


def test_selection_prefers_explicit_laser_fac() -> None:
    scout = _asset(unit_id="scout-2", laser=True, smoke=False, explicit=False)
    fac = _asset(unit_id="jtac-1", laser=True, smoke=True, explicit=True)
    with patch("orion.mission_control_autonomy.build_mission_control_picture", return_value=_picture(TacticalThreatKind.GROUND)), patch(
        "orion.mission_control_autonomy.available_jtac_assets", return_value=[scout, fac]
    ):
        decision = evaluate_mission_control_autonomy()
    assert decision.selected_designator_id == "jtac-1"


def test_surface_threat_without_designator_does_not_offer_tasking() -> None:
    with patch("orion.mission_control_autonomy.build_mission_control_picture", return_value=_picture(TacticalThreatKind.SAM)), patch(
        "orion.mission_control_autonomy.available_jtac_assets", return_value=[]
    ):
        decision = evaluate_mission_control_autonomy()
    assert decision.action is MissionControlAction.OBSERVE
    assert decision.requires_pilot_confirmation is False
