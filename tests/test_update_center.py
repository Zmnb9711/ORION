from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from orion import update_center
from orion.update_center import ReleaseInfo, UpdateChannel


class _Response:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_normalize_version_orders_semver_like_values() -> None:
    assert update_center._normalize_version("v0.2.0") > update_center._normalize_version("0.1.9")
    assert update_center._normalize_version("0.1.0-alpha") == (0, 1, 0)


def test_release_parser_finds_installer_checksum_and_size() -> None:
    checksum = "a" * 64
    payload = {
        "tag_name": "v0.2.0",
        "name": "ORION Alpha 0.2",
        "body": f"Changes\nSHA256 ORION-Alpha-0.2-Setup.exe {checksum}",
        "published_at": "2026-08-10T12:00:00Z",
        "prerelease": True,
        "assets": [
            {
                "name": "ORION-Alpha-0.2-Setup.exe",
                "browser_download_url": "https://example.invalid/setup.exe",
                "size": 12345,
            }
        ],
    }
    release = update_center._release_from_payload(payload)
    assert release.version == "0.2.0"
    assert release.installer_name == "ORION-Alpha-0.2-Setup.exe"
    assert release.sha256 == checksum
    assert release.prerelease is True
    assert release.size_bytes == 12345


def test_release_channels_filter_prereleases() -> None:
    payload = [
        {"tag_name": "v0.3.0-alpha", "prerelease": True, "draft": False, "assets": []},
        {"tag_name": "v0.2.0-beta", "prerelease": True, "draft": False, "assets": []},
        {"tag_name": "v0.1.5", "prerelease": False, "draft": False, "assets": []},
    ]
    stable = update_center._select_release(payload, UpdateChannel.STABLE)
    beta = update_center._select_release(payload, UpdateChannel.BETA)
    alpha = update_center._select_release(payload, UpdateChannel.ALPHA)
    assert stable is not None and stable.version == "0.1.5"
    assert beta is not None and beta.version == "0.2.0-beta"
    assert alpha is not None and alpha.version == "0.3.0-alpha"


def test_check_for_updates_handles_repository_without_release(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise HTTPError(update_center.GITHUB_RELEASES_URL, 404, "Not Found", {}, None)

    monkeypatch.setattr(update_center.urllib.request, "urlopen", fail)
    result = update_center.check_for_updates(UpdateChannel.ALPHA)
    assert result.status == "no_release"
    assert result.update_available is False
    assert result.latest is None
    assert result.channel == UpdateChannel.ALPHA


def test_check_for_updates_detects_newer_release(monkeypatch) -> None:
    monkeypatch.setattr(update_center, "__version__", "0.1.0")
    monkeypatch.setattr(
        update_center.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _Response([
            {"tag_name": "v0.2.0", "name": "ORION 0.2", "body": "New ATC work", "prerelease": False, "assets": []}
        ]),
    )
    result = update_center.check_for_updates(UpdateChannel.STABLE)
    assert result.status == "update_available"
    assert result.update_available is True
    assert result.latest is not None
    assert result.latest.notes == "New ATC work"


def _binary_response(payload: bytes, content_length: bool = False):
    class BinaryResponse:
        def __init__(self) -> None:
            self.done = False
            self.headers = {"Content-Length": str(len(payload))} if content_length else {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            if self.done:
                return b""
            self.done = True
            return payload

    return BinaryResponse()


def test_download_update_rejects_bad_checksum(monkeypatch, tmp_path: Path) -> None:
    payload = b"installer-bytes"
    monkeypatch.setattr(update_center.urllib.request, "urlopen", lambda *args, **kwargs: _binary_response(payload))
    release = ReleaseInfo("0.2.0", "Update", "", None, "https://example.invalid/setup.exe", "ORION-Setup.exe", "0" * 64)
    with pytest.raises(ValueError, match="SHA-256"):
        update_center.download_update(release, tmp_path)
    assert not (tmp_path / "ORION-Setup.exe").exists()


def test_download_update_accepts_matching_checksum_and_reports_progress(monkeypatch, tmp_path: Path) -> None:
    payload = b"installer-bytes"
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(update_center.urllib.request, "urlopen", lambda *args, **kwargs: _binary_response(payload, True))
    release = ReleaseInfo("0.2.0", "Update", "", None, "https://example.invalid/setup.exe", "ORION-Setup.exe", digest)
    progress: list[tuple[int, int | None]] = []
    path = update_center.download_update(release, tmp_path, progress=lambda done, total: progress.append((done, total)))
    assert path.read_bytes() == payload
    assert progress[-1] == (len(payload), len(payload))


def test_feature_manifest_exposes_current_and_planned_capabilities() -> None:
    statuses = {item.name: item.state for item in update_center.current_feature_status()}
    assert statuses["Diagnostics"] == "available"
    assert statuses["Native Windows launcher"] == "available"
    assert statuses["Mission Studio"] == "planned"
    assert statuses["Multi-provider AI"] == "planned"
