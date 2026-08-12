from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from orion.app import app
from orion.dcs_steam_detection import discover_steam_dcs


def _make_dcs_install(root: Path) -> tuple[Path, Path]:
    steam = root / "Steam"
    secondary = root / "Games" / "SteamLibrary"
    (steam / "steamapps").mkdir(parents=True)
    (secondary / "steamapps" / "common" / "DCSWorld" / "bin").mkdir(parents=True)
    (secondary / "steamapps" / "common" / "DCSWorld" / "bin" / "DCS.exe").write_bytes(b"")
    (secondary / "steamapps" / "appmanifest_223750.acf").write_text(
        '"AppState"\n{\n  "appid" "223750"\n  "installdir" "DCSWorld"\n}\n',
        encoding="utf-8",
    )
    escaped = str(secondary).replace("\\", "\\\\")
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n "1" {{ "path" "{escaped}" }}\n}}\n',
        encoding="utf-8",
    )
    return steam, secondary


def test_discovers_dcs_in_secondary_steam_library(tmp_path: Path) -> None:
    steam, secondary = _make_dcs_install(tmp_path)
    found = discover_steam_dcs([steam])
    assert len(found) == 1
    assert found[0].installation_type.value == "steam"
    assert Path(found[0].steam_library) == secondary
    assert Path(found[0].executable_path).name == "DCS.exe"
    assert found[0].executable_exists is True
    assert found[0].manifest_path and found[0].manifest_path.endswith("appmanifest_223750.acf")


def test_default_detection_probes_conventional_secondary_library(tmp_path: Path, monkeypatch) -> None:
    import orion.dcs_steam_detection as detection

    drive = tmp_path / "D"
    library = drive / "SteamLibrary"
    install = library / "steamapps" / "common" / "DCSWorld"
    (install / "bin-mt").mkdir(parents=True)
    (install / "bin-mt" / "DCS.exe").write_bytes(b"")
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
    monkeypatch.delenv("PROGRAMFILES", raising=False)
    monkeypatch.setattr(detection, "_registry_steam_roots", lambda: [])
    monkeypatch.setattr(detection, "_windows_drive_roots", lambda: [drive])

    found = discover_steam_dcs()
    assert len(found) == 1
    assert Path(found[0].steam_library) == library
    assert Path(found[0].executable_path) == install / "bin-mt" / "DCS.exe"


def test_windows_drive_roots_use_logical_drive_bitmask(monkeypatch) -> None:
    import ctypes
    import orion.dcs_steam_detection as detection

    class Kernel32:
        @staticmethod
        def GetLogicalDrives() -> int:
            # C: and D:
            return (1 << 2) | (1 << 3)

    class Windll:
        kernel32 = Kernel32()

    monkeypatch.setattr(detection, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(ctypes, "windll", Windll(), raising=False)

    roots = detection._windows_drive_roots()

    assert [str(item) for item in roots] == ["C:\\", "D:\\"]


def test_detection_deduplicates_manifest_and_default_dcsworld_path(tmp_path: Path) -> None:
    steam = tmp_path / "Steam"
    install = steam / "steamapps" / "common" / "DCSWorld"
    (install / "bin").mkdir(parents=True)
    (install / "bin" / "DCS.exe").write_bytes(b"")
    (steam / "steamapps" / "appmanifest_223750.acf").write_text(
        '"AppState" { "installdir" "DCSWorld" }', encoding="utf-8"
    )
    found = discover_steam_dcs([steam])
    assert len(found) == 1


def test_steam_detection_api_is_registered(monkeypatch) -> None:
    import orion.dcs_steam_detection_api as api

    monkeypatch.setattr(api, "discover_steam_dcs", lambda: [])
    with TestClient(app) as client:
        response = client.get("/v1/dcs-detection/steam")
    assert response.status_code == 200
    assert response.json() == []
