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
    assert result["speechkit_stt"]["sample_rate_hz"] == 16_000
    assert result["speechkit_stt"]["external_eou"] is True
    assert result["speechkit_stt"]["network_used"] is False
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
        assert "--exclude-module orion.srs_radio_adapter" in launcher_line
        assert "--exclude-module orion.yandex_speechkit_stt" in launcher_line
        assert "--exclude-module orion.yandex_speechkit_v3_proto" in launcher_line
        assert "--srs-control-smoke" in source
        assert "--integrated-product-smoke" in source
        assert "dist-product/Launcher/ORION-Launcher.exe" in source
        assert "python -m orion.build_identity_packaging" in source
        assert "dist/ORION-Core/build-identity.json" in source
        assert "dist/ORION-Launcher/build-identity.json" in source


def test_installer_layout_copies_adjacent_identity_markers_and_upgrade_overwrites_stale() -> None:
    installer = (ROOT / "packaging/orion-alpha.iss").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/installer-smoke.yml").read_text(
        encoding="utf-8"
    )

    assert 'Source: "{#ProductSourceDir}\\Core\\*"; DestDir: "{app}\\Core"' in installer
    assert (
        'Source: "{#ProductSourceDir}\\Launcher\\*"; DestDir: "{app}\\Launcher"'
        in installer
    )
    assert "$launcherIdentity = Join-Path $launcherDir \"build-identity.json\"" in workflow
    assert "$coreIdentity = Join-Path $coreDir \"build-identity.json\"" in workflow
    assert "Repair install retained stale build identity" in workflow


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
    assert "--credential-store-smoke" in source
    assert "credential_store_ok" in source
    assert "communication_profiles_ok" in source
    assert "/v1/communication-profiles" in source
    assert '"ORION-Launcher.exe"' in source
    assert '"ORION-Core.exe"' in source


def test_installer_removes_orion_voice_credentials_without_touching_srs() -> None:
    source = (ROOT / "packaging/orion-alpha.iss").read_text(encoding="utf-8")
    assert "--clear-voice-credentials" in source
    assert "SRS-Server.exe" not in source
    assert "SR-ClientRadio.exe" not in source


def test_project_memory_requires_exact_integrated_field_artifact() -> None:
    source = (ROOT / "docs/ORION_PROJECT_MEMORY.md").read_text(encoding="utf-8")
    assert "complete normal ORION product" in source
    assert "exact delivered Launcher/Core pair" in source
    assert "Stage/Test/Smoke-named" in source
