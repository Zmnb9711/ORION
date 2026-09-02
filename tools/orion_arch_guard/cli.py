from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from tools.orion_arch_guard.config import SourceConfig
from tools.orion_arch_guard.discovery import discover_all
from tools.orion_arch_guard.manifest import (
    build_manifest,
    change_counts,
    compare_sources,
    existing_manifest_sha256,
    read_manifest,
    write_manifest,
)
from tools.orion_arch_guard.models import ChangeStatus, Manifest, SourceChange
from tools.orion_arch_guard.indexing import index_manifest
from tools.orion_arch_guard.queries import HistoryIndex
from tools.orion_arch_guard.fingerprints import sha256_file
from tools.orion_arch_guard.models import SourceType


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.orion_arch_guard",
        description="ORION Architecture Guard source discovery and derived index",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("discover", "verify"):
        command = subparsers.add_parser(name)
        command.add_argument("--config", type=Path)
        command.add_argument("--repository", type=Path)
        command.add_argument("--output", type=Path)
        command.add_argument(
            "--chatgpt-root",
            type=Path,
            action="append",
            help="Override configured ChatGPT archive roots; repeatable",
        )
    subparsers.choices["verify"].add_argument("--manifest", type=Path)
    index = subparsers.add_parser("index")
    index.add_argument("--config", type=Path)
    index.add_argument("--repository", type=Path)
    index.add_argument("--manifest", type=Path)
    index.add_argument("--database", type=Path)
    status = subparsers.add_parser("status")
    status.add_argument("--database", type=Path)
    lookup = subparsers.add_parser("lookup")
    lookup.add_argument("--database", type=Path)
    selector = lookup.add_mutually_exclusive_group(required=True)
    selector.add_argument("--item")
    selector.add_argument("--source")
    selector.add_argument("--native")
    lookup.add_argument("--item-type")
    lookup.add_argument("--neighbors", action="store_true")
    lookup.add_argument("--range-before", type=int, default=0)
    lookup.add_argument("--range-after", type=int, default=0)
    return parser


def _load_config(args: argparse.Namespace, previous: Manifest | None = None) -> SourceConfig:
    repository_arg = getattr(args, "repository", None)
    repository = repository_arg.absolute() if repository_arg else None
    config_arg = getattr(args, "config", None)
    if config_arg:
        config = SourceConfig.from_json(config_arg, repository)
    elif previous is not None:
        config = SourceConfig.from_mapping(previous.discovery_config)
    else:
        config = SourceConfig.defaults(repository)
    return config.with_overrides(
        repository_root=repository,
        output_path=getattr(args, "output", None),
        chatgpt_archive_roots=(
            tuple(args.chatgpt_root) if getattr(args, "chatgpt_root", None) else None
        ),
    )


def _summary(manifest: Manifest) -> dict[str, object]:
    type_counts = Counter(
        source.source_type.value for source in manifest.sources if source.exists
    )
    unavailable = sum(not source.exists for source in manifest.sources)
    git_record = next(
        (
            source
            for source in manifest.sources
            if source.source_type.value == "git_repository"
        ),
        None,
    )
    return {
        "sources_found": sum(source.exists for source in manifest.sources),
        "sources_unavailable": unavailable,
        "chatgpt_archives": type_counts["chatgpt_archive"],
        "codex_sessions": type_counts["codex_rollout"],
        "evidence_zips": type_counts["evidence_zip"],
        "release_trees": type_counts["release_tree"],
        "logs_and_probes": type_counts["runtime_artifact"],
        "project_documents": type_counts["project_document"],
        "git": git_record.metadata if git_record else {"status": "unavailable"},
    }


def _print_changes(changes: Sequence[SourceChange], *, verbose: bool) -> None:
    print("change_summary=" + json.dumps(change_counts(changes), sort_keys=True))
    if not verbose:
        return
    for change in changes:
        if change.status is ChangeStatus.UNCHANGED:
            continue
        print(
            "source_change="
            + json.dumps(
                {
                    "status": change.status.value,
                    "source_type": change.source_type.value,
                    "source_id": change.source_id,
                    "old_path": change.old_path,
                    "new_path": change.new_path,
                    "old_sha256": change.old_sha256,
                    "new_sha256": change.new_sha256,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )


def discover_command(args: argparse.Namespace) -> int:
    temporary_config = _load_config(args)
    output = temporary_config.output_path
    previous = read_manifest(output) if output.is_file() else None
    config = _load_config(args, previous)
    old_hash = existing_manifest_sha256(output)
    current_sources = discover_all(config)
    manifest = build_manifest(
        config, current_sources, previous_manifest_sha256=old_hash
    )
    changes = compare_sources(previous.sources if previous else (), manifest.sources)
    print("discovery_summary=" + json.dumps(_summary(manifest), sort_keys=True))
    _print_changes(changes, verbose=previous is not None)
    write_manifest(output, manifest)
    print(f"manifest={output}")
    return 0


def verify_command(args: argparse.Namespace) -> int:
    manifest_path = args.manifest or args.output
    if manifest_path is None:
        manifest_path = SourceConfig.defaults(args.repository).output_path
    if not manifest_path.is_file():
        print(f"manifest_missing={manifest_path}", file=sys.stderr)
        return 2
    previous = read_manifest(manifest_path)
    config = _load_config(args, previous)
    current = discover_all(config)
    changes = compare_sources(previous.sources, current)
    _print_changes(changes, verbose=True)
    differences = [
        change for change in changes if change.status is not ChangeStatus.UNCHANGED
    ]
    return 1 if differences else 0


_MUTABLE_INDEX_TYPES = {
    SourceType.CODEX_ROLLOUT,
    SourceType.CODEX_HISTORY_ROOT,
    SourceType.RUNTIME_ARTIFACT,
    SourceType.RUNTIME_ROOT,
    SourceType.GIT_REPOSITORY,
    SourceType.CHATGPT_ARCHIVE_ROOT,
    SourceType.EVIDENCE_ROOT,
    SourceType.RELEASE_ROOT,
}


def index_command(args: argparse.Namespace) -> int:
    defaults = SourceConfig.defaults(args.repository)
    initial_config = (
        SourceConfig.from_json(args.config, args.repository)
        if args.config
        else defaults
    )
    manifest_path = args.manifest or initial_config.output_path
    if not manifest_path.is_file():
        print(f"manifest_missing={manifest_path}", file=sys.stderr)
        return 2
    stored = read_manifest(manifest_path)
    config = _load_config(args, stored)
    current_sources = discover_all(config)
    changes = compare_sources(stored.sources, current_sources)
    _print_changes(changes, verbose=True)
    critical = [
        change
        for change in changes
        if change.status is not ChangeStatus.UNCHANGED
        and change.source_type not in _MUTABLE_INDEX_TYPES
    ]
    if critical:
        print(
            "index_blocked=immutable_or_architecture_critical_source_changed; "
            "run discover and review the differential first",
            file=sys.stderr,
        )
        return 3
    effective = Manifest(
        schema_version=stored.schema_version,
        tool_version=stored.tool_version,
        generated_at_utc=stored.generated_at_utc,
        repository_root=stored.repository_root,
        discovery_config=stored.discovery_config,
        previous_manifest_sha256=stored.previous_manifest_sha256,
        sources=current_sources,
    )
    database = (args.database or config.resolved_index_path).absolute()
    result = index_manifest(
        effective,
        database,
        manifest_sha256=sha256_file(manifest_path),
    )
    print("index_result=" + json.dumps(asdict(result), sort_keys=True))
    return 1 if result.sources_failed else 0


def _database_path(value: Path | None) -> Path:
    return (value or SourceConfig.defaults().resolved_index_path).absolute()


def status_command(args: argparse.Namespace) -> int:
    database = _database_path(args.database)
    if not database.is_file():
        print(f"index_missing={database}", file=sys.stderr)
        return 2
    index = HistoryIndex(database)
    try:
        print(json.dumps(index.status(), ensure_ascii=False, indent=2, sort_keys=True))
    finally:
        index.close()
    return 0


def lookup_command(args: argparse.Namespace) -> int:
    database = _database_path(args.database)
    if not database.is_file():
        print(f"index_missing={database}", file=sys.stderr)
        return 2
    index = HistoryIndex(database)
    try:
        if args.item:
            if args.neighbors:
                result: object = index.neighbors(args.item)
            elif args.range_before or args.range_after:
                result = index.thread_range(
                    args.item, before=args.range_before, after=args.range_after
                )
            else:
                result = index.get_item(args.item)
        elif args.source:
            result = index.get_source(args.source)
        else:
            result = index.find_native(args.native, item_type=args.item_type)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result else 1
    finally:
        index.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "discover":
        return discover_command(args)
    if args.command == "verify":
        return verify_command(args)
    if args.command == "index":
        return index_command(args)
    if args.command == "status":
        return status_command(args)
    if args.command == "lookup":
        return lookup_command(args)
    raise AssertionError(f"unsupported command: {args.command}")
