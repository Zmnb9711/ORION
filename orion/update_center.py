from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orion import __version__

GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/Zmnb9711/ORION/releases/latest"
INSTALLER_ASSET_SUFFIX = "Setup.exe"


@dataclass(frozen=True, slots=True)
class FeatureStatus:
    name: str
    state: str
    description: str


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    version: str
    title: str
    notes: str
    published_at: str | None
    installer_url: str | None
    installer_name: str | None
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class UpdateCheckResult:
    current_version: str
    latest: ReleaseInfo | None
    update_available: bool
    status: str
    message: str


def current_feature_status() -> tuple[FeatureStatus, ...]:
    return (
        FeatureStatus("DCS connectivity / telemetry", "available", "DCS Export.lua bridge, telemetry handshake and readiness checks."),
        FeatureStatus("F/A-18C integration", "available", "F/A-18C focused aircraft integration for the first Alpha test path."),
        FeatureStatus("Voice runtime", "available", "Voice scheduling, Windows audio output and radio/intercom policy."),
        FeatureStatus("Virtual ATC", "available", "Ground, Tower, Departure and current Arrival/Approach runtime work."),
        FeatureStatus("Mission Control / AWACS", "available", "Threat picture, tactical queries and proactive mission-control guidance."),
        FeatureStatus("JTAC / laser / smoke", "available", "JTAC assignment, laser/smoke designation and laser code handling."),
        FeatureStatus("AAR / tanker", "available", "Tanker discovery, rendezvous and AAR workflow support."),
        FeatureStatus("Diagnostics", "available", "One-shot Windows/DCS diagnostic ZIP bundle."),
        FeatureStatus("Mission Studio", "planned", "Launcher entry approved; .miz compiler/editor backend tracked separately."),
        FeatureStatus("Multi-provider AI", "planned", "OpenAI, Yandex Cloud, GigaChat and Local adapters are approved but not all implemented yet."),
    )


def _normalize_version(value: str) -> tuple[int, ...]:
    cleaned = value.strip().lower().removeprefix("v").split("-")[0]
    parts: list[int] = []
    for chunk in cleaned.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


def _extract_sha256(notes: str, asset_name: str | None) -> str | None:
    if not asset_name:
        return None
    lower_name = asset_name.lower()
    for raw_line in notes.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if "sha256" not in lower or lower_name not in lower:
            continue
        for token in line.replace("`", " ").replace(":", " ").split():
            if len(token) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in token):
                return token.lower()
    return None


def _release_from_payload(payload: dict[str, Any]) -> ReleaseInfo:
    assets = payload.get("assets") or []
    installer = next(
        (
            asset
            for asset in assets
            if str(asset.get("name", "")).lower().endswith(INSTALLER_ASSET_SUFFIX.lower())
        ),
        None,
    )
    notes = str(payload.get("body") or "")
    installer_name = str(installer.get("name")) if installer else None
    return ReleaseInfo(
        version=str(payload.get("tag_name") or payload.get("name") or "0.0.0").removeprefix("v"),
        title=str(payload.get("name") or payload.get("tag_name") or "ORION update"),
        notes=notes,
        published_at=payload.get("published_at"),
        installer_url=(str(installer.get("browser_download_url")) if installer else None),
        installer_name=installer_name,
        sha256=_extract_sha256(notes, installer_name),
    )


def check_for_updates(timeout: float = 5.0) -> UpdateCheckResult:
    request = urllib.request.Request(
        GITHUB_LATEST_RELEASE_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"ORION/{__version__}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return UpdateCheckResult(__version__, None, False, "no_release", "No public ORION release has been published yet.")
        return UpdateCheckResult(__version__, None, False, "error", f"Update check failed: HTTP {exc.code}")
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return UpdateCheckResult(__version__, None, False, "error", f"Update check failed: {exc}")

    latest = _release_from_payload(payload)
    available = _normalize_version(latest.version) > _normalize_version(__version__)
    return UpdateCheckResult(
        current_version=__version__,
        latest=latest,
        update_available=available,
        status="update_available" if available else "current",
        message=(f"ORION {latest.version} is available." if available else f"ORION {__version__} is up to date."),
    )


def download_update(release: ReleaseInfo, destination_dir: Path | None = None, timeout: float = 60.0) -> Path:
    if not release.installer_url or not release.installer_name:
        raise ValueError("Release does not contain an ORION installer asset")
    target_dir = destination_dir or Path(tempfile.gettempdir()) / "ORION" / "updates"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / release.installer_name
    request = urllib.request.Request(release.installer_url, headers={"User-Agent": f"ORION/{__version__}"})
    with urllib.request.urlopen(request, timeout=timeout) as response, target.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    if release.sha256:
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest.lower() != release.sha256.lower():
            target.unlink(missing_ok=True)
            raise ValueError("Downloaded installer SHA-256 does not match the release manifest")
    return target


def launch_installer(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    if os.name == "nt":
        subprocess.Popen([str(path)], close_fds=True)
    else:
        raise OSError("ORION installer updates are only supported on Windows")
