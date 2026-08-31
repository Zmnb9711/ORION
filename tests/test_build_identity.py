from __future__ import annotations

import json

import orion.build_identity as identity_module

from orion.build_identity import load_build_identity
from orion.build_identity_packaging import write_build_identity_markers


def test_frozen_marker_build_identity_is_bounded_and_exact(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    executable = tmp_path / "Core" / "ORION-Core.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"")
    (executable.parent / "build-identity.json").write_text(
        json.dumps(
            {
                "sha": "9f38d449cf94fb0d8c5534488a59e4031b73dad4",
                "branch": "dev/adr004-post-389",
                "version": "0.2.0",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("ORION_BUILD_SHA", raising=False)
    monkeypatch.setattr(identity_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(identity_module.sys, "executable", str(executable))
    monkeypatch.setattr(identity_module, "_read_source_git_identity", lambda _path: None)
    identity = load_build_identity()
    assert identity.sha == "9f38d449cf94fb0d8c5534488a59e4031b73dad4"
    assert identity.branch == "dev/adr004-post-389"
    assert identity.source == "frozen_marker"


def test_invalid_environment_identity_never_becomes_evidence(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("ORION_BUILD_SHA", "not-a-sha")
    monkeypatch.setenv("ORION_BUILD_BRANCH", "branch with spaces")
    monkeypatch.setattr(identity_module, "_marker_candidates", lambda: ())
    monkeypatch.setattr(identity_module, "_read_source_git_identity", lambda _path: None)
    identity = load_build_identity()
    assert identity.sha == identity.branch == "unknown"


def test_packaging_stamps_both_components_and_overwrites_stale_install_markers(
    tmp_path, monkeypatch
) -> None:  # noqa: ANN001
    current_sha = "255f2007abd44885d24d8dd2e45974d2873e4b14"
    stale_sha = "5eae997e76e208727141bf596eb73141be55e0b9"
    core_dir = tmp_path / "installed" / "Core"
    launcher_dir = tmp_path / "installed" / "Launcher"
    core_dir.mkdir(parents=True)
    launcher_dir.mkdir(parents=True)
    for directory in (core_dir, launcher_dir):
        (directory / "build-identity.json").write_text(
            json.dumps(
                {
                    "sha": stale_sha,
                    "branch": "dev/adr004-post-389",
                    "version": "0.2.0-alpha",
                }
            ),
            encoding="utf-8",
        )

    markers = write_build_identity_markers(
        core_dir=core_dir,
        launcher_dir=launcher_dir,
        sha=current_sha,
        branch="dev/adr004-post-389",
        version="0.2.0-alpha",
    )

    assert markers == (
        core_dir / "build-identity.json",
        launcher_dir / "build-identity.json",
    )
    for marker in markers:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        assert payload["sha"] == current_sha
        assert stale_sha not in marker.read_text(encoding="utf-8")

    executable = core_dir / "ORION-Core.exe"
    executable.write_bytes(b"")
    monkeypatch.delenv("ORION_BUILD_SHA", raising=False)
    monkeypatch.setattr(identity_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(identity_module.sys, "executable", str(executable))
    monkeypatch.setattr(identity_module, "_read_source_git_identity", lambda _path: None)
    assert load_build_identity().sha == current_sha


def test_packaging_rejects_abbreviated_sha_and_missing_frozen_directory(tmp_path) -> None:  # noqa: ANN001
    core_dir = tmp_path / "Core"
    launcher_dir = tmp_path / "Launcher"
    core_dir.mkdir()
    launcher_dir.mkdir()
    try:
        write_build_identity_markers(
            core_dir=core_dir,
            launcher_dir=launcher_dir,
            sha="255f200",
            branch="dev/adr004-post-389",
        )
    except ValueError as exc:
        assert "full 40-character SHA" in str(exc)
    else:
        raise AssertionError("Abbreviated packaging SHA must be rejected")

    missing = tmp_path / "missing"
    try:
        write_build_identity_markers(
            core_dir=core_dir,
            launcher_dir=missing,
            sha="255f2007abd44885d24d8dd2e45974d2873e4b14",
            branch="dev/adr004-post-389",
        )
    except FileNotFoundError as exc:
        assert str(missing) in str(exc)
    else:
        raise AssertionError("Missing frozen directory must fail packaging")
