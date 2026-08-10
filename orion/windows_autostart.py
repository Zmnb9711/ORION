from __future__ import annotations

import os
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "ORION"


def launcher_command(executable: str | Path | None = None) -> str:
    target = Path(executable or sys.executable).resolve()
    return f'"{target}" --desktop'


def set_autostart(enabled: bool, executable: str | Path | None = None) -> bool:
    """Enable or disable per-user ORION autostart.

    Returns False on non-Windows hosts so tests and development environments
    remain portable. No administrator rights are required because HKCU is used.
    """
    if os.name != "nt":
        return False
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launcher_command(executable))
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
    return True


def autostart_enabled() -> bool:
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    return str(value).strip() == launcher_command().strip()
