from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.orion_arch_guard",
        description="ORION Architecture Guard AG-0 source discovery",
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
    return parser


def _load_config(args: argparse.Namespace, previous: Manifest | None = None) -> SourceConfig:
    repository = args.repository.absolute() if args.repository else None
    if args.config:
        config = SourceConfig.from_json(args.config, repository)
    elif previous is not None:
        config = SourceConfig.from_mapping(previous.discovery_config)
    else:
        config = SourceConfig.defaults(repository)
    return config.with_overrides(
        repository_root=repository,
        output_path=args.output,
        chatgpt_archive_roots=(
            tuple(args.chatgpt_root) if args.chatgpt_root else None
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


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "discover":
        return discover_command(args)
    if args.command == "verify":
        return verify_command(args)
    raise AssertionError(f"unsupported command: {args.command}")
