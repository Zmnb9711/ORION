from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orion.active_dcs_installation import ActiveDcsInstallationStore
from orion.build_identity import _read_marker
from orion.dcs_installation_discovery import discover_dcs_installations
from orion.dcs_installations import DcsInstallationType
from orion.dcs_readiness import ORION_EXPORT_LINE, discover_saved_games
from orion.srs_process_control import (
    SrsProcessKind,
    discover_srs_executable,
)
from tools.orion_arch_guard.config import SourceConfig
from tools.orion_arch_guard.discovery import (
    discover_evidence,
    discover_releases,
    discover_runtime_artifacts,
)
from tools.orion_arch_guard.fingerprints import canonical_sha256, sha256_file
from tools.orion_arch_guard.guard_rules import AG3_RULESET_VERSION
from tools.orion_arch_guard.models import SourceType
from tools.orion_development_console.context import VerificationContext
from tools.orion_development_console.models import (
    ComparisonState,
    FactState,
    TruthDomain,
    VerificationObservation,
    VerificationReport,
    VerificationState,
)
from tools.orion_development_console.privacy import sanitize


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _observation(
    context: VerificationContext,
    *,
    subject: str,
    truth_domain: TruthDomain,
    state: VerificationState,
    method: str,
    details: dict[str, Any],
    source_reference: str | None = None,
    installed: FactState = FactState.NOT_CHECKED,
    configured: FactState = FactState.NOT_CHECKED,
    running: FactState = FactState.NOT_CHECKED,
    ready: FactState = FactState.NOT_CHECKED,
) -> VerificationObservation:
    safe_details = sanitize(details)
    fingerprint = canonical_sha256(
        {
            "subject": subject,
            "method": method,
            "details": safe_details,
            "installed": installed.value,
            "configured": configured.value,
            "running": running.value,
            "ready": ready.value,
        }
    )
    return VerificationObservation(
        subject=subject,
        truth_domain=truth_domain,
        state=state,
        verified_at=_iso(context.now()),
        verification_method=method,
        fingerprint=fingerprint,
        source_reference=source_reference,
        details=safe_details,
        installed=installed,
        configured=configured,
        running=running,
        ready=ready,
    )


def _error_observation(
    context: VerificationContext,
    subject: str,
    domain: TruthDomain,
    method: str,
    exc: BaseException,
) -> VerificationObservation:
    return _observation(
        context,
        subject=subject,
        truth_domain=domain,
        state=VerificationState.ERROR,
        method=method,
        details={"error": f"{type(exc).__name__}: {exc}"[:500]},
    )


def collect_git(context: VerificationContext) -> VerificationObservation:
    method = "git_cli_local_no_fetch"
    try:
        git = context.git_runner
        root = context.repository_root
        head = git(root, ("rev-parse", "HEAD"))
        branch = git(root, ("branch", "--show-current")) or "detached"
        history_count = int(git(root, ("rev-list", "--count", "HEAD")))
        status_lines = git(root, ("status", "--porcelain=v1")).splitlines()
        tracked = [line for line in status_lines if not line.startswith("??")]
        staged = [line for line in tracked if line and line[0] not in {" ", "?"}]
        untracked = [line for line in status_lines if line.startswith("??")]
        upstream_name: str | None = None
        upstream_sha: str | None = None
        ahead = behind = None
        try:
            upstream_name = git(
                root,
                ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"),
            )
            upstream_sha = git(root, ("rev-parse", "@{upstream}"))
            divergence = git(
                root,
                ("rev-list", "--left-right", "--count", "HEAD...@{upstream}"),
            ).split()
            if len(divergence) == 2:
                ahead, behind = int(divergence[0]), int(divergence[1])
        except (RuntimeError, ValueError):
            pass
        details = {
            "repository_found": (root / ".git").exists(),
            "history_readable": history_count >= 1,
            "history_commit_count": history_count,
            "branch": branch,
            "head": head,
            "cached_upstream_name": upstream_name,
            "cached_upstream_head": upstream_sha,
            "upstream_semantics": "cached_local_tracking_ref_not_live_remote",
            "ahead": ahead,
            "behind": behind,
            "tracked_clean": not tracked,
            "staged_clean": not staged,
            "tracked_change_count": len(tracked),
            "staged_change_count": len(staged),
            "untracked_count": len(untracked),
            "network_fetch_performed": False,
            "head_vs_cached_upstream": (
                ComparisonState.UNKNOWN.value
                if upstream_sha is None
                else ComparisonState.MATCH.value
                if upstream_sha == head
                else ComparisonState.DIFFERENT.value
            ),
        }
        state = VerificationState.VERIFIED
        if upstream_name is None:
            state = VerificationState.PARTIAL
        elif tracked or staged:
            state = VerificationState.CHANGED
        return _observation(
            context,
            subject="git",
            truth_domain=TruthDomain.DEVELOPMENT,
            state=state,
            method=method,
            details=details,
            source_reference=str(root),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return _error_observation(context, "git", TruthDomain.DEVELOPMENT, method, exc)


def _open_index_read_only(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection


def _latest_report_file(report_root: Path) -> Path | None:
    candidates = sorted(report_root.glob("AG-*.json"), key=lambda item: item.stat().st_mtime_ns)
    return candidates[-1] if candidates else None


def collect_history(context: VerificationContext) -> VerificationObservation:
    method = "guard_manifest_sqlite_graph_and_ag3_report_read_only"
    index_path = context.guard_root / "index.sqlite3"
    manifest_path = context.guard_root / "source-manifest.json"
    report_root = context.guard_root / "reports"
    required_report_path = report_root / f"{context.architecture_report_id}.json"
    try:
        latest_report_path = _latest_report_file(report_root)
        required_payload: dict[str, Any] = {}
        latest_payload: dict[str, Any] = {}
        if required_report_path.is_file():
            required_payload = json.loads(required_report_path.read_text(encoding="utf-8"))
        if latest_report_path is not None:
            latest_payload = json.loads(latest_report_path.read_text(encoding="utf-8"))

        reasons: list[str] = []
        index_details: dict[str, Any] = {}
        if not index_path.is_file():
            reasons.append("guard_index_missing")
        else:
            with _open_index_read_only(index_path) as connection:
                quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
                by_type = dict(
                    connection.execute(
                        "SELECT item_type, COUNT(*) FROM source_items GROUP BY item_type"
                    )
                )
                unavailable = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM sources WHERE availability != 'AVAILABLE'"
                    ).fetchone()[0]
                )
                d73_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM source_items WHERE item_type = 'decision_register_row' AND native_id = 'D73'"
                    ).fetchone()[0]
                )
                graph_table = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'graph_metadata'"
                ).fetchone()[0]
                graph_metadata = (
                    dict(connection.execute("SELECT key, value FROM graph_metadata"))
                    if graph_table
                    else {}
                )
                latest_snapshot = connection.execute(
                    "SELECT snapshot_id, manifest_sha256, indexed_at_utc FROM source_snapshots ORDER BY indexed_at_utc DESC LIMIT 1"
                ).fetchone()
                index_details = {
                    "sqlite_quick_check": quick_check,
                    "chatgpt_conversations": int(by_type.get("chatgpt_conversation", 0)),
                    "chatgpt_messages": int(by_type.get("chatgpt_message", 0)),
                    "codex_sessions": int(by_type.get("codex_session_meta", 0)),
                    "decision_register_count": int(by_type.get("decision_register_row", 0)),
                    "evidence_source_count": int(by_type.get("evidence_archive", 0)),
                    "unavailable_source_count": unavailable,
                    "d73_verified": d73_count > 0,
                    "graph_verified": bool(graph_metadata),
                    "graph_signature": graph_metadata.get("AG2_INPUT_SIGNATURE"),
                    "latest_snapshot": dict(latest_snapshot) if latest_snapshot else None,
                }
                if quick_check != "ok" or d73_count == 0 or not graph_metadata:
                    reasons.append("guard_index_or_graph_incomplete")

        manifest_fingerprint = sha256_file(manifest_path) if manifest_path.is_file() else None
        if manifest_fingerprint is None:
            reasons.append("ag0_manifest_missing")
        required_found = required_report_path.is_file()
        required_gate = str(required_payload.get("gate") or "UNKNOWN")
        report_decisions = required_payload.get("decisions") or {}
        report_d73 = any(
            isinstance(item, dict) and item.get("decision_id") == "D73"
            for item in report_decisions.get("CURRENT", [])
        )
        if not required_found or required_gate != "PASS" or not report_d73:
            reasons.append("required_ag3_report_not_verified")
        details = {
            "guard_operational": index_path.is_file() and required_found,
            "required_report_id": context.architecture_report_id,
            "required_report_found": required_found,
            "required_report_gate": required_gate,
            "last_guard_report_id": latest_payload.get("report_id"),
            "last_guard_gate": str(latest_payload.get("gate") or "UNKNOWN"),
            "last_historical_verification": latest_payload.get("generated_at_utc"),
            "ag0_manifest_found": manifest_path.is_file(),
            "ag0_manifest_fingerprint": manifest_fingerprint,
            "ag1_index_found": index_path.is_file(),
            "ag2_graph_verified": bool(index_details.get("graph_verified")),
            "ag3_ruleset_version": AG3_RULESET_VERSION,
            "index_signature": latest_payload.get("index_signature"),
            "logical_signature": latest_payload.get("logical_signature"),
            "d73_visible_in_report": report_d73,
            **index_details,
            "partial_reasons": reasons,
        }
        return _observation(
            context,
            subject="history",
            truth_domain=TruthDomain.HISTORICAL,
            state=VerificationState.PARTIAL if reasons else VerificationState.VERIFIED,
            method=method,
            details=details,
            source_reference=str(context.guard_root),
        )
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
        return _error_observation(context, "history", TruthDomain.HISTORICAL, method, exc)


def _source_config(context: VerificationContext) -> SourceConfig:
    runtime = context.local_app_data / "ORION" / "runtime"
    return SourceConfig(
        repository_root=context.repository_root,
        output_path=context.guard_root / "source-manifest.json",
        index_path=context.guard_root / "index.sqlite3",
        chatgpt_archive_roots=(),
        codex_history_roots=(),
        evidence_roots=(runtime / "test-evidence",),
        runtime_log_roots=(runtime, context.repository_root / "runtime"),
        release_roots=(context.repository_root,),
    )


def _previous_items(previous: VerificationReport | None, subject: str) -> dict[str, str]:
    if previous is None:
        return {}
    observation = previous.observation(subject)
    if observation is None:
        return {}
    items = observation.details.get("items")
    if not isinstance(items, list):
        return {}
    return {
        str(item.get("id")): str(item.get("fingerprint"))
        for item in items
        if isinstance(item, dict) and item.get("id") and item.get("fingerprint")
    }


def _item_delta(current: dict[str, str], previous: dict[str, str]) -> dict[str, int]:
    if not previous:
        return {"new": 0, "changed": 0, "missing": 0}
    return {
        "new": len(current.keys() - previous.keys()),
        "changed": sum(current[key] != previous[key] for key in current.keys() & previous.keys()),
        "missing": len(previous.keys() - current.keys()),
    }


def _private_locator(path: str) -> str:
    return canonical_sha256({"path": str(Path(path).absolute()).casefold()})


def collect_logs_and_evidence(
    context: VerificationContext,
    previous: VerificationReport | None,
) -> tuple[VerificationObservation, VerificationObservation]:
    config = _source_config(context)
    try:
        log_records = discover_runtime_artifacts(config)
        logs = [item for item in log_records if item.source_type is SourceType.RUNTIME_ARTIFACT]
        log_items = {_private_locator(item.path): str(item.sha256) for item in logs if item.sha256}
        log_delta = _item_delta(log_items, _previous_items(previous, "logs"))
        unavailable_roots = [item.path for item in log_records if not item.exists and item.source_type is SourceType.RUNTIME_ROOT]
        log_state = VerificationState.CHANGED if any(log_delta.values()) else VerificationState.VERIFIED
        if unavailable_roots and not logs:
            log_state = VerificationState.PARTIAL
        log_observation = _observation(
            context,
            subject="logs",
            truth_domain=TruthDomain.MACHINE,
            state=log_state,
            method="ag0_bounded_runtime_artifact_discovery",
            details={
                "runtime_roots": [str(path) for path in config.runtime_log_roots],
                "logs_discovered": len(logs),
                "logs_known_by_fingerprint": len(log_items),
                "new_logs": log_delta["new"],
                "changed_logs": log_delta["changed"],
                "missing_logs": log_delta["missing"],
                "unavailable_roots": unavailable_roots,
                "items": [
                    {"id": source_id, "fingerprint": fingerprint}
                    for source_id, fingerprint in sorted(log_items.items())
                ],
                "content_parsed": False,
            },
        )
    except (OSError, ValueError) as exc:
        log_observation = _error_observation(
            context, "logs", TruthDomain.MACHINE, "ag0_bounded_runtime_artifact_discovery", exc
        )

    try:
        evidence_records = discover_evidence(config)
        evidence = [item for item in evidence_records if item.source_type is SourceType.EVIDENCE_ZIP]
        evidence_items = {
            _private_locator(item.path): str(item.sha256) for item in evidence if item.sha256
        }
        evidence_delta = _item_delta(evidence_items, _previous_items(previous, "evidence"))
        latest = max(evidence, key=lambda item: item.mtime_utc or "", default=None)
        evidence_state = VerificationState.CHANGED if any(evidence_delta.values()) else VerificationState.VERIFIED
        evidence_observation = _observation(
            context,
            subject="evidence",
            truth_domain=TruthDomain.HISTORICAL,
            state=evidence_state,
            method="ag0_bounded_test_evidence_discovery",
            details={
                "evidence_roots": [str(path) for path in config.evidence_roots],
                "evidence_zip_count": len(evidence),
                "new_evidence": evidence_delta["new"],
                "changed_evidence": evidence_delta["changed"],
                "missing_evidence": evidence_delta["missing"],
                "latest_evidence_timestamp": latest.mtime_utc if latest else None,
                "latest_evidence_build_sha": latest.metadata.get("build_sha") if latest else None,
                "items": [
                    {"id": source_id, "fingerprint": fingerprint}
                    for source_id, fingerprint in sorted(evidence_items.items())
                ],
                "private_bodies_parsed_for_dashboard": False,
            },
        )
    except (OSError, ValueError) as exc:
        evidence_observation = _error_observation(
            context, "evidence", TruthDomain.HISTORICAL, "ag0_bounded_test_evidence_discovery", exc
        )
    return log_observation, evidence_observation


_INNO_APP_ID = "{6E4CA1C5-4E77-42CE-9E6B-A6D1124B09E7}_is1"


def _windows_installer_metadata() -> dict[str, str]:
    if os.name != "nt":
        return {}
    import winreg

    subkeys = (
        rf"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{_INNO_APP_ID}",
        rf"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{_INNO_APP_ID}",
    )
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for subkey in subkeys:
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    result: dict[str, str] = {"registry_key": subkey}
                    for source, target in (
                        ("InstallLocation", "install_location"),
                        ("DisplayVersion", "display_version"),
                        ("DisplayName", "display_name"),
                    ):
                        try:
                            result[target] = str(winreg.QueryValueEx(key, source)[0])
                        except OSError:
                            pass
                    return result
            except OSError:
                continue
    return {}


def _installation_candidates(context: VerificationContext, metadata: dict[str, str]) -> tuple[Path, ...]:
    if context.installation_candidates is not None:
        return context.installation_candidates
    candidates: list[Path] = []
    if metadata.get("install_location"):
        candidates.append(Path(metadata["install_location"]))
    for name in ("ProgramFiles", "ProgramFiles(x86)"):
        value = context.environment.get(name)
        if value:
            candidates.append(Path(value) / "ORION")
    return tuple(dict.fromkeys(candidates))


def _comparison(values: list[str | None], target: str | None) -> ComparisonState:
    normalized = [value.casefold() for value in values if value]
    if target is None or len(normalized) != len(values) or not values:
        return ComparisonState.UNKNOWN
    return ComparisonState.MATCH if all(value == target.casefold() for value in normalized) else ComparisonState.DIFFERENT


def _latest_release_sha(context: VerificationContext) -> tuple[str | None, str | None]:
    releases = [
        item
        for item in discover_releases(_source_config(context))
        if item.source_type is SourceType.RELEASE_TREE and item.exists and item.metadata.get("build_sha")
    ]
    latest = max(releases, key=lambda item: item.mtime_utc or "", default=None)
    return (
        str(latest.metadata.get("build_sha")) if latest else None,
        str(latest.metadata.get("release_name")) if latest else None,
    )


def collect_installed_orion(
    context: VerificationContext,
    repository_head: str | None,
) -> VerificationObservation:
    method = "inno_registry_bounded_layout_and_build_identity_markers"
    try:
        metadata = dict(context.installer_metadata or _windows_installer_metadata())
        candidates = _installation_candidates(context, metadata)
        root = next(
            (
                path
                for path in candidates
                if path.is_dir()
                and ((path / "Core" / "ORION-Core.exe").is_file() or (path / "Launcher" / "ORION-Launcher.exe").is_file())
            ),
            None,
        )
        if root is None:
            return _observation(
                context,
                subject="installed_orion",
                truth_domain=TruthDomain.MACHINE,
                state=VerificationState.MISSING,
                method=method,
                details={
                    "orion_installed": "NO",
                    "bounded_candidates_checked": [str(path) for path in candidates],
                    "installer_metadata_found": bool(metadata),
                    "repository_comparison": ComparisonState.UNKNOWN.value,
                    "latest_release_comparison": ComparisonState.UNKNOWN.value,
                },
                installed=FactState.NO,
            )
        core_exe = root / "Core" / "ORION-Core.exe"
        launcher_exe = root / "Launcher" / "ORION-Launcher.exe"
        core_marker = root / "Core" / "build-identity.json"
        launcher_marker = root / "Launcher" / "build-identity.json"
        core_identity = _read_marker(core_marker)
        launcher_identity = _read_marker(launcher_marker)
        core_sha = core_identity.sha if core_identity else None
        launcher_sha = launcher_identity.sha if launcher_identity else None
        repository_comparison = _comparison([core_sha, launcher_sha], repository_head)
        release_sha, release_name = _latest_release_sha(context)
        release_comparison = _comparison([core_sha, launcher_sha], release_sha)
        complete = core_exe.is_file() and launcher_exe.is_file() and core_identity is not None and launcher_identity is not None
        marker_mismatch = bool(core_sha and launcher_sha and core_sha != launcher_sha)
        state = VerificationState.VERIFIED if complete else VerificationState.PARTIAL
        if marker_mismatch:
            state = VerificationState.CHANGED
        version = metadata.get("display_version")
        if not version and core_identity and launcher_identity and core_identity.version == launcher_identity.version:
            version = core_identity.version
        details = {
            "orion_installed": "YES",
            "installation_path": str(root.resolve()),
            "installed_version": version,
            "core_executable_found": core_exe.is_file(),
            "launcher_executable_found": launcher_exe.is_file(),
            "core_build_sha": core_sha,
            "launcher_build_sha": launcher_sha,
            "build_identity_source": "frozen_marker" if core_identity or launcher_identity else None,
            "installer_identity": metadata.get("registry_key") or _INNO_APP_ID,
            "repository_head": repository_head,
            "repository_comparison": repository_comparison.value,
            "latest_local_release": release_name,
            "latest_local_release_sha": release_sha,
            "latest_release_comparison": release_comparison.value,
            "core_launcher_marker_mismatch": marker_mismatch,
        }
        return _observation(
            context,
            subject="installed_orion",
            truth_domain=TruthDomain.MACHINE,
            state=state,
            method=method,
            details=details,
            source_reference=str(root),
            installed=FactState.YES,
            running=FactState.NOT_CHECKED,
            ready=FactState.NOT_CHECKED,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _error_observation(context, "installed_orion", TruthDomain.MACHINE, method, exc)


def _path_snapshot(path: Path, *, max_entries: int = 512) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "fingerprint": None, "entry_count": 0}
    if path.is_file():
        return {"exists": True, "fingerprint": sha256_file(path), "entry_count": 1}
    entries: list[dict[str, Any]] = []
    try:
        for item in sorted(path.iterdir(), key=lambda value: value.name.casefold()):
            lowered = item.name.casefold()
            if lowered.endswith(("-shm", "-wal", ".lock", ".tmp")) or lowered == "__pycache__":
                continue
            if len(entries) >= max_entries:
                break
            stat = item.stat()
            is_directory = item.is_dir()
            entries.append(
                {
                    "name": item.name,
                    "kind": "directory" if is_directory else "file",
                    "size": None if is_directory else stat.st_size,
                    "mtime_ns": None if is_directory else stat.st_mtime_ns,
                }
            )
    except OSError as exc:
        return {"exists": True, "fingerprint": None, "entry_count": len(entries), "error": type(exc).__name__}
    return {
        "exists": True,
        "fingerprint": canonical_sha256(entries),
        "entry_count": len(entries),
        "bounded": True,
    }


def collect_local_data(context: VerificationContext) -> VerificationObservation:
    method = "bounded_known_orion_root_registry"
    orion_local = context.local_app_data / "ORION"
    roots: list[tuple[str, Path, bool]] = [
        ("runtime", orion_local / "runtime", True),
        ("guard", context.guard_root, True),
        ("evidence", orion_local / "runtime" / "test-evidence", False),
        ("logs", orion_local / "runtime" / "logs", False),
        ("diagnostics", orion_local / "runtime" / "diagnostics", False),
        ("active_dcs", orion_local / "active-dcs.json", False),
        ("onboarding", orion_local / "onboarding.json", False),
        ("cloud_voice", orion_local / "runtime" / "cloud-voice.json", False),
        ("communication_profiles", orion_local / "communication-profiles", False),
        ("repository_runtime", context.repository_root / "runtime", False),
    ]
    for path in sorted(context.repository_root.glob("release-*")):
        roots.append((f"local_release:{path.name}", path, False))
    try:
        records: list[dict[str, Any]] = []
        required_missing = False
        access_errors = False
        for name, path, required in roots:
            snapshot = _path_snapshot(path)
            required_missing |= required and not bool(snapshot["exists"])
            access_errors |= bool(snapshot.get("error"))
            records.append(
                {
                    "name": name,
                    "path": str(path),
                    "required": required,
                    "state": (
                        VerificationState.PARTIAL.value
                        if snapshot.get("error")
                        else VerificationState.VERIFIED.value
                        if snapshot["exists"]
                        else VerificationState.MISSING.value
                    ),
                    **snapshot,
                }
            )
        state = VerificationState.VERIFIED
        if required_missing or access_errors:
            state = VerificationState.PARTIAL
        return _observation(
            context,
            subject="local_data",
            truth_domain=TruthDomain.MACHINE,
            state=state,
            method=method,
            details={
                "all_expected_roots_checked": True,
                "required_missing": required_missing,
                "access_errors": access_errors,
                "roots": records,
                "whole_disk_scan_performed": False,
                "missing_directories_created": False,
            },
            source_reference=str(orion_local),
        )
    except OSError as exc:
        return _error_observation(context, "local_data", TruthDomain.MACHINE, method, exc)


def _contains_export_hook(path: Path) -> bool:
    try:
        return path.is_file() and ORION_EXPORT_LINE in path.read_text(encoding="utf-8")
    except OSError:
        return False


def collect_dcs(context: VerificationContext) -> VerificationObservation:
    method = "existing_dcs_bounded_discovery_saved_games_and_hash_comparison"
    try:
        installations = discover_dcs_installations(
            DcsInstallationType.AUTO,
            steam_roots=context.dcs_steam_roots,
            standalone_roots=context.dcs_standalone_roots,
        )
        active_path = context.local_app_data / "ORION" / "active-dcs.json"
        active = ActiveDcsInstallationStore(active_path).get()
        saved_games = discover_saved_games(context.saved_games_root)
        selected = Path(active.saved_games_path) if active and active.saved_games_path else next(
            (Path(item.path) for item in saved_games if item.exists), None
        )
        hook_path = selected / "Scripts" / "Export.lua" if selected else None
        payload_path = selected / "Scripts" / "ORION" / "Export.lua" if selected else None
        expected_path = context.repository_root / "dcs-export" / "Export.lua"
        existing_installations = [item for item in installations.candidates if item.exists]
        hook_found = bool(hook_path and _contains_export_hook(hook_path))
        payload_found = bool(payload_path and payload_path.is_file())
        installed_hash = sha256_file(payload_path) if payload_found and payload_path else None
        expected_hash = sha256_file(expected_path) if expected_path.is_file() else None
        if installed_hash and expected_hash:
            comparison = ComparisonState.MATCH if installed_hash == expected_hash else ComparisonState.DIFFERENT
        else:
            comparison = ComparisonState.UNKNOWN
        configured = hook_found and payload_found
        if comparison is ComparisonState.DIFFERENT:
            state = VerificationState.CHANGED
        elif configured and comparison is ComparisonState.MATCH:
            state = VerificationState.VERIFIED
        elif not existing_installations and selected is None:
            state = VerificationState.MISSING
        elif expected_hash is None:
            state = VerificationState.UNKNOWN
        else:
            state = VerificationState.PARTIAL
        return _observation(
            context,
            subject="dcs_integration",
            truth_domain=TruthDomain.MACHINE,
            state=state,
            method=method,
            details={
                "dcs_installations_found": len(existing_installations),
                "dcs_installations": [
                    {
                        "type": item.installation_type.value,
                        "install_root": item.install_root,
                        "executable_path": item.executable_path,
                        "exists": item.exists,
                    }
                    for item in installations.candidates
                ],
                "selected_installation": active.model_dump(mode="json") if active else None,
                "saved_games_candidates": [item.model_dump(mode="json") for item in saved_games],
                "selected_saved_games": str(selected) if selected else None,
                "export_hook_path": str(hook_path) if hook_path else None,
                "export_hook_found": hook_found,
                "integration_payload_path": str(payload_path) if payload_path else None,
                "integration_payload_found": payload_found,
                "installed_integration_hash": installed_hash,
                "expected_integration_hash": expected_hash,
                "integration_comparison": comparison.value,
                "live_readiness_checked": False,
            },
            source_reference=str(selected) if selected else None,
            installed=FactState.YES if payload_found else FactState.NO,
            configured=FactState.YES if configured else FactState.NO,
            running=FactState.NOT_CHECKED,
            ready=FactState.NOT_CHECKED,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _error_observation(context, "dcs_integration", TruthDomain.MACHINE, method, exc)


def _load_srs_config(context: VerificationContext) -> tuple[str, str]:
    path = context.local_app_data / "ORION" / "runtime" / "cloud-voice.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "", ""
    if not isinstance(payload, dict):
        return "", ""
    return str(payload.get("srs_server_path") or ""), str(payload.get("srs_client_path") or "")


def collect_srs(context: VerificationContext) -> VerificationObservation:
    method = "existing_srs_bounded_discovery_and_passive_exact_process_inspection"
    try:
        server_config, client_config = _load_srs_config(context)
        server = discover_srs_executable(
            SrsProcessKind.SERVER,
            server_config,
            environment=context.srs_environment or context.environment,
        )
        client = discover_srs_executable(
            SrsProcessKind.CLIENT,
            client_config,
            environment=context.srs_environment or context.environment,
        )
        access_partial = False
        running_records: list[dict[str, Any]] = []
        for image in ("SRS-Server.exe", "SR-ClientRadio.exe"):
            try:
                for record in context.process_inspector(image):
                    running_records.append(
                        {"image": image, "pid": record.pid, "executable_path": record.executable_path}
                    )
            except (OSError, PermissionError, RuntimeError):
                access_partial = True
        installed = bool(server or client)
        configured = bool((server_config and server) or (client_config and client))
        running = bool(running_records)
        state = VerificationState.VERIFIED if installed else VerificationState.MISSING
        if access_partial:
            state = VerificationState.PARTIAL
        return _observation(
            context,
            subject="srs",
            truth_domain=TruthDomain.MACHINE,
            state=state,
            method=method,
            details={
                "official_srs_installation_found": installed,
                "server_path": str(server) if server else None,
                "client_path": str(client) if client else None,
                "configured_server_path_present": bool(server_config),
                "configured_client_path_present": bool(client_config),
                "version": None,
                "version_state": VerificationState.UNKNOWN.value,
                "passive_process_inspection_partial": access_partial,
                "running_processes": running_records,
                "srs_started": False,
                "live_readiness_checked": False,
            },
            source_reference=str(client or server) if client or server else None,
            installed=FactState.YES if installed else FactState.NO,
            configured=(
                FactState.YES if configured else FactState.NO if server_config or client_config else FactState.UNKNOWN
            ),
            running=FactState.UNKNOWN if access_partial else FactState.YES if running else FactState.NO,
            ready=FactState.NOT_CHECKED,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _error_observation(context, "srs", TruthDomain.MACHINE, method, exc)
