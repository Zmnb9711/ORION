from orion.mission_control_runtime import MissionControlPicture, MissionControlReadiness


def test_default_picture_is_unavailable():
    picture = MissionControlPicture()
    assert picture.readiness is MissionControlReadiness.UNAVAILABLE
    assert picture.primary_air_threat is None
    assert picture.primary_surface_threat is None
    assert picture.secondary_air_threats == []
