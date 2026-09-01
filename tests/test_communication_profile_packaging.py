from __future__ import annotations

from pathlib import Path

import pytest

from orion.communication_contracts import CommunicationProfileId
from orion.communication_profile_packs import PackError, default_bootstrap_root, load_source_registry


ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_assets_exist_for_core_and_contain_no_normative_entries() -> None:
    root = default_bootstrap_root()
    assert root.is_dir()
    registry = load_source_registry(root / "source-registry.json")
    assert {item.profile_id for item in registry.profiles} == set(CommunicationProfileId)
    for profile_id in CommunicationProfileId:
        pack_root = root / "packs" / profile_id.value
        assert (pack_root / "manifest.json").is_file()
        assert (pack_root / "entries.json").read_text(encoding="utf-8").strip() == '{"entries": []}'


def test_build_pipeline_and_python_package_include_bootstrap_assets() -> None:
    workflow = (ROOT / ".github" / "workflows" / "alpha-build.yml").read_text(encoding="utf-8")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '--add-data "orion/communication_profile_assets;orion/communication_profile_assets"' in workflow
    assert 'communication_profile_assets/**/*.json' in project


def test_installer_creates_separate_preserved_mutable_profile_location() -> None:
    source = (ROOT / "packaging" / "orion-alpha.iss").read_text(encoding="utf-8")
    assert 'Name: "{localappdata}\\ORION\\communication-profiles"' in source
    assert 'Name: "{localappdata}\\ORION\\runtime"' in source
    uninstall_lines = [line for line in source.splitlines() if line.startswith("Type: filesandordirs")]
    assert all("communication-profiles" not in line for line in uninstall_lines)


def test_source_registry_is_closed_and_requires_all_four_profiles(tmp_path) -> None:  # noqa: ANN001
    original = (default_bootstrap_root() / "source-registry.json").read_text(encoding="utf-8")
    import json

    payload = json.loads(original)
    payload["unknown"] = True
    bad = tmp_path / "unknown.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PackError, match="invalid"):
        load_source_registry(bad)

    payload = json.loads(original)
    payload["profiles"] = payload["profiles"][:-1]
    missing = tmp_path / "missing.json"
    missing.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PackError, match="invalid"):
        load_source_registry(missing)
