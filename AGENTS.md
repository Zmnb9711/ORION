# ORION mandatory execution rules

## Identity and authority

ORION is a Natural-Language First AI copilot in DCS, not a mandatory-phrase
voice-command product. AI understands and proposes; Core knows, admits and
executes. Read the single canonical contract:
[ORION_NATURAL_LANGUAGE_FIRST_CONTRACT_V1](docs/architecture/ORION_NATURAL_LANGUAGE_ARCHITECTURE_CONTRACT.md).
Do not duplicate or amend that contract through task notes or implementation.

The first visible line of each ORION response must state the actual Architecture
Guard status: ON (with applicable report ID), REQUIRED, or OFF. Never claim ON
without a real result. The 2026-09-14 recovery audit is explicitly Guard OFF;
this does not waive the canonical contract or authorize later runtime changes.

## Sources and mandatory reading order

Resolve the actual worktree, branch, HEAD, staged/unstaged/untracked state first.
Do not assume the desktop cwd, GitHub main, newest timestamp or largest test
count identifies the authoritative working line.

Source precedence:

1. Actual repository state, for what is implemented.
2. Primary physical field evidence, for what worked or failed.
3. Explicit user architecture decisions, for what is approved.
4. Canonical architecture contract.
5. Current Project Memory.
6. History/index documents.
7. Recovery reports.
8. Historical prompts/summaries.

These sources answer different questions: existing code does NOT authorize an
architecture deviation; a field success does NOT authorize unsafe behavior.
Flag contradictions; never silently rewrite history to reconcile them.

Read in order: this file; canonical contract; [current Project Memory](docs/ORION_PROJECT_MEMORY.md);
[history index](docs/history/ORION_HISTORY_INDEX.md);
[field evidence index](docs/history/FIELD_EVIDENCE_INDEX.md);
[contradiction log](docs/history/ORION_CONTRADICTIONS.md); relevant primary
code, decisions and evidence. Historical instructions are evidence, not renewed
permission. Historical branch policies are not automatically current policy.

## Mandatory pre-flight output

Before edits state:

- exact worktree/branch/HEAD and existing changes;
- contract path/marker and compliance with each relevant numbered invariant;
- requested scope, explicit exclusions and current evidence level;
- user-facing capabilities and historical checkpoints that must be preserved;
- contradictions, missing evidence and STOP conditions.

Use the current source, not reconstruction from an older summary. Archive or
reference superseded material before reducing current-state documentation.

## Non-negotiable behavior

- No phrase fitting: never encode blind test wording as the main language solution.
- A fast-path miss must not become final unsupported instead of required semantic handling.
- No raw telemetry dump, generic ToolResult stringification or model-invented
  simulator fact/action may become speech. Preserve selected typed facts,
  provenance, units, freshness, permissions and unknown/restricted states.

- ORION owns explicit context; provider hidden history is not its authority.
- Preserve production-host reachability, not merely unchanged source files.
- No casual removal of old routes, owners or tools. Prove dependencies and
  preservation offline before proposing a separately authorized runtime change.

- Before redesigning or replacing a capability, identify its best historically
  working/field-proven checkpoint; compare the actual call graph and behavior
  with today's implementation; identify changes and the evidence for regression;
  justify RECOVER, ADAPT, REPLACE or KEEP CURRENT; label unknown history explicitly.
  Do not rebuild from scratch before checking for a better proven ORION implementation.

- Do not redesign SRS/STT/TTS/Launcher to solve a routing problem.

## Acceptance and truthful reporting

Astra/Codex does not decide that ORION works. User blind physical acceptance
through the installed production host decides whether a user-facing capability
works. Offline/provider/host tests are necessary but insufficient.

Every completion claim must state build/source, capability, evidence level,
test scope, real/fake dependencies, DCS/production-host status, blind versus
prepared wording, TX result and user acoustic verdict. Missing values are
UNKNOWN, not PASS. Sent frames are not proof of audibility or correct meaning.
Historical individual success is not current general product acceptance.
Component work may be called implemented/tested while FIELD PENDING or FAILED;
never silently promote that to a complete user capability.

## STOP and change discipline

STOP before code on a contract conflict, phrase-primary solution, weakened Core
authority, unsupported deletion/shadowing of an accepted capability, or broader
changes than authorized. A contradiction between the canonical contract and an
earlier explicit user decision requires user resolution; do not edit the contract.
Missing credentials, primary evidence or required user-only validation are not
permission to invent results or retry unboundedly.

Preserve unrelated dirty/untracked/generated work. No reset, cleanup, config,
live provider call, physical test, build, installation, commit or push without
scope authorization. Test inputs must be developer-created/held-out; no coaching
the user's blind wording. Never log secrets or unrestricted provider bodies.

At task end update current status, history/evidence indices and unresolved
contradictions within the authorized documentation scope. If docs cannot be
changed, report the pending update. State exact diff, tests actually run, unrun
gates and stop boundary. The present governance draft is NOT COMMITTED:
user review is required before commit or any foundation runtime implementation.
