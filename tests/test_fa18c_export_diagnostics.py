from pathlib import Path


EXPORT = Path("dcs-export/Export.lua").read_text(encoding="utf-8")


def test_diagnostics_disabled_by_default() -> None:
    assert "enabled = false" in EXPORT


def test_diagnostics_has_explicit_start_stop_commands() -> None:
    assert 'command == "start_cockpit_diagnostics"' in EXPORT
    assert 'command == "stop_cockpit_diagnostics"' in EXPORT


def test_diagnostics_scans_changes_not_every_frame() -> None:
    assert "sample_every_frames = 10" in EXPORT
    assert "math.abs(value - previous) >= diagnostics.epsilon" in EXPORT
    assert '"changes"' in EXPORT


def test_diagnostics_range_is_bounded() -> None:
    assert "math.max(0" in EXPORT
    assert "math.min(2000" in EXPORT


def test_diagnostics_only_targets_hornet() -> None:
    assert 'selfData.Name ~= "FA-18C_hornet"' in EXPORT


def test_regular_telemetry_still_carries_cockpit_state() -> None:
    assert '"cockpit_state":%s' in EXPORT
    assert '"diagnostics":%s' in EXPORT
    assert '"protocol_version":"0.3"' in EXPORT
