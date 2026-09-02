from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from tools.orion_arch_guard.config import SourceConfig
from tools.orion_arch_guard.cli import main
from tools.orion_arch_guard.discovery import (
    discover_chatgpt_archives,
    discover_codex_history,
    discover_evidence,
    discover_git,
)
from tools.orion_arch_guard.fingerprints import file_record, missing_record, sha256_file
from tools.orion_arch_guard.manifest import (
    build_manifest,
    compare_sources,
    read_manifest,
    write_manifest,
)
from tools.orion_arch_guard.models import ChangeStatus, PrivacyClass, SourceType


def _config(tmp_path: Path) -> SourceConfig:
    repository = tmp_path / "repository"
    chatgpt = tmp_path / "chatgpt"
    codex = tmp_path / "codex"
    evidence = tmp_path / "evidence"
    runtime = tmp_path / "runtime"
    releases = tmp_path / "releases"
    for path in (repository, chatgpt, codex, evidence, runtime, releases):
        path.mkdir()
    return SourceConfig(
        repository_root=repository,
        output_path=tmp_path / "local" / "source-manifest.json",
        chatgpt_archive_roots=(chatgpt,),
        codex_history_roots=(codex,),
        evidence_roots=(evidence,),
        runtime_log_roots=(runtime,),
        release_roots=(releases,),
    )


def _private_file_record(path: Path):  # noqa: ANN202
    return file_record(
        path,
        source_type=SourceType.CODEX_ROLLOUT,
        privacy_class=PrivacyClass.PRIVATE_PRIMARY_HISTORY,
        discovery_method="test",
    )


def _write_zip(path: Path, entries: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in entries.items():
            archive.writestr(name, value)


def test_immutable_file_fingerprint_and_stable_source_id(tmp_path: Path) -> None:
    source = tmp_path / "history.jsonl"
    source.write_bytes(b"immutable history\n")

    first = _private_file_record(source)
    second = _private_file_record(source)

    assert first.sha256 == sha256_file(source)
    assert first.size_bytes == len(b"immutable history\n")
    assert first.source_id == second.source_id
    assert first.privacy_class is PrivacyClass.PRIVATE_PRIMARY_HISTORY


def test_relocated_identical_source_is_not_a_second_fact(tmp_path: Path) -> None:
    original = tmp_path / "old" / "rollout.jsonl"
    relocated = tmp_path / "new" / "rollout.jsonl"
    original.parent.mkdir()
    relocated.parent.mkdir()
    original.write_bytes(b"same")
    relocated.write_bytes(b"same")

    changes = compare_sources(
        (_private_file_record(original),), (_private_file_record(relocated),)
    )

    assert len(changes) == 1
    assert changes[0].status is ChangeStatus.RELOCATED
    assert changes[0].old_path == str(original.absolute())
    assert changes[0].new_path == str(relocated.absolute())


def test_changed_missing_new_and_unchanged_semantics(tmp_path: Path) -> None:
    changed = tmp_path / "changed.jsonl"
    missing = tmp_path / "missing.jsonl"
    unchanged = tmp_path / "unchanged.jsonl"
    new = tmp_path / "new.jsonl"
    for path, value in (
        (changed, b"old"),
        (missing, b"gone"),
        (unchanged, b"same"),
    ):
        path.write_bytes(value)
    old = (
        _private_file_record(changed),
        _private_file_record(missing),
        _private_file_record(unchanged),
    )
    changed.write_bytes(b"new")
    missing.unlink()
    new.write_bytes(b"brand new")
    current = (
        _private_file_record(changed),
        missing_record(
            missing,
            source_type=SourceType.CODEX_ROLLOUT,
            privacy_class=PrivacyClass.PRIVATE_PRIMARY_HISTORY,
            discovery_method="test",
        ),
        _private_file_record(unchanged),
        _private_file_record(new),
    )

    statuses = {change.new_path or change.old_path: change.status for change in compare_sources(old, current)}

    assert statuses[str(changed.absolute())] is ChangeStatus.CHANGED
    assert statuses[str(missing.absolute())] is ChangeStatus.MISSING
    assert statuses[str(unchanged.absolute())] is ChangeStatus.UNCHANGED
    assert statuses[str(new.absolute())] is ChangeStatus.NEW


def test_config_accepts_configurable_windows_paths(tmp_path: Path) -> None:
    base = _config(tmp_path)
    payload = {
        "chatgpt_archive_roots": [r"C:\History\ChatGPT"],
        "codex_history_roots": [r"D:\Codex\sessions"],
        "evidence_roots": [r"E:\ORION\evidence"],
    }

    config = SourceConfig.from_mapping(payload, base=base)

    assert str(config.chatgpt_archive_roots[0]).casefold().endswith(
        r"c:\history\chatgpt".casefold()
    )
    assert str(config.codex_history_roots[0]).casefold().endswith(
        r"d:\codex\sessions".casefold()
    )


def test_chatgpt_zip_detection_records_count_but_not_body(tmp_path: Path) -> None:
    config = _config(tmp_path)
    secret = "API_KEY_DO_NOT_COPY_123456789"
    archive = config.chatgpt_archive_roots[0] / "export.zip"
    _write_zip(
        archive,
        {
            "conversations.json": json.dumps(
                [{"title": "ORION", "mapping": {"x": {"message": secret}}}]
            ),
            "chat.html": f"<p>{secret}</p>",
        },
    )

    records = discover_chatgpt_archives(config)
    source = next(
        item for item in records if item.source_type is SourceType.CHATGPT_ARCHIVE
    )

    assert source.metadata["conversation_count_mechanical"] == 1
    assert source.privacy_class is PrivacyClass.PRIVATE_PRIMARY_HISTORY
    assert secret not in json.dumps(source.to_dict())


def test_codex_jsonl_detection(tmp_path: Path) -> None:
    config = _config(tmp_path)
    rollout = config.codex_history_roots[0] / "2026" / "rollout.jsonl"
    rollout.parent.mkdir()
    rollout.write_text('{"type":"message"}\n', encoding="utf-8")

    records = discover_codex_history(config)
    source = next(
        item for item in records if item.source_type is SourceType.CODEX_ROLLOUT
    )

    assert source.path == str(rollout.absolute())
    assert source.format == "codex-rollout/jsonl"
    assert source.metadata["coverage"] == "PARTIAL"


def test_evidence_zip_detection_keeps_only_allowlisted_metadata(tmp_path: Path) -> None:
    config = _config(tmp_path)
    secret = "SECRET_API_KEY_abcdef0123456789abcdef0123456789abcdef01"
    build_sha = "255f2007abd44885d24d8dd2e45974d2873e4b14"
    archive = config.evidence_roots[0] / "ORION-Test-Evidence-20260902-000000.zip"
    _write_zip(
        archive,
        {
            "manifest.txt": (
                f"api_key={secret}\n"
                f"orion_build_sha={build_sha}\n"
                "test_session_id=abcdef01-2345-6789-abcd-ef0123456789\n"
                "evidence_type=FIELD\n"
            ),
            "events.jsonl": f'{{"Authorization":"{secret}"}}\n',
        },
    )

    records = discover_evidence(config)
    source = next(
        item for item in records if item.source_type is SourceType.EVIDENCE_ZIP
    )
    encoded = json.dumps(source.to_dict())

    assert source.metadata["build_sha"] == build_sha
    assert source.metadata["explicit_evidence_kind"] == "FIELD"
    assert secret not in encoded
    assert "Authorization" not in encoded


def test_git_state_discovery_is_bounded_and_tracks_all_refs(tmp_path: Path) -> None:
    config = _config(tmp_path)
    repository = config.repository_root
    subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "ag0@example.invalid"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "AG0 Test"], cwd=repository, check=True)
    (repository / "tracked.txt").write_text("tracked", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repository, check=True, capture_output=True)

    record = discover_git(config)

    assert record.exists is True
    assert record.metadata["current_branch"] == "main"
    assert record.metadata["commit_count_all"] == 1
    assert record.metadata["all_refs_discoverable"] is True
    assert record.metadata["renamed_lineage_followable"] is True
    encoded = json.dumps(record.to_dict()).casefold()
    assert "https://" not in encoded
    assert "ag0@example.invalid" not in encoded


def test_manifest_local_output_contains_no_source_body_or_secret(tmp_path: Path) -> None:
    config = _config(tmp_path)
    source_path = config.codex_history_roots[0] / "rollout.jsonl"
    secret = "Bearer private-token-value"
    source_path.write_text(secret, encoding="utf-8")
    source = _private_file_record(source_path)
    manifest = build_manifest(config, (source,))

    write_manifest(config.output_path, manifest)
    encoded = config.output_path.read_text(encoding="utf-8")

    assert config.output_path.parent.is_dir()
    assert read_manifest(config.output_path).sources == (source,)
    assert secret not in encoded
    assert "Bearer" not in encoded


def test_missing_configured_root_is_reported_not_created(tmp_path: Path) -> None:
    config = _config(tmp_path)
    missing = tmp_path / "does-not-exist"
    config = config.with_overrides(chatgpt_archive_roots=(missing,))

    records = discover_chatgpt_archives(config)

    assert len(records) == 1
    assert records[0].exists is False
    assert records[0].source_type is SourceType.CHATGPT_ARCHIVE_ROOT
    assert not missing.exists()


def test_manifest_round_trip_rejects_no_fields(tmp_path: Path) -> None:
    config = _config(tmp_path)
    source_path = tmp_path / "source.log"
    source_path.write_text("bounded", encoding="utf-8")
    source = file_record(
        source_path,
        source_type=SourceType.RUNTIME_ARTIFACT,
        privacy_class=PrivacyClass.PRIVATE_RUNTIME_LOG,
        discovery_method="test",
    )
    manifest = build_manifest(config, (source,), previous_manifest_sha256="A" * 64)

    write_manifest(config.output_path, manifest)
    loaded = read_manifest(config.output_path)

    assert loaded == manifest


def test_discover_and_verify_cli_use_private_local_manifest(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config_path = tmp_path / "source-roots.json"
    config_path.write_text(json.dumps(config.to_dict()), encoding="utf-8")

    assert main(["discover", "--config", str(config_path)]) == 0
    assert config.output_path.is_file()
    assert main(["verify", "--manifest", str(config.output_path)]) == 0


@pytest.mark.parametrize(
    ("source_type", "privacy"),
    [
        (SourceType.CHATGPT_ARCHIVE, PrivacyClass.PRIVATE_PRIMARY_HISTORY),
        (SourceType.EVIDENCE_ZIP, PrivacyClass.PRIVATE_EVIDENCE),
        (SourceType.RUNTIME_ARTIFACT, PrivacyClass.PRIVATE_RUNTIME_LOG),
        (SourceType.PROJECT_DOCUMENT, PrivacyClass.PROJECT_GIT),
    ],
)
def test_required_privacy_classes_are_serializable(
    tmp_path: Path, source_type: SourceType, privacy: PrivacyClass
) -> None:
    path = tmp_path / f"{source_type.value}.txt"
    path.write_text("safe", encoding="utf-8")

    record = file_record(
        path,
        source_type=source_type,
        privacy_class=privacy,
        discovery_method="test",
    )

    assert record.to_dict()["privacy_class"] == privacy
