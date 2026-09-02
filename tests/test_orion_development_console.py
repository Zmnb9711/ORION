from __future__ import annotations

import json
import sqlite3
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from orion.srs_process_control import SrsProcessRecord
from tools.orion_development_console.collectors import (
    collect_dcs,
    collect_git,
    collect_history,
    collect_installed_orion,
    collect_local_data,
    collect_logs_and_evidence,
    collect_srs,
)
from tools.orion_development_console.context import VerificationContext
from tools.orion_development_console.engine import (
    VerificationEngine,
    age_observation,
    apply_previous_fingerprint,
)
from tools.orion_development_console.models import (
    FactState,
    TruthDomain,
    VerificationObservation,
    VerificationReport,
    VerificationState,
)
from tools.orion_development_console.presentation import presentation_rows
from tools.orion_development_console.store import VerificationReportStore


NOW = datetime(2026, 9, 2, 20, 0, tzinfo=UTC)
HEAD = "1d4e0cbc299c8e2dd3db041bec10099b6172f68c"


class FakeGit:
    def __init__(
        self,
        *,
        head: str = HEAD,
        upstream: str | None = HEAD,
        status: str = "",
    ) -> None:
        self.head = head
        self.upstream = upstream
        self.status = status
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, _repository: Path, arguments: tuple[str, ...]) -> str:
        self.calls.append(arguments)
        if arguments == ("rev-parse", "HEAD"):
            return self.head
        if arguments == ("branch", "--show-current"):
            return "dev/adr004-post-389"
        if arguments == ("rev-list", "--count", "HEAD"):
            return "1708"
        if arguments == ("status", "--porcelain=v1"):
            return self.status
        if arguments == (
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{upstream}",
        ):
            if self.upstream is None:
                raise RuntimeError("no upstream")
            return "origin/dev/adr004-post-389"
        if arguments == ("rev-parse", "@{upstream}"):
            if self.upstream is None:
                raise RuntimeError("no upstream")
            return self.upstream
        if arguments == (
            "rev-list",
            "--left-right",
            "--count",
            "HEAD...@{upstream}",
        ):
            return "0\t0" if self.upstream == self.head else "1\t2"
        raise AssertionError(arguments)


def _context(tmp_path: Path, **updates: object) -> VerificationContext:
    repository = tmp_path / "repo"
    repository.mkdir(exist_ok=True)
    (repository / ".git").mkdir(exist_ok=True)
    local = tmp_path / "local"
    guard = local / "ORION" / "development" / "architecture-guard"
    console = local / "ORION" / "development" / "console"
    values: dict[str, object] = {
        "repository_root": repository,
        "local_app_data": local,
        "guard_root": guard,
        "console_root": console,
        "saved_games_root": tmp_path / "Saved Games",
        "dcs_steam_roots": [],
        "dcs_standalone_roots": [],
        "installation_candidates": (),
        "git_runner": FakeGit(),
        "process_inspector": lambda _image: (),
        "now": lambda: NOW,
        "environment": {},
        "srs_environment": {},
    }
    values.update(updates)
    return VerificationContext(**values)  # type: ignore[arg-type]


def _guard_fixture(context: VerificationContext, *, signature: str = "INDEX-A") -> None:
    context.guard_root.mkdir(parents=True, exist_ok=True)
    (context.guard_root / "source-manifest.json").write_text(
        json.dumps({"schema_version": 1, "sources": []}), encoding="utf-8"
    )
    reports = context.guard_root / "reports"
    reports.mkdir()
    (reports / f"{context.architecture_report_id}.json").write_text(
        json.dumps(
            {
                "report_id": context.architecture_report_id,
                "gate": "PASS",
                "generated_at_utc": NOW.isoformat(),
                "index_signature": signature,
                "logical_signature": "LOGICAL-A",
                "decisions": {"CURRENT": [{"decision_id": "D73"}]},
            }
        ),
        encoding="utf-8",
    )
    with sqlite3.connect(context.guard_root / "index.sqlite3") as connection:
        connection.executescript(
            """
            CREATE TABLE source_items(item_type TEXT, native_id TEXT);
            CREATE TABLE sources(availability TEXT);
            CREATE TABLE graph_metadata(key TEXT, value TEXT);
            CREATE TABLE source_snapshots(snapshot_id TEXT, manifest_sha256 TEXT, indexed_at_utc TEXT);
            """
        )
        rows = [
            ("decision_register_row", "D73"),
            *[("decision_register_row", f"D{index:02d}") for index in range(1, 73)],
            ("chatgpt_conversation", "chat-1"),
            ("chatgpt_message", "message-1"),
            ("codex_session_meta", "session-1"),
            ("evidence_archive", "evidence-1"),
        ]
        connection.executemany("INSERT INTO source_items VALUES (?, ?)", rows)
        connection.execute("INSERT INTO sources VALUES ('AVAILABLE')")
        connection.execute("INSERT INTO graph_metadata VALUES ('AG2_INPUT_SIGNATURE', 'GRAPH-A')")
        connection.execute(
            "INSERT INTO source_snapshots VALUES ('snapshot:a', 'manifest-a', ?)",
            (NOW.isoformat(),),
        )


def _marker(path: Path, sha: str, *, version: str = "0.2.0-alpha") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "sha": sha,
                "branch": "dev/adr004-post-389",
                "version": version,
            }
        ),
        encoding="utf-8",
    )


def _install(root: Path, core_sha: str | None, launcher_sha: str | None) -> None:
    (root / "Core").mkdir(parents=True)
    (root / "Launcher").mkdir(parents=True)
    (root / "Core" / "ORION-Core.exe").write_bytes(b"core")
    (root / "Launcher" / "ORION-Launcher.exe").write_bytes(b"launcher")
    if core_sha:
        _marker(root / "Core" / "build-identity.json", core_sha)
    if launcher_sha:
        _marker(root / "Launcher" / "build-identity.json", launcher_sha)


def _minimal_report(observations: list[VerificationObservation]) -> VerificationReport:
    return VerificationReport(
        verification_id="OV-old",
        generated_at=NOW.isoformat(),
        repository_head=HEAD,
        architecture_guard_report_id="AG-test",
        architecture_guard_gate="PASS",
        observations=observations,
        actions_not_performed=[],
    )


def test_git_match_uses_cached_upstream_without_fetch(tmp_path: Path) -> None:
    git = FakeGit()
    observation = collect_git(_context(tmp_path, git_runner=git))
    assert observation.state is VerificationState.VERIFIED
    assert observation.details["head_vs_cached_upstream"] == "MATCH"
    assert observation.details["upstream_semantics"] == "cached_local_tracking_ref_not_live_remote"
    assert observation.details["network_fetch_performed"] is False
    assert all("fetch" not in call for call in git.calls)


def test_git_different_and_dirty_are_visible(tmp_path: Path) -> None:
    different = collect_git(_context(tmp_path, git_runner=FakeGit(upstream="a" * 40)))
    dirty = collect_git(_context(tmp_path, git_runner=FakeGit(status=" M tracked.py\nA  staged.py\n?? generated/")))
    assert different.details["head_vs_cached_upstream"] == "DIFFERENT"
    assert different.details["ahead"] == 1 and different.details["behind"] == 2
    assert dirty.state is VerificationState.CHANGED
    assert dirty.details["tracked_change_count"] == 2
    assert dirty.details["staged_change_count"] == 1
    assert dirty.details["untracked_count"] == 1


def test_missing_upstream_is_partial_not_live_remote_claim(tmp_path: Path) -> None:
    observation = collect_git(_context(tmp_path, git_runner=FakeGit(upstream=None)))
    assert observation.state is VerificationState.PARTIAL
    assert observation.details["cached_upstream_head"] is None


def test_guard_index_and_d73_are_verified_read_only(tmp_path: Path) -> None:
    context = _context(tmp_path)
    _guard_fixture(context)
    before = (context.guard_root / "index.sqlite3").stat().st_mtime_ns
    observation = collect_history(context)
    after = (context.guard_root / "index.sqlite3").stat().st_mtime_ns
    assert observation.state is VerificationState.VERIFIED
    assert observation.details["d73_verified"] is True
    assert observation.details["decision_register_count"] == 73
    assert observation.details["index_signature"] == "INDEX-A"
    assert before == after


def test_required_preflight_and_latest_guard_are_distinct(tmp_path: Path) -> None:
    context = _context(tmp_path)
    _guard_fixture(context)
    latest_id = "AG-20260902-210000-latest"
    latest = context.guard_root / "reports" / f"{latest_id}.json"
    latest.write_text(
        json.dumps(
            {
                "report_id": latest_id,
                "gate": "PASS",
                "generated_at_utc": (NOW + timedelta(hours=1)).isoformat(),
                "index_signature": "INDEX-LATEST",
                "logical_signature": "LOGICAL-LATEST",
                "decisions": {"CURRENT": [{"decision_id": "D73"}]},
            }
        ),
        encoding="utf-8",
    )
    latest.touch()
    observation = collect_history(context)
    assert observation.details["required_report_id"] == context.architecture_report_id
    assert observation.details["required_report_gate"] == "PASS"
    assert observation.details["last_guard_report_id"] == latest_id
    assert observation.details["index_signature"] == "INDEX-LATEST"


def test_guard_fingerprint_change_invalidates_verified_state(tmp_path: Path) -> None:
    context = _context(tmp_path)
    _guard_fixture(context)
    previous = collect_history(context)
    previous.details["index_signature"] = "OLD"
    previous.fingerprint = "OLD-FINGERPRINT"
    current = collect_history(context)
    changed = apply_previous_fingerprint(current, previous)
    assert changed.state is VerificationState.CHANGED
    assert changed.invalidated_by == ["fingerprint_changed_since_previous_verification"]


def test_logs_detect_new_changed_and_missing_without_parsing_content(tmp_path: Path) -> None:
    context = _context(tmp_path)
    runtime = context.local_app_data / "ORION" / "runtime"
    runtime.mkdir(parents=True)
    first = runtime / "first.jsonl"
    removed = runtime / "removed.log"
    first.write_text('{"event":"one"}\n', encoding="utf-8")
    removed.write_text("old\n", encoding="utf-8")
    before, _ = collect_logs_and_evidence(context, None)
    previous = _minimal_report([before])
    first.write_text('{"event":"two"}\n', encoding="utf-8")
    removed.unlink()
    (runtime / "new.log").write_text("new\n", encoding="utf-8")
    after, _ = collect_logs_and_evidence(context, previous)
    assert after.state is VerificationState.CHANGED
    assert after.details["new_logs"] == 1
    assert after.details["changed_logs"] == 1
    assert after.details["missing_logs"] == 1
    assert after.details["content_parsed"] is False


def test_evidence_discovery_is_bounded_and_private(tmp_path: Path) -> None:
    context = _context(tmp_path)
    root = context.local_app_data / "ORION" / "runtime" / "test-evidence"
    root.mkdir(parents=True)
    archive = root / "ORION-Test-Evidence-20260902-200000.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("summary.json", json.dumps({"build_sha": HEAD, "api_key": "DO-NOT-READ"}))
    _, observation = collect_logs_and_evidence(context, None)
    serialized = observation.model_dump_json()
    assert observation.details["evidence_zip_count"] == 1
    assert observation.details["private_bodies_parsed_for_dashboard"] is False
    assert "DO-NOT-READ" not in serialized


@pytest.mark.parametrize(
    ("core_sha", "launcher_sha", "expected_state", "comparison"),
    [
        (HEAD, HEAD, VerificationState.VERIFIED, "MATCH"),
        ("a" * 40, "a" * 40, VerificationState.VERIFIED, "DIFFERENT"),
        (HEAD, None, VerificationState.PARTIAL, "UNKNOWN"),
        (HEAD, "a" * 40, VerificationState.CHANGED, "DIFFERENT"),
    ],
)
def test_installed_orion_match_different_unknown_and_marker_mismatch(
    tmp_path: Path,
    core_sha: str | None,
    launcher_sha: str | None,
    expected_state: VerificationState,
    comparison: str,
) -> None:
    install = tmp_path / "ORION"
    _install(install, core_sha, launcher_sha)
    context = _context(
        tmp_path,
        installation_candidates=(install,),
        installer_metadata={"display_version": "0.2.0-alpha"},
    )
    observation = collect_installed_orion(context, HEAD)
    assert observation.state is expected_state
    assert observation.details["repository_comparison"] == comparison
    assert observation.ready is FactState.NOT_CHECKED


def test_missing_installation_is_not_inferred_from_repository(tmp_path: Path) -> None:
    observation = collect_installed_orion(_context(tmp_path), HEAD)
    assert observation.state is VerificationState.MISSING
    assert observation.installed is FactState.NO
    assert observation.details["repository_comparison"] == "UNKNOWN"


def test_local_missing_roots_are_not_created(tmp_path: Path) -> None:
    context = _context(tmp_path)
    runtime = context.local_app_data / "ORION" / "runtime"
    observation = collect_local_data(context)
    assert observation.state is VerificationState.PARTIAL
    assert not runtime.exists()
    assert observation.details["missing_directories_created"] is False


def test_local_data_fingerprint_ignores_sqlite_sidecars_and_directory_mtime(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    runtime = context.local_app_data / "ORION" / "runtime"
    runtime.mkdir(parents=True)
    context.guard_root.mkdir(parents=True)
    (context.guard_root / "index.sqlite3").write_bytes(b"index")
    (context.guard_root / "reports").mkdir()
    first = collect_local_data(context)
    (context.guard_root / "index.sqlite3-shm").write_bytes(b"volatile-one")
    second = collect_local_data(context)
    (context.guard_root / "index.sqlite3-shm").write_bytes(b"volatile-two")
    (context.guard_root / "reports" / "new-report.json").write_text("{}", encoding="utf-8")
    third = collect_local_data(context)
    assert first.fingerprint == second.fingerprint == third.fingerprint


@pytest.mark.parametrize(
    ("installed_payload", "expected_payload", "expected_state", "comparison"),
    [
        (b"same", b"same", VerificationState.VERIFIED, "MATCH"),
        (b"old", b"new", VerificationState.CHANGED, "DIFFERENT"),
        (None, b"new", VerificationState.PARTIAL, "UNKNOWN"),
    ],
)
def test_dcs_configured_is_separate_from_ready_and_hash_comparison(
    tmp_path: Path,
    installed_payload: bytes | None,
    expected_payload: bytes,
    expected_state: VerificationState,
    comparison: str,
) -> None:
    context = _context(tmp_path)
    assert context.saved_games_root is not None
    saved = context.saved_games_root / "DCS"
    scripts = saved / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "Export.lua").write_text(
        'dofile(lfs.writedir() .. "Scripts/ORION/Export.lua")\n', encoding="utf-8"
    )
    if installed_payload is not None:
        payload = scripts / "ORION" / "Export.lua"
        payload.parent.mkdir()
        payload.write_bytes(installed_payload)
    expected = context.repository_root / "dcs-export" / "Export.lua"
    expected.parent.mkdir()
    expected.write_bytes(expected_payload)
    observation = collect_dcs(context)
    assert observation.state is expected_state
    assert observation.details["integration_comparison"] == comparison
    assert observation.ready is FactState.NOT_CHECKED
    assert observation.details["live_readiness_checked"] is False


def test_srs_installed_running_and_version_unknown(tmp_path: Path) -> None:
    program_files = tmp_path / "Program Files"
    client = program_files / "DCS-SimpleRadio-Standalone" / "Client" / "SR-ClientRadio.exe"
    client.parent.mkdir(parents=True)
    client.write_bytes(b"srs")
    context = _context(
        tmp_path,
        srs_environment={"ProgramFiles": str(program_files)},
        process_inspector=lambda image: (
            (SrsProcessRecord(42, str(client)),) if image == "SR-ClientRadio.exe" else ()
        ),
    )
    observation = collect_srs(context)
    assert observation.installed is FactState.YES
    assert observation.running is FactState.YES
    assert observation.details["version_state"] == "UNKNOWN"
    assert observation.ready is FactState.NOT_CHECKED
    assert observation.details["srs_started"] is False


def test_srs_access_denied_is_partial_and_running_unknown(tmp_path: Path) -> None:
    program_files = tmp_path / "Program Files"
    client = program_files / "DCS-SimpleRadio-Standalone" / "Client" / "SR-ClientRadio.exe"
    client.parent.mkdir(parents=True)
    client.write_bytes(b"srs")

    def denied(_image: str) -> tuple[SrsProcessRecord, ...]:
        raise PermissionError("denied")

    observation = collect_srs(
        _context(
            tmp_path,
            srs_environment={"ProgramFiles": str(program_files)},
            process_inspector=denied,
        )
    )
    assert observation.state is VerificationState.PARTIAL
    assert observation.running is FactState.UNKNOWN


def test_staleness_after_age_and_fingerprint_change() -> None:
    observation = VerificationObservation(
        subject="git",
        truth_domain=TruthDomain.DEVELOPMENT,
        state=VerificationState.VERIFIED,
        verified_at=NOW.isoformat(),
        verification_method="fixture",
        fingerprint="A",
    )
    aged = age_observation(observation, now=NOW + timedelta(hours=25), max_age=timedelta(hours=24))
    changed = apply_previous_fingerprint(observation.model_copy(update={"fingerprint": "B"}), observation)
    assert aged.state is VerificationState.STALE
    assert changed.state is VerificationState.CHANGED


def test_verify_everything_records_forbidden_actions_and_writes_only_console_cache(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _guard_fixture(context)
    runtime = context.local_app_data / "ORION" / "runtime"
    runtime.mkdir(parents=True)
    store = VerificationReportStore(context.console_root)
    report = VerificationEngine(context, store=store).verify_everything()
    assert report.network_accessed is False
    assert report.product_processes_launched is False
    assert report.primary_history_modified is False
    assert {"git_fetch", "start_dcs", "start_srs", "request_elevation"} <= set(
        report.actions_not_performed
    )
    assert store.latest_path.is_file()
    assert not (context.repository_root / "runtime").exists()


def test_report_privacy_redacts_sensitive_detail_keys(tmp_path: Path) -> None:
    context = _context(tmp_path)
    _guard_fixture(context)
    report = VerificationEngine(context).verify_everything(persist=False)
    payload = report.model_dump_json()
    assert "api_key" not in payload.casefold()
    assert "password" not in payload.casefold()
    assert "bearer" not in payload.casefold()


def test_ui_state_mapping_has_permanent_eight_rows(tmp_path: Path) -> None:
    context = _context(tmp_path)
    _guard_fixture(context)
    report = VerificationEngine(context).verify_everything(persist=False)
    rows = presentation_rows(report)
    assert [row["subject"] for row in rows] == [
        "git",
        "history",
        "logs",
        "evidence",
        "installed_orion",
        "local_data",
        "dcs_integration",
        "srs",
    ]
    assert all(row["state"] and row["summary"] and row["verified_at"] for row in rows)
