from pathlib import Path
from types import ModuleType

from orion import launcher


def test_runtime_root_uses_cwd_when_not_frozen(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher.sys, "frozen", False, raising=False)
    assert launcher._runtime_root() == tmp_path


def test_configure_runtime_creates_runtime_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher.sys, "frozen", False, raising=False)
    monkeypatch.delenv("ORION_RUNTIME_DIR", raising=False)
    runtime = launcher._configure_runtime()
    assert runtime == tmp_path / "runtime"
    assert runtime.is_dir()


def test_desktop_mode_dispatches_to_native_launcher(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher.sys, "frozen", False, raising=False)
    monkeypatch.delenv("ORION_RUNTIME_DIR", raising=False)
    calls: list[tuple[Path, str, int]] = []
    module = ModuleType("orion.desktop_launcher")

    def fake_run(runtime_dir: Path, host: str, port: int) -> int:
        calls.append((runtime_dir, host, port))
        return 17

    module.run_desktop_launcher = fake_run  # type: ignore[attr-defined]
    monkeypatch.setitem(launcher.sys.modules, "orion.desktop_launcher", module)

    assert launcher.main(["--desktop", "--host", "127.0.0.1", "--port", "8124"]) == 17
    assert calls == [(tmp_path / "runtime", "127.0.0.1", 8124)]
