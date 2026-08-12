from pathlib import Path

import orion.dcs_readiness as readiness


def test_saved_games_prefers_windows_known_folder(tmp_path: Path, monkeypatch) -> None:
    known = tmp_path / "Redirected Saved Games"
    (known / "DCS").mkdir(parents=True)
    monkeypatch.setattr(readiness, "_windows_saved_games_root", lambda: known)
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "Wrong Profile"))

    found = readiness.discover_saved_games()
    assert found[0].path == str(known / "DCS")
    assert found[0].exists is True


def test_saved_games_falls_back_to_userprofile(tmp_path: Path, monkeypatch) -> None:
    profile = tmp_path / "Profile"
    (profile / "Saved Games" / "DCS.openbeta").mkdir(parents=True)
    monkeypatch.setattr(readiness, "_windows_saved_games_root", lambda: None)
    monkeypatch.setenv("USERPROFILE", str(profile))

    found = readiness.discover_saved_games()
    assert found[0].path == str(profile / "Saved Games" / "DCS")
    assert found[1].path == str(profile / "Saved Games" / "DCS.openbeta")
    assert found[1].exists is True
