from orion.jtac_assets import available_jtac_assets, select_jtac_asset
from orion.mission import Coalition, MissionPosition, MissionSnapshot, MissionUnit, UnitCategory
from orion.mission_store import mission_store


def _unit(unit_id: str, name: str, category: UnitCategory, type_name: str, coalition: Coalition = Coalition.BLUE, alive: bool = True):
    return MissionUnit(unit_id=unit_id, name=name, category=category, type_name=type_name, coalition=coalition, alive=alive, position=MissionPosition(latitude=0, longitude=0))


def test_selects_explicit_ground_jtac_before_air_asset():
    mission_store.replace(MissionSnapshot(mission_id="m", units=[
        _unit("air", "Kiowa 1-1", UnitCategory.HELICOPTER, "OH-58D"),
        _unit("ground", "JTAC Alpha", UnitCategory.GROUND, "HMMWV"),
    ]))
    selected = select_jtac_asset()
    assert selected is not None
    assert selected.unit_id == "ground"
    assert selected.explicit_fac_role is True


def test_generic_ground_vehicle_is_not_promoted_to_jtac():
    mission_store.replace(MissionSnapshot(mission_id="m", units=[
        _unit("hmmwv", "Blue Utility", UnitCategory.GROUND, "HMMWV"),
        _unit("m113", "Blue APC", UnitCategory.GROUND, "M113"),
    ]))
    assert available_jtac_assets() == []


def test_capable_airborne_designator_remains_available_fallback():
    mission_store.replace(MissionSnapshot(mission_id="m", units=[
        _unit("apache", "Springfield 1-1", UnitCategory.HELICOPTER, "AH-64D_BLK_II"),
    ]))
    selected = select_jtac_asset()
    assert selected is not None
    assert selected.unit_id == "apache"
    assert selected.supports_laser is True
    assert selected.supports_smoke is False


def test_excludes_enemy_dead_and_unrelated_units():
    mission_store.replace(MissionSnapshot(mission_id="m", units=[
        _unit("enemy", "JTAC Red", UnitCategory.GROUND, "HMMWV", Coalition.RED),
        _unit("dead", "JTAC Dead", UnitCategory.GROUND, "HMMWV", alive=False),
        _unit("tank", "Blue Armor", UnitCategory.GROUND, "T-72"),
    ]))
    assert available_jtac_assets() == []


def test_requested_asset_must_be_available_designator():
    mission_store.replace(MissionSnapshot(mission_id="m", units=[
        _unit("jtac", "JTAC Alpha", UnitCategory.GROUND, "HMMWV"),
    ]))
    assert select_jtac_asset(requested_asset_id="missing") is None
    assert select_jtac_asset(requested_asset_id="jtac").unit_id == "jtac"
