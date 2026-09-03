# ORION Development Console Phase 3

## Canonical Roadmap integration

The derived Roadmap shows current Golden Components, historical reconnect
candidates, retirement history, U01–U20 recovered ideas, ten protected
user-value markers, and C0–C7 stages. Recovered ideas use a distinct purple
not-implemented class; test/experimental lineage remains cyan/blue, completed
proof green, and planned work gray. Current position is `CANONICAL ORION
BASELINE ESTABLISHED`; next is `REALTIME INFORMATIONAL PRESENTER RELIABILITY
CORRECTION`. Filters cover canonical context, historical reconnect, and
recovered ideas. Refresh remains derived/idempotent with no automatic save.

## Purpose and boundary

Phase 3 activates the existing Development Console `ROADMAP` section as a
maximum-detail graphical navigation layer over the real ORION development
history. It is read-only, derived and non-authoritative. It does not replace
AG-0/AG-1, the AG-2 graph, AG-3, durable Development History, Git, Evidence or
Phase 2 checkpoint/prompt storage.

The implementation is entirely under `tools/orion_development_console/`.
Production `orion/**`, Launcher/Core lifecycle, installer, packaging, DCS/SRS
integration, providers and audio paths are outside this phase.

The mandatory FULL preflight was
`AG-20260902-205236-989bb053-f5c4fa9-r1`: history `COMPLETE`, gate `PASS`, no
conflicts, no ownership drift and no user decision required. It selected the
D71 order `RECONNECT -> ADAPT -> EXTEND`: reuse the Guard index/graph, Phase 2
memory services and the Launcher-family Tk/ttk theme rather than introduce a
second history system or UI framework.

## Derived model

Stable typed nodes cover project, stages, subsystems, decisions,
implementations, refactors, tests, probes, field tests, failures, root causes,
fixes, retests, milestones, checkpoints, supersessions, rejections, removals,
disconnections, Guard events and explicitly approved planned work. Typed edges
retain Git parentage, Guard graph relationships, derived chronological stage
membership and failure/fix lineage.

The builder reads, without modifying:

- AG-0/AG-1 source items and fingerprints;
- AG-2 capabilities, decisions, implementations, mechanisms, Evidence and
  exact provenance;
- AG-3 runs and gates;
- all indexed Git branches and commits;
- the Master Decision Register, Master Architecture Checkpoint, Project Memory
  and Development History headings as current durable local inputs;
- bounded Evidence/release metadata;
- Phase 2 immutable checkpoints and prompt/recall services.

No chat message bodies, Codex response bodies, raw logs, raw audio, credentials
or provider reasoning enter a Roadmap snapshot. Conversation/session summary
nodes use only the bounded metadata already supplied by AG-1.

## Chronology, branches and proof

Nodes are ordered oldest to newest by their actual source time or durable
decision date. A recovered old source therefore enters its historical position,
not the bottom. Vertical progression is time; horizontal lanes distinguish
main development, test/experiment, historical alternatives, governance and
approved future work.

Branch identity is independent of result. Cyan/blue identifies a test or
experimental lineage, while node completion remains green only when the
node-specific proof gate is satisfied. Unfinished or insufficiently proven
nodes remain grey. Proof badges retain distinctions such as
`AUTOMATED_PROVEN`, `PROBE_PROVEN`, `FIELD_PROVEN`, `FAILED`, `SUPERSEDED`,
`REJECTED`, `REMOVED` and `DISCONNECTED`. Merely finding implementation code
does not make an implementation complete.

Guard implementation defect records deterministically yield bounded
failure/root-cause presentation nodes. When a later overlapping implementation
and linked Evidence exist, the Roadmap presents the supported
failure-to-fix-to-retest chain while retaining exact Guard provenance. This is
minimal presentation classification, not a second Guard graph.

## Refresh, freshness and no silent loss

`ОБНОВИТЬ` computes a dependency fingerprint from current HEAD, latest Guard,
AG graph signature, source snapshot, durable document hashes, latest Evidence
and latest checkpoint. It rebuilds the derived model, compares it with the
previous private snapshot and reports new/changed nodes, branches, proof
transitions, decisions, Evidence, checkpoints, recovered history, missing nodes
and unresolved items.

Missing prior nodes are never silently ignored: the differential classifies
them as `SOURCE_MISSING`, `SUPERSEDED`, `MERGED` or `RECLASSIFIED` where the
available metadata supports that status. The page permanently exposes
`CURRENT`, `STALE`, `REFRESH_REQUIRED`, `PARTIAL` or `ERROR`; changed
dependencies cannot remain silently `CURRENT`.

Snapshots are create-once private JSON under
`%LOCALAPPDATA%\ORION\development\console\roadmap\snapshots`. They support
change detection and stable layout only. They are not L0, checkpoints or
machine truth.

## UI and navigation

The existing Launcher-family Tk/ttk shell now hosts a custom Canvas tree with:

- `ОБНОВИТЬ`, `К ТЕКУЩЕЙ ТОЧКЕ`, `К НАЧАЛУ` and refresh differential;
- search across IDs, titles, capabilities, decisions, commits, Evidence,
  checkpoints, Guard reports, providers and mechanisms;
- filters for main, experimental, field-proven, failure/fix, unfinished,
  superseded/rejected, decision and checkpoint views;
- stage collapse/expand, stable selection and a visible current marker;
- compact proof cards plus lazy full node detail/provenance on selection;
- checkpoint nodes and `ВСПОМНИТЬ ЭТО` through the existing Phase 2 Task Recall
  path, with full preview and manual copy only;
- a simplified reliable vertical overview indicator using the native scrollbar
  and `visible / total` position instead of a fragile second minimap renderer.

The cached branch lanes and stable node IDs preserve layout order when history
is unchanged. Refresh retains selection and returns to the current position
when appropriate. Search/filter/collapse are presentation state only.

## Explicit future boundary

Only two future nodes are introduced by the explicitly approved Phase 3 task:

1. full Development Console checkpoint requiring explicit user SAVE;
2. low-latency natural informational presentation, which requires a new FULL
   Architecture Guard preflight before implementation.

No speculative later work is generated. Latency/Yandex implementation is not
resumed during Phase 3.
