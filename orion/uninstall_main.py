from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from orion.component_uninstall import UninstallComponent, UninstallRequest, installation_root, whisper_root
from orion.dcs_readiness import remove_export_integration


def _parse_components(raw: str) -> set[UninstallComponent]:
    result: set[UninstallComponent] = set()
    for value in raw.split(","):
        value = value.strip()
        if value:
            result.add(UninstallComponent(value))
    return result


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return str(pid) in completed.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _wait_for_parent(pid: int | None, timeout_seconds: float = 15.0) -> None:
    if not pid:
        return
    deadline = time.monotonic() + timeout_seconds
    while _pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    if _pid_alive(pid):
        raise RuntimeError(f"ORION Launcher did not exit within {timeout_seconds:.0f} seconds")


def _stop_core_processes() -> None:
    if os.name != "nt":
        return
    subprocess.run(
        ["taskkill", "/F", "/IM", "ORION-Core.exe"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _remove_launcher_shortcuts() -> None:
    if os.name != "nt":
        return
    appdata = os.environ.get("APPDATA")
    userprofile = os.environ.get("USERPROFILE")
    candidates: list[Path] = []
    if appdata:
        candidates.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "ORION.lnk")
    if userprofile:
        candidates.append(Path(userprofile) / "Desktop" / "ORION.lnk")
    public = os.environ.get("PUBLIC")
    if public:
        candidates.append(Path(public) / "Desktop" / "ORION.lnk")
    for shortcut in candidates:
        try:
            shortcut.unlink()
        except FileNotFoundError:
            pass


def _inno_uninstaller(root: Path) -> Path | None:
    matches = sorted(root.glob("unins*.exe"))
    return matches[0] if matches else None


def execute_uninstall(request: UninstallRequest) -> None:
    root = installation_root()
    source_development = not getattr(sys, "frozen", False) and not os.environ.get("ORION_INSTALL_ROOT")

    if request.removes_dcs_integration and request.dcs_saved_games_path:
        remove_export_integration(request.dcs_saved_games_path)

    if request.removes_whisper:
        _remove_tree(whisper_root())

    if request.removes_core:
        _stop_core_processes()
        if source_development:
            raise RuntimeError("Refusing to remove Core source files outside an installed ORION product")
        _remove_tree(root / "Core")

    if request.remove_everything:
        if source_development:
            raise RuntimeError("Full uninstall is available only for an installed ORION product")
        _stop_core_processes()
        _wait_for_parent(request.parent_pid)
        uninstaller = _inno_uninstaller(root)
        if uninstaller is None:
            raise FileNotFoundError(f"ORION product uninstaller was not found under {root}")
        subprocess.Popen([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], cwd=str(root))
        return

    if request.removes_launcher:
        if source_development:
            raise RuntimeError("Refusing to remove Launcher source files outside an installed ORION product")
        _wait_for_parent(request.parent_pid)
        _remove_tree(root / "Launcher")
        _remove_launcher_shortcuts()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ORION component uninstaller")
    parser.add_argument("--components", required=True)
    parser.add_argument("--remove-everything", action="store_true")
    parser.add_argument("--dcs-saved-games")
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args(argv)

    request = UninstallRequest(
        components=_parse_components(args.components),
        remove_everything=bool(args.remove_everything),
        dcs_saved_games_path=args.dcs_saved_games,
        parent_pid=args.parent_pid,
    )
    execute_uninstall(request)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
