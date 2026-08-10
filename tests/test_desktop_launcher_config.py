from pathlib import Path

from orion.desktop_launcher import LauncherConfig, LauncherConfigStore


def test_launcher_config_persists_update_channel(tmp_path: Path) -> None:
    store = LauncherConfigStore(tmp_path)
    config = LauncherConfig(update_channel="beta", ai_provider="gigachat")
    store.save(config)

    loaded = store.load()
    assert loaded.update_channel == "beta"
    assert loaded.ai_provider == "gigachat"


def test_launcher_config_loads_legacy_file_without_update_channel(tmp_path: Path) -> None:
    store = LauncherConfigStore(tmp_path)
    store.path.write_text('{"language":"ru","ai_provider":"auto"}', encoding="utf-8")

    loaded = store.load()
    assert loaded.language == "ru"
    assert loaded.update_channel == "alpha"
