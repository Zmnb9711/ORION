from __future__ import annotations

import json
from pathlib import Path

from orion import branding
from orion.desktop_app import LauncherConfig, LauncherConfigStore
from orion.launcher_i18n import normalize_language, translate
from orion.windows_autostart import launcher_command, set_autostart


def test_launcher_config_round_trip_preserves_update_channel_and_language(tmp_path: Path) -> None:
    store = LauncherConfigStore(tmp_path)
    expected = LauncherConfig(language="ru", update_channel="beta", ai_provider="gigachat")
    store.save(expected)
    loaded = store.load()
    assert loaded.language == "ru"
    assert loaded.update_channel == "beta"
    assert loaded.ai_provider == "gigachat"


def test_launcher_config_reads_legacy_json_without_new_fields(tmp_path: Path) -> None:
    (tmp_path / "launcher.json").write_text(json.dumps({"language": "ru-RU", "ai_provider": "auto"}), encoding="utf-8")
    loaded = LauncherConfigStore(tmp_path).load()
    assert loaded.language == "ru"
    assert loaded.update_channel == "alpha"


def test_localization_has_russian_and_english_navigation() -> None:
    assert normalize_language("ru-RU") == "ru"
    assert normalize_language("en-US") == "en"
    assert translate("nav.settings", "ru") == "Настройки"
    assert translate("nav.settings", "en") == "Settings"
    assert translate("missing.key", "ru") == "missing.key"


def test_autostart_command_quotes_executable() -> None:
    command = launcher_command(Path("C:/Program Files/ORION/ORION.exe"))
    assert command.endswith('ORION.exe" --desktop')
    assert command.startswith('"')


def test_set_autostart_is_safe_noop_off_windows() -> None:
    import os

    if os.name != "nt":
        assert set_autostart(True) is False


def test_packaged_icon_path_prefers_frozen_bundle(monkeypatch, tmp_path: Path) -> None:
    icon = tmp_path / "branding" / "orion.ico"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"approved-icon")
    monkeypatch.setattr(branding.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert branding.packaged_icon_path() == icon
