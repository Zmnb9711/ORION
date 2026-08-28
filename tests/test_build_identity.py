from __future__ import annotations

import json

import orion.build_identity as identity_module

from orion.build_identity import load_build_identity


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
