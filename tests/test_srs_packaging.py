from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from orion.srs_frozen_smoke import run_smoke

ROOT = Path(__file__).resolve().parents[1]


import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Core native smoke is Windows-only")
def test_source_offline_native_smoke_and_asset_provenance() -> None:
    result = run_smoke()
    assert result["ok"] is True
    assert result["opus_version"] == "libopus 1.6.1"
    assert result["decoded_bytes"] == 1280
    assert result["network_used"] is False
    assert result["audio_devices_opened"] is False
    dll = ROOT / "orion/native/win_amd64/opus.dll"
    assert hashlib.sha256(dll.read_bytes()).hexdigest() == (
        "82b454192834e0afce0d5ce3c46f2deba653ac437f369d847ab8043a93157808"
    )
    for name in (
        "opus-BSD-3-Clause.txt",
        "python-samplerate-MIT.txt",
        "libsamplerate-BSD-2-Clause.txt",
        "SRS-reference-provenance.md",
    ):
        assert (ROOT / "orion/native/licenses" / name).is_file()


def test_build_workflows_assign_srs_native_runtime_to_core_not_launcher() -> None:
    for relative in (
        ".github/workflows/alpha-build.yml",
        ".github/workflows/installer-smoke.yml",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "orion/native/win_amd64/opus.dll;native/win_amd64" in source
        assert "--srs-native-smoke" in source
        launcher_line = next(
            line for line in source.splitlines() if "--name ORION-Launcher" in line
        )
        assert "--exclude-module samplerate" in launcher_line
        assert "--exclude-module numpy" in launcher_line
        assert "--srs-control-smoke" in source
        assert "--integrated-product-smoke" in source
        assert "dist-product/Launcher/ORION-Launcher.exe" in source


def test_orion_distribution_never_contains_external_srs_applications() -> None:
    for root in (ROOT / "orion", ROOT / "packaging"):
        packaged = {
            path.name.casefold()
            for path in root.rglob("*.exe")
        }
        assert "srs-server.exe" not in packaged
        assert "sr-clientradio.exe" not in packaged


def test_launcher_entrypoint_has_offline_srs_control_smoke() -> None:
    source = (ROOT / "orion/launcher_main.py").read_text(encoding="utf-8")
    assert "--srs-control-smoke" in source
    assert "launcher_srs_offline_smoke" in source
    assert "--integrated-product-smoke" in source
    assert '"ORION-Launcher.exe"' in source
    assert '"ORION-Core.exe"' in source


def test_project_memory_requires_exact_integrated_field_artifact() -> None:
    source = (ROOT / "docs/ORION_PROJECT_MEMORY.md").read_text(encoding="utf-8")
    assert "complete normal ORION product" in source
    assert "exact delivered Launcher/Core pair" in source
    assert "Stage/Test/Smoke-named" in source
