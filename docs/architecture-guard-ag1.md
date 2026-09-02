# ORION Architecture Guard AG-1

AG-1 extends AG-0 source discovery with a private, derived SQLite index for
exact historical-source retrieval. It remains development tooling and is not
part of Core, Launcher, packaging, DCS, SRS, or any provider path.

The database is not authoritative. ChatGPT/Codex archives, Git, Evidence ZIPs,
runtime artifacts, releases, and project documents remain L0. Every indexed
item carries an exact structured pointer back to its L0 source.

## Location and commands

The default database is outside Git:

```text
%LOCALAPPDATA%\ORION\development\architecture-guard\index.sqlite3
```

From the repository root:

```powershell
python -m tools.orion_arch_guard discover
python -m tools.orion_arch_guard verify
python -m tools.orion_arch_guard index
python -m tools.orion_arch_guard status
python -m tools.orion_arch_guard lookup --item <item-id>
python -m tools.orion_arch_guard lookup --native D71 --item-type decision_register_row
python -m tools.orion_arch_guard lookup --item <item-id> --neighbors
python -m tools.orion_arch_guard lookup --item <item-id> --range-before 2 --range-after 2
```

`index` verifies the AG-0 manifest before ingestion. A changed immutable or
architecture-critical source blocks indexing until `discover` records a new
reviewed manifest. Append-style Codex/runtime changes and Git working-state
changes are surfaced but may be deterministically reindexed.

To rebuild, close Guard readers and delete only the private `index.sqlite3`
file (plus its SQLite `-wal`/`-shm` sidecars if present), then run `index`.
Deleting this derived database never deletes L0. The Guard has no automated
command that deletes primary sources.

## Indexed structure

Schema version 1 provides `schema_metadata`, `source_snapshots`, `sources`,
`source_locations`, `snapshot_sources`, `source_items`, and `item_sources`.
Empty migration seams exist for future capability, decision, implementation,
mechanism, evidence, metric, relationship, run, and conflict graphs. AG-1 does
not populate those semantic tables.

AG-1 indexes:

- ChatGPT conversations and nodes/messages, including principal-chain versus
  alternative-branch structure, native IDs, chronology, hashes, and pointers;
- Codex rollout JSONL ordinals, native/correlation IDs where present, roles,
  timestamps, hashes, and pointers; coverage remains explicitly partial;
- Git `--all` commits, parents, authors, subjects, refs, changed paths, deleted
  paths, and explicit rename metadata without storing repository blobs;
- bounded Evidence ZIP identity, safe manifest metadata, event count, and
  entry names without extracting archives or ingesting audio;
- bounded release/runtime source metadata;
- Markdown sections and exact Decision Register rows, including D01-D73.

Stable native identity plus content hash prevents repeated exports and copied
archives from multiplying facts. `item_sources` retains multiple L0
provenances. Source snapshots preserve same-path content changes. Missing
sources remain recorded and are marked unavailable; relocated identical
sources gain a location instead of duplicate items.

## Source pointers and chronology

Pointers are JSON objects separate from previews. Depending on the source,
they include archive/file SHA, path, conversation/node/message ID, JSONL
ordinal, Git repository/commit/path, ZIP identity/internal metadata entry, or
document Git SHA/path/line/section/content hash.

Primitive lookup supports exact item/source/native ID, parent/children,
previous/next neighbor, bounded thread ranges, and Git path history. A preview
helps a human identify a candidate; it is never evidence and is never an item
identity.

## Privacy decision

AG-1 chooses **bounded preview only**. It stores exact native identities,
content SHA-256, safe structural metadata, and L0 pointers, but no full private
conversation body, arbitrary log body, Authorization header, credential, or
raw audio. Previews are whitespace-normalized, secret-redacted, and capped at
240 characters. The database is private and must never be committed or copied
into a release.

FTS5 is deliberately deferred: bounded previews are not authoritative enough
for meaningful full-text claims, while indexing full private bodies would
increase privacy exposure. Exact ID, chronology, hash, and source-pointer
queries avoid reparsing the 233 MB archive for ordinary anchored retrieval;
later stages may selectively open the exact L0 pointer for full context.

## Limitations and AG-2 boundary

AG-1 does not use semantic/vector retrieval and does not decide whether an
item is approved, superseded, better, or relevant to a capability. It does not
build Previous Best Solution, Architecture PASS/BLOCK, or product-behavior
rules. Alternative ChatGPT branches are retained but never silently promoted
to principal history.

The next stage is `AG-2 — CAPABILITY TAXONOMY +
DECISION/IMPLEMENTATION/MECHANISM GRAPH`. AG-2 may consume exact AG-1 pointers;
it must continue to validate candidate context against L0.
