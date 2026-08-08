from unittest.mock import patch

from orion.jtac_assets import JtacAsset, JtacAssetAvailability
from orion.mission import UnitCategory
from orion.mission_control_autonomy import MissionControlAction, evaluate_mission_control_autonomy
from orion.mission_control_runtime import MissionControlPicture, MissionControlReadiness
from orion.tactical_situation import TacticalThreat, TacticalThreatKind


def _threat(kind: TacticalThreatKind) -> TacticalThreat:
    return TacticalThreat(
        unit_id="threat-1",
        name="SA-11" if kind is TacticalThreatKind.SAM else "armor",
        kind=kind,
        bearing_deg=270,
        range_nm=12,
        braa="270/12",
        score=90,
    )


def _asset() -> JtacAsset:
    return JtacAsset(
        unit_id="jtac-1",
        name="Axeman 1-1",
        category=UnitCategory.GROUND,
        supports_laser=True,
        supports_smoke=True,
        explicit_fac_role=True,
        availability=JtacAssetAvailability.AVAILABLE,
    )


def test_unavailable_picture_stays_observe() -> None:
    with patch("orion.mission_control_autonomy.build_mission_control_picture", return_value=MissionControlPicture()):
        decision = evaluate_mission_control_autonomy()
    assert decision.action is MissionControlAction.OBSERVE
    assert decision.requires_pilot_confirmation is False


def test_sam_with_designator_suggests_9line() -> None:
    picture = MissionControlPicture(
        readiness=MissionControlReadiness.ENGAGED,
        primary_surface_threat=_threat(TacticalThreatKind.SAM),
        total_threats=1,
    )
    with patch("orion.mission_control_autonomy.build_mission_control_picture", return_value=picture), patch(
        "orion.mission_control_autonomy.available_jtac_assets", return_value=[_asset()]
    ):
        decision = evaluate_mission_control_autonomy()
    assert decision.action is MissionControlAction.SUGGEST_9LINE
    assert decision.target_id == "threat-1"
    assert decision.requires_pilot_confirmation is True
    assert decision.available_designators == 1


def test_non_sam_surface_threat_suggests_jtac() -> None:
    picture = MissionControlPicture(
        readiness=MissionControlReadiness.ENGAGED,
        primary_surface_threat=_threat(TacticalThreatKind.GROUND),
        total_threats=1,
    )
    with patch("orion.mission_control_autonomy.build_mission_control_picture", return_value=picture), patch(
        "orion.mission_control_autonomy.available_jtac_assets", return_value=[_asset()]
    ):
        decision = evaluate_mission_control_autonomy()
    assert decision.action is MissionControlAction.SUGGEST_JTAC


def test_surface_threat_without_designator_does_not_offer_tasking() -> None:
    picture = MissionControlPicture(
        readiness=MissionControlReadiness.ENGAGED,
        primary_surface_threat=_threat(TacticalThreatKind.SAM),
        total_threats=1,
    )
    with patch("orion.mission_control_autonomy.build_mission_control_picture", return_value=picture), patch(
        "orion.mission_control_autonomy.available_jtac_assets", return_value=[]
    ):
        decision = evaluate_mission_control_autonomy()
    assert decision.action is MissionControlAction.OBSERVE
    assert decision.requires_pilot_confirmation is False
