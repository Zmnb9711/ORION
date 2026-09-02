# ORION Architecture Guard AG-3

AG-3 turns the private AG-0/AG-1 source index and AG-2 capability graph into a
deterministic architecture preflight. It is development tooling; it does not
change ORION runtime behavior and does not use an LLM or paid provider.

## Modes

- `FULL` covers provider, authority, ownership, state, lifecycle, routing,
  radio and transport architecture.
- `STANDARD` covers bounded implementation of an already-approved design.
- `LIGHT` covers local bug fixes, refactors and tests.

`STANDARD` and `LIGHT` escalate to `FULL` when the task changes a sensitive
capability or ownership boundary. A test-only change that explicitly preserves
architecture does not escalate merely because it names the tested mechanism.

## Gate semantics

- `PASS`: history is sufficient and no unresolved conflict exists.
- `BLOCK`: the task violates an explicit current decision, restores rejected
  or superseded behavior, replaces a protected field-proven mechanism without
  justification, or crosses a hard ownership/safety boundary.
- `USER_DECISION_REQUIRED`: more than one legitimate direction remains or the
  proposal changes an approved ownership choice that history cannot supersede.
- `INCOMPLETE_HISTORY`: architecture-critical L0 provenance is unavailable.

The Guard can retrieve, compare, warn, block and surface reuse. It cannot
supersede an explicit user decision or choose between legitimate product
directions.

## Historical and Previous Best checks

Capability aliases expand task text into AG-2 capability IDs. The Guard then
collects decisions, current/disconnected/historical/removed implementations,
mechanisms, ownership and evidence. D71 is applied to every resolved preflight.

Previous Best is qualitative. It preserves evidence boundaries and never
invents a numeric score. The selection order is:

`RECONNECT → ADAPT → EXTEND → REFACTOR → REPLACE`.

Whole implementations and reusable mechanisms are separate. This permits the
Guard to surface combinations such as historical persistent Realtime natural
presentation plus current Core fact validation/binding without silently
approving that architecture.

## Ownership drift

The first ruleset detects fact-authority, STT, presentation, protected wording,
session model, radio transport, physical PTT and EOU ownership changes. Drift
is reported independently from the final gate.

## Performance and evidence reuse

Performance metrics retain their exact boundary, statistic, sample count and
source pointer. Historical Realtime `response.created → first audio` is not
treated as directly equivalent to current Planner request-to-completion.

Advancing HEAD does not invalidate field evidence. The report identifies what
existing evidence still proves and names the new invariant, if any, requiring
new automated or field validation.

## CLI and reports

```powershell
python -m tools.orion_arch_guard preflight `
  --mode FULL `
  --task "Replace current formulation path ..." `
  --proposed-change "..." `
  --capability NATURAL_INFORMATIONAL_PRESENTATION
```

Use `--json` for machine-readable stdout and `--no-store` for a dry run.
Otherwise both Markdown and JSON are stored under:

`%LOCALAPPDATA%\ORION\development\architecture-guard\reports\`

Report IDs use:

`AG-YYYYMMDD-HHMMSS-<taskhash8>-<head7>-r<ruleset>`.

The JSON contains task/head/index identity, capabilities, history coverage,
decisions, implementations, Previous Best, mechanisms, ownership drift,
performance, evidence reuse, conflicts, gate and exact provenance pointers.
The logical signature excludes timestamp and report path, so identical
task/HEAD/index/rules produce the same logical result.

## Regression rules in ruleset 1

Ruleset 1 covers the required Yandex/Qwen differential, UDP7082 versus packet
gap, superseded hard language modes, explicitly removed Whisper fallback,
protected Phraseology ownership, the rejected 20–30 production-KB
interpretation, manual callsign authority and duplicate SRS transport work.
It also includes a positive bounded-test case and incomplete-history fail-safe.

## Privacy and limitations

Task text is bounded and credential-redacted before persistence. Reports store
no raw conversation bodies, audio, credentials, provider reasoning or prompts.
Primary evidence is represented by exact local source IDs and pointers.

Capability expansion is deterministic alias/rule matching, not semantic vector
search. Ambiguous architecture-critical input therefore requires an explicit
capability or returns `USER_DECISION_REQUIRED`. AG-3 does not implement an
autonomous architecture recommender.
