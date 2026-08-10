from pathlib import Path

from orion import launcher


def test_runtime_root_uses_cwd_when_not_frozen(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher.sys, "frozen", False, raising=False)
    assert launcher._runtime_root() == tmp_path


def test_configure_runtime_creates_runtime_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher.sys, "frozen", False, raising=False)
    monkeypatch.delenv("ORION_RUNTIME_DIR", raising=False)
    launcher._configure_runtime()
    assert (tmp_path / "runtime").is_dir()
