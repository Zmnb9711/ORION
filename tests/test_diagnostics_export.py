from __future__ import annotations

from pathlib import Path

import pytest

from orion import diagnostics_export


def test_copy_diagnostics_bundle_preserves_original_and_adds_zip_suffix(tmp_path: Path) -> None:
    source = tmp_path / "source.zip"
    source.write_bytes(b"orion diagnostics")

    saved = diagnostics_export.copy_diagnostics_bundle(source, tmp_path / "shared" / "flight-test")

    assert saved == (tmp_path / "shared" / "flight-test.zip").resolve()
    assert saved.read_bytes() == source.read_bytes()
    assert source.is_file()


def test_copy_diagnostics_bundle_requires_existing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        diagnostics_export.copy_diagnostics_bundle(tmp_path / "missing.zip", tmp_path / "copy.zip")


def test_reveal_in_file_manager_selects_bundle_on_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = tmp_path / "diagnostics.zip"
    bundle.write_bytes(b"zip")
    calls: list[list[str]] = []

    monkeypatch.setattr(diagnostics_export.os, "name", "nt")
    monkeypatch.setattr(diagnostics_export.subprocess, "Popen", lambda args: calls.append(args))

    diagnostics_export.reveal_in_file_manager(bundle)

    assert calls == [["explorer.exe", "/select,", str(bundle.resolve())]]
