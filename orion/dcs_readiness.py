from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, Field


ORION_EXPORT_MARKER = "-- ORION DCS integration"
ORION_EXPORT_LINE = 'dofile(lfs.writedir() .. "Scripts/ORION/Export.lua")'
FOLDERID_SAVED_GAMES = UUID("4c5c32ff-bb9d-43b0-b5b4-2d72e54eaaa4")


class ReadinessState(StrEnum):
    READY = "ready"
    ACTION_REQUIRED = "action_required"


class DcsSavedGamesCandidate(BaseModel):
    path: str
    variant: str
    exists: bool


class DcsReadinessReport(BaseModel):
    state: ReadinessState
    saved_games: list[DcsSavedGamesCandidate] = Field(default_factory=list)
    selected_saved_games: str | None = None
    export_lua_path: str | None = None
    export_configured: bool = False
    actions: list[str] = Field(default_factory=list)


def discover_saved_games(home: Path | None = None) -> list[DcsSavedGamesCandidate]:
    root = home or _saved_games_root()
    variants = (("DCS", "stable"), ("DCS.openbeta", "openbeta"))
    return [
        DcsSavedGamesCandidate(path=str(root / folder), variant=variant, exists=(root / folder).is_dir())
        for folder, variant in variants
    ]


def inspect_dcs_readiness(saved_games_path: str | None = None) -> DcsReadinessReport:
    candidates = discover_saved_games()
    selected = Path(saved_games_path) if saved_games_path else _first_existing(candidates)
    actions: list[str] = []
    export_path: Path | None = None
    configured = False

    if selected is None:
        actions.append("Select the DCS Saved Games directory")
    else:
        export_path = selected / "Scripts" / "Export.lua"
        configured = _export_contains_orion(export_path)
        if not configured:
            actions.append("Install ORION Export.lua integration")

    return DcsReadinessReport(
        state=ReadinessState.READY if not actions else ReadinessState.ACTION_REQUIRED,
        saved_games=candidates,
        selected_saved_games=str(selected) if selected else None,
        export_lua_path=str(export_path) if export_path else None,
        export_configured=configured,
        actions=actions,
    )


def install_export_integration(saved_games_path: str) -> DcsReadinessReport:
    root = Path(saved_games_path)
    scripts = root / "Scripts"
    orion_dir = scripts / "ORION"
    scripts.mkdir(parents=True, exist_ok=True)
    orion_dir.mkdir(parents=True, exist_ok=True)

    export_path = scripts / "Export.lua"
    current = export_path.read_text(encoding="utf-8") if export_path.is_file() else ""
    if ORION_EXPORT_LINE not in current:
        separator = "" if not current or current.endswith("\n") else "\n"
        export_path.write_text(
            current + separator + f"{ORION_EXPORT_MARKER}\n{ORION_EXPORT_LINE}\n",
            encoding="utf-8",
        )

    source = _packaged_export_source()
    if not source.is_file():
        raise FileNotFoundError(f"ORION DCS exporter payload is missing: {source}")
    integration = orion_dir / "Export.lua"
    integration.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return inspect_dcs_readiness(str(root))


def remove_export_integration(saved_games_path: str) -> DcsReadinessReport:
    """Remove only ORION-owned DCS integration content.

    ``Scripts/Export.lua`` is a shared user file and may contain Tacview, SRS,
    DCS-BIOS or other exporters.  Never delete it wholesale: remove the exact
    ORION marker/call pair while preserving every unrelated line.  The payload
    under ``Scripts/ORION`` is ORION-owned and may be removed directly.
    """
    root = Path(saved_games_path)
    scripts = root / "Scripts"
    export_path = scripts / "Export.lua"
    if export_path.is_file():
        lines = export_path.read_text(encoding="utf-8").splitlines()
        filtered = [line for line in lines if line.strip() not in {ORION_EXPORT_MARKER, ORION_EXPORT_LINE}]
        if filtered:
            export_path.write_text("\n".join(filtered).rstrip() + "\n", encoding="utf-8")
        else:
            export_path.unlink()

    orion_dir = scripts / "ORION"
    integration = orion_dir / "Export.lua"
    try:
        integration.unlink()
    except FileNotFoundError:
        pass
    try:
        orion_dir.rmdir()
    except (FileNotFoundError, OSError):
        # Preserve the directory if it contains user/diagnostic files that are
        # not owned by the standard ORION exporter payload.
        pass

    return inspect_dcs_readiness(str(root))


def _packaged_export_source() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / "dcs-export" / "Export.lua"
    return Path(__file__).resolve().parent.parent / "dcs-export" / "Export.lua"


def _saved_games_root() -> Path:
    known = _windows_saved_games_root()
    if known is not None:
        return known
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        return Path(userprofile) / "Saved Games"
    return Path.home() / "Saved Games"


def _windows_saved_games_root() -> Path | None:
    if os.name != "nt":
        return None

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    raw = FOLDERID_SAVED_GAMES.bytes_le
    guid = GUID.from_buffer_copy(raw)
    result = ctypes.c_wchar_p()
    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32
    shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    hr = shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(result))
    if hr != 0 or not result.value:
        return None
    try:
        return Path(result.value)
    finally:
        ole32.CoTaskMemFree(result)


def _first_existing(candidates: list[DcsSavedGamesCandidate]) -> Path | None:
    for candidate in candidates:
        if candidate.exists:
            return Path(candidate.path)
    return None


def _export_contains_orion(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        return ORION_EXPORT_LINE in path.read_text(encoding="utf-8")
    except OSError:
        return False
