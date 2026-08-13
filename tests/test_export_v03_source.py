from pathlib import Path


EXPORT = Path("dcs-export/Export.lua")


def _source() -> str:
    return EXPORT.read_text(encoding="utf-8")


def test_exporter_emits_v03_and_rich_generic_domains() -> None:
    source = _source()
    assert '"protocol_version":"0.3"' in source
    for api_name in (
        "LoGetTrueAirSpeed",
        "LoGetVerticalVelocity",
        "LoGetAltitudeAboveGroundLevel",
        "LoGetADIPitchBankYaw",
        "LoGetMechInfo",
        "LoGetEngineInfo",
        "LoGetPayloadInfo",
        "LoGetNavigationInfo",
        "LoGetTWSInfo",
        "LoGetSightingSystemInfo",
    ):
        assert f'safeCall("{api_name}")' in source or f'safeTriple("{api_name}")' in source

    for domain in (
        '"airframe":',
        '"propulsion":',
        '"fuel":',
        '"navigation":',
        '"payload":',
        '"ew":',
        '"sensors":',
        '"capabilities":',
    ):
        assert domain in source


def test_sensor_exports_are_permission_gated() -> None:
    source = _source()
    permission = source.index('safeCall("LoIsSensorExportAllowed")')
    tws = source.index('safeCall("LoGetTWSInfo")')
    sighting = source.index('safeCall("LoGetSightingSystemInfo")')
    assert permission < tws
    assert permission < sighting
    assert '"restricted"' in source


def test_fuel_is_preserved_as_raw_module_dependent_data() -> None:
    source = _source()
    assert '"internal_raw"' in source
    assert '"external_raw"' in source
    assert '"semantics":"module_dependent"' in source
