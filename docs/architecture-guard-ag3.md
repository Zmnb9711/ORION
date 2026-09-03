# ORION Architecture Guard AG-3

## D74 canonical context extension

AG-3 reports include capability-filtered `canonical_context` without changing
AG-0/1/2/3 ownership. Current Best, Historical Best, Recovered Unimplemented
Ideas, DO NOT REINVENT rules, retirement conflicts, and canonical stages remain
distinct. Records reuse the AG-1 SQLite index and AG-2 capability graph.
`TRUE_GREENFIELD` appears only after all ordered layers are empty; retirement
conflicts require semantic restoration intent, not a keyword alone.

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

## Mandatory assistant response status (D73)

Every ChatGPT or Codex response about ORION must start on its first visible
line with exactly one of the following status forms:

- `ORION ARCHITECTURE GUARD: ON`
- `ORION ARCHITECTURE GUARD: REQUIRED`
- `ORION ARCHITECTURE GUARD: OFF`

`ON` means the response or task is grounded in an applicable, actual Guard
result. Because AG-3 report generation exists, an architecture-changing `ON`
must include its concrete report ID:
`ORION ARCHITECTURE GUARD: ON — AG-...`.

`REQUIRED` means the discussion has reached an architecture decision or change.
The Guard must run before the assistant recommends, approves, or implements
that architecture.

`OFF` means the Guard was not applied. It is permitted for non-architectural
ORION explanation, status, or chitchat only; under `OFF`, the assistant must not
recommend, approve, or assert a new ORION architecture decision.

The line is mandatory for every ORION response. Omission is a process
violation. This convention is effective immediately.

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

## Task intent and negated constraints

Ruleset 2 classifies each bounded task clause before scenario and ownership
rules run. The supported intent categories are:

- `PROPOSED_CHANGE`: positively adds, modifies, replaces or removes behavior;
- `REQUIRED_PRESERVATION`: requires an existing owner or mechanism to remain;
- `OUT_OF_SCOPE`: explicitly excludes a capability from the change;
- `PROHIBITED_ACTION`: forbids starting, modifying, rebuilding or replacing it;
- `OBSERVATION_ONLY`: permits bounded read, inspect, verify or report behavior;
- `CONTEXT_ONLY`: mentions surrounding architecture without changing it.

Capability mentions from every category remain visible in
`affected_capabilities` together with their classified intents. Only positive
`PROPOSED_CHANGE` clauses feed mutation scenarios, ownership-drift rules and
duplicate-field-proven-work rules. This prevents an instruction such as
`Do not modify SRS` from becoming a proposed SRS transport, while retaining the
constraint and its historical context.

Negation does not hide a separate positive proposal. For example,
`Replace radio transport, but do not change SRS` still identifies a radio
transport change and retains the existing field-proven RadioRouter/SRS/UDP7082
protection. Classification is deterministic clause/alias matching; it does not
use an LLM.

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

## Regression rules

Ruleset 1 covers the required Yandex/Qwen differential, UDP7082 versus packet
gap, superseded hard language modes, explicitly removed Whisper fallback,
protected Phraseology ownership, the rejected 20–30 production-KB
interpretation, manual callsign authority and duplicate SRS transport work.
It also includes a positive bounded-test case and incomplete-history fail-safe.

Ruleset 2 preserves those controls and adds exact negation/out-of-scope
regressions. Windows-launcher safety constraints, `Do not add Whisper`,
`Do not replace SpeechKit`, `Preserve Core-owned phraseology`, `Do not modify
UDP7082` and `Do not change Qwen` no longer imply mutation. Positive and mixed
controls continue to block a new or replacement radio transport and all other
protected regressions.

## Privacy and limitations

Task text is bounded and credential-redacted before persistence. Reports store
no raw conversation bodies, audio, credentials, provider reasoning or prompts.
Primary evidence is represented by exact local source IDs and pointers.

Capability expansion is deterministic alias/rule matching, not semantic vector
search. Ambiguous architecture-critical input therefore requires an explicit
capability or returns `USER_DECISION_REQUIRED`. AG-3 does not implement an
autonomous architecture recommender.
