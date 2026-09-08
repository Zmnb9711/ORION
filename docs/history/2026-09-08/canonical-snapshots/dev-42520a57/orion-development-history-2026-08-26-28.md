# ORION Intelligence, Presentation and Radio Development History — 2026-08-26/28

Status: **HISTORICAL RECONCILIATION OF IMPLEMENTED AND VALIDATED WORK**

This record reconstructs the IA-0 through Stage 6B.2 sequence from Git, the
canonical project memory, ADRs, stage documents and retained test/field
evidence. It does not change the current development position. The newer D74
`STRATEGY_A_CURRENT_RECONNECT` policy, current C3 checkpoint and next C4 field
proof recorded at repository HEAD remain authoritative.

## Authority and interpretation

- Current repository code and tests define implemented behavior.
- `docs/ORION_PROJECT_MEMORY.md`, the Master Architecture Checkpoint, Master
  Decision Register and accepted ADRs define durable intent and status.
- Field evidence is required for claims about provider behavior, SRS reception
  or audible output. Deterministic and frozen-build tests do not manufacture
  those claims.
- Historical `NOT STARTED` and `PENDING` statements below describe the moment
  at which they were written; later rows record their closure.
- Existing unrelated generated/release artifacts are not source-of-truth Git
  history and were not changed during this reconciliation.

## Architectural decisions recovered

### Intelligence ownership

Core owns routing policy, World Model authority, capabilities, tool execution,
deadlines, cancellation, replay, validation and operational truth. Qwen is a
replaceable planner/reasoner and language component. It cannot grant
capabilities, call DCS or domain owners directly, or turn an unsupported claim
into an authoritative fact.

The resulting controlled path is:

```text
InteractionRequest
  -> Core-owned InteractionRouter
  -> deterministic path or Planner
  -> Qwen through a provider adapter when required
  -> ToolGateway
  -> WorldModelFacade / existing authoritative owners
  -> validated SemanticResponse
```

### Communication and Phraseology ownership

The accepted mechanism is Hybrid D with the fail-closed Hybrid B policy
boundary:

- Core owns operational truth, protected values, priority, validation,
  critical operational wording and final deterministic composition.
- Qwen may understand free/mixed language, reason, recommend and supply an
  optional conversational or noncritical advisory envelope.
- Once Core renders a `ProtectedOperationalFragment`, it never returns to Qwen
  for rewriting, paraphrase or naturalization.
- Communication Profile, domain, input language, conversational language policy
  and operational language remain separate concepts. A profile may change
  presentation rules; it may not change facts, capabilities, permissions,
  freshness, tools or mission truth.

IA-6 established only the immutable seams. The later Pilot Phraseology and
Golden/Mixed probes proved the approach without claiming a complete normative
ICAO/FAA/NATO/FAP corpus.

### Provider, presentation and transport separation

The durable separation is:

```text
validated meaning
  -> communication / phraseology
  -> finalized presentation text
  -> Realtime voice or SpeechKit TTS
  -> finalized PCM
  -> RadioRouter
  -> RadioTransportAdapter
  -> SRS, or a future supported transport
```

Qwen and Yandex are not radio transports. SRS is not an AI provider and does
not own ATC/AWACS/JTAC/AAR semantics. AI provider and voice transport are
independently selected dimensions. Direct Audio remains independent; SRS is the
first field-proven operational radio transport. No DCS Native Voice API is
assumed to exist.

ADR-005 removed the legacy Whisper/ORION-Voice fallback after the Qwen proof.
ADR-006 later generalized the product to selectable Qwen/Yandex realtime
providers without forcing their different protocols through one audio engine.
ADR-007 froze the SRS 2.4.x protocol and provider/transport boundary.

The IA-1/IA-1.1 field work rejected Realtime-only presentation as the sole
renderer for critical aviation values. The accepted hybrid policy is Yandex
Realtime for conversational/noncritical speech and SpeechKit TTS for finalized
critical/radio speech. Later SpeechKit v3 streaming STT/TTS promotion and SRS
PTT work are recorded in `docs/orion-development-history-2026-09-02.md` and the
Master Architecture Checkpoint rather than duplicated here.

## Chronological implementation record

### 2026-08-26 — IA-0 provider-neutral interaction contracts

- Commit: `2d90e4f` (`feat: add provider-neutral interaction contracts`).
- Added immutable, serialization-safe `CapabilityId`, `InteractionRequest`,
  `RouteDecision` and `SemanticResponse` contracts.
- Separated authoritative facts, derived results, recommendations, assumptions,
  unavailable inputs and warnings; introduced `NATURALIZE` and `VERBATIM`
  presentation intent without binding the contracts to a provider or transport.
- Evidence at the checkpoint: 28 focused tests passed; Ruff, Pyright,
  compileall and `git diff --check` passed.
- Boundary: no World Model, ToolGateway, Planner, provider adapter, RadioContext
  or production routing was introduced.

### 2026-08-26 — IA-1 and IA-1.1 presentation decision

- IA-1 commit: `e1dc5a6` (`feat: probe yandex semantic presentation`).
- IA-1 proved the bounded `SemanticResponse -> Yandex presentation -> existing
  SRS` tunnel and conservative semantic checks. Initial validation reported 78
  focused and 1,259 full isolated tests passed, with static, privacy, packaging
  and offline frozen smokes passing.
- The initial field run showed that a successful Realtime transcript was not
  sufficient evidence of safe audible rendering for signs, units and other
  critical aviation values. Queue serialization and stale voice-acknowledgement
  defects also made parts of the first acoustic probe inconclusive.
- IA-1.1 was implemented through `bfa5443` and the documentation correction
  `00052a5`, then hardened by `8575f06`, `08ca767` and `293b627` for clear
  authorization errors, SpeechKit v1-compatible voices and bounded transient
  connection retries.
- Both A/B arms consumed the same finalized semantic phrase. Realtime output
  never became SpeechKit input. Each arm waited for matching SRS
  `tx_completed`, preventing probe-generated queue overflow or duplicate radio
  transmission.
- Final evidence `ORION-Test-Evidence-20260826-193719.zip` recorded 20/20 SRS
  transmissions, semantic PASS for all ten Realtime/SpeechKit pairs, 20 bounded
  synthetic WAV artifacts, human acoustic review CLEAR and no duplicate TX. A
  real first-attempt SpeechKit connection timeout recovered under the bounded
  retry policy without duplicate SRS admission.
- Decision: hybrid presentation approved; Realtime-only critical presentation
  rejected. SpeechKit synthesis remained downstream of finalized meaning and
  did not become a reasoning or domain component.

### 2026-08-26 — IA-2 World Model Query Facade

- Commit: `63448ed` (`Implement IA-2 world model query facade`).
- Added an immutable, provider-neutral, read-only facade over existing owners;
  it did not create a second telemetry or mission store.
- Facts preserve known/unknown/unavailable/stale/restricted status, source,
  authoritative/observed/derived classification, freshness, generation, units
  and bounded provenance. Mission truth is not relabelled as detected sensor
  knowledge.
- Data coverage and gaps were recorded explicitly. DCS control surfaces and
  general terrain queries remained gaps; Tacview remained reference evidence,
  never an ORION dependency.
- Evidence: 16 IA-2 tests, 77 relevant tests and 1,313 full isolated tests
  passed; branch coverage was 80.75%; Ruff, Pyright and compileall passed.
- Field classification: no new IA-2 flight was required because the stage was a
  deterministic read-only boundary over existing sources.

### 2026-08-27 — IA-3 Tool Gateway

- Commit: `913b8b8` (`Implement IA-3 tool gateway`).
- Added the sole Core-governed typed tool boundary with exact registration,
  schema, capability, permission, module, mission/freshness, confirmation,
  deadline, cancellation and idempotency checks.
- The initial catalog was read-only and delegated World Model reads to IA-2.
  Provider schemas and SRS concepts did not enter the Gateway.
- Evidence: 23 IA-3 tests, 150 relevant IA/mission/realtime/SRS tests and 1,336
  full isolated tests passed; branch coverage was 80.95%; static checks and
  offline frozen smokes passed.
- Field classification: not required; no live provider or action tool was part
  of the stage.

### 2026-08-27 — IA-4 PlannerProvider contract

- Commit: `7f37b4d` (`Implement IA-4 planner provider contract`).
- Added a provider-neutral short-lived Planner run and Core-owned task state
  machine. Bounded sequential and multi-call rounds execute only through IA-3;
  Core owns replay, deadlines, cancellation, cleanup and final acceptance.
- Authoritative output already required completed IA-3/IA-2 provenance. Exact
  value-to-ToolResult binding was identified as an IA-6 closure item.
- Evidence: 122 relevant tests and 1,363 full isolated tests passed; branch
  coverage was 81.09%; IA-4 module coverage was 85–88%; privacy, Ruff, Pyright,
  compileall and frozen build checks passed.
- Field classification: deterministic fake-provider proof was sufficient; no
  Yandex, Qwen, SRS, DCS or audio was invoked.

### 2026-08-27 — IA-5 Yandex Qwen planner adapter

- Commit: `a4f9942` (`feat(intelligence): implement IA-5 Yandex Qwen planner
  adapter`).
- Added the real Yandex AI Studio Responses adapter for Qwen3.6. Provider-safe
  function aliases map back to exact IA-3 names; provider output becomes IA-4
  events, never direct execution.
- Strict structured final output builds IA-0 `SemanticResponse`; IA-4 validates
  it. Core retains complete ToolResults while Qwen sees only bounded facts.
  Stored provider responses are deleted at terminal cleanup.
- Live Gates 1–4 proved authentication/model access, ordinary response, strict
  output, function calling, continuation IDs, usage and deletion. Gate 6 then
  completed `Qwen -> IA-4 -> one IA-3 ownship call -> IA-2 -> continuation ->
  IA-0` on synthetic state. A stochastic invalid semantic shape was rejected
  fail closed rather than repaired silently.
- Evidence: 22 IA-5 module tests and 1,382 full isolated tests passed with three
  unrelated environment-sensitive Setup Wizard tests deselected; IA-5 module
  coverage was 86.52%; Ruff, Pyright and compileall passed.
- Live classification: provider validated. DCS, external SRS and physical audio
  were not required for this provider/tool boundary.

### 2026-08-27 — PRE-IA-6 Launcher/Core lifecycle

- Commit: `b7800db` (`fix(lifecycle): stop launcher-owned Core on tray exit`).
- Window close hides to tray and preserves runtime. Explicit Exit stops only the
  Core created by that Launcher, proven by its live child handle plus an
  unlogged, non-persisted lifecycle token. PID files, process names, executable
  paths and ports do not establish ownership.
- Core uses bounded graceful Uvicorn shutdown; terminate/kill fallback is
  permitted only through the still-authoritative owned child handle. An
  already-running external Core is preserved.
- Evidence: 116 relevant tests and 1,394 full isolated tests passed; branch
  coverage was 81.26%; static, privacy and diff checks passed. Isolated ports
  prevented interference with the installed Core and canonical UDP 45100.
- Status: completed and field-proven as the retained Launcher/Core lifecycle
  contract.

### 2026-08-27 — IA-6 Interaction Router

- Commits: `f1a3e08` (`Implement IA-6 interaction router slice`) and `5c5c831`
  (`Stabilize IA-6 live semantic contract`).
- Added Core policy routing for an exact health path, one controlled ownship
  Planner request and typed unsupported results. Qwen does not decide whether
  Qwen is required.
- Closed exact fact binding: key, typed scalar value, unit, known status and
  authority must match a retained ToolResult leaf. Mutating heading `137` to
  `173`, duplicating a key or upgrading derived data to authoritative fails.
- Initial implementation evidence: 99 focused and 1,412 full isolated tests
  passed. Bounded provider runs reached one valid IA-3 call but were rejected
  for duplicate or wrongly classified facts, demonstrating fail-closed safety.
- A narrow instruction correction for this controlled slice left schemas,
  validators, permissions, retries and provider translation unchanged. The
  post-fix live gate accepted heading `137 deg`, latitude `42.1` and longitude
  `41.2`, with one tool call, no derived facts, both provider responses deleted
  and transport closed.
- Final evidence: 126 focused IA-0...IA-6 and 1,412 full isolated tests passed;
  branch coverage was 82%; Ruff, Pyright, compileall, diff and privacy/secret
  checks passed. Status: complete / live-provider validated.
- IA-6 also added the provider-neutral Communication/Phraseology contract seams
  described above, but no renderer, normative KB, radio transport, Launcher
  profile UI or domain migration.

### 2026-08-28 — Stage 6B.1 transport-neutral radio boundary

- Commit: `49f083d` (`Implement Stage 6B.1 radio router contracts`).
- Added immutable `RadioEntityRef`, resolved `RadioContext`, finalized bounded
  mono PCM16 audio and a provider-neutral `RadioTransportAdapter` contract.
- Added one Core-owned bounded semantic TX queue with
  `IMMEDIATE > URGENT > IMPORTANT > ROUTINE`, FIFO within priority, explicit
  transport selection, typed readiness/capability failures, replay protection,
  queued cancellation and bounded shutdown/diagnostics.
- The slice was deliberately unwired. It did not alter production SRS,
  RadioInfo, registration, Opus, pacing, PTT, Yandex, SpeechKit, Direct Audio,
  Launcher or domains. No active preemption was claimed.
- Evidence: 34 focused Stage 6B.1 tests, 62 final contract/router tests, 246
  relevant IA/SRS/Yandex/lifecycle/privacy tests and 1,446 full isolated tests
  passed; branch coverage was 82%; privacy/security regression was 121 passed;
  static and diff checks passed.
- Field classification: not required until a real adapter was connected.

### 2026-08-28 — Stage 6B.2 production SRS adapter

- Commit: `a955d7c` (`feat(radio): add production SRS transport adapter`).
- Added a thin `SrsRadioTransportAdapter` below the 6B.1 boundary. It retained
  the field-proven SRS 2.4.x connection, non-null canonical RadioInfo handshake,
  radio/UDP registration, 44.1-to-16 kHz conversion, Opus, packet construction,
  retransmit semantics, 40 ms pacing and established `tx_completed` ownership.
- The controlled production migration was the IA-1.1 Hybrid Presentation Probe
  finalized-PCM path. Ordinary Realtime output temporarily retained its legacy
  admission into the same SRS worker; no second SRS stack or domain migration
  was created.
- Generic readiness becomes `READY` only after the endpoint, server-echoed radio
  state and UDP registration are complete. Entity, coalition, frequency,
  modulation and PCM mismatches fail closed. Active per-transmission cancel is
  reported unsupported rather than simulated.
- Deterministic wire-equivalence proved legacy and routed PCM traverse the same
  resampler, encoder, packetizer, pacer and UDP send mechanics with equal frame
  and protocol fields. One semantic request produces one enqueue and one
  matching completion; replay does not transmit again.
- Implementation evidence: 73 focused 6B.1/6B.2/endpoint tests, 322 extended
  SRS/Yandex/IA/lifecycle tests and 1,478 full isolated tests passed; branch
  coverage was 82%; Ruff, Pyright, compileall, diff, secret/privacy and frozen
  package smokes passed.
- Field evidence: the bounded official-SRS gate completed 20/20 routed Hybrid
  Probe transmissions. Adapter start, existing SRS TX start, matching
  `tx_completed` and adapter completion correlated without loss or duplication,
  and reception was acoustically confirmed through the official SRS Client.
- Status: **CLOSED / FIELD VALIDATED**. The result proves SRS as the first
  adapter; it does not authorize Stage 6B.3, domain migration, DCS Native Voice,
  full Phraseology or broad Launcher work.

## Validation taxonomy retained

- **Deterministic/code validated:** contract, policy, failure, replay, privacy,
  lifecycle and wire-mechanics claims proven without external services.
- **Live-provider validated:** a real Yandex/Qwen call completed the exact
  bounded semantic/tool path; this does not imply DCS or radio field proof.
- **Field validated:** external SRS/provider/audio behavior was observed through
  the controlled product path and retained evidence, including human acoustic
  review where audibility was part of the claim.
- **Frozen/offline smoke:** packaged Core/Launcher ownership, imports and local
  loopback startup/shutdown were proven without claiming external audibility.

These evidence classes remain separate. A passing unit or wire-equivalence test
cannot replace official-SRS reception, and a successful provider HTTP response
cannot replace Core semantic validation.

## End-state at the close of Stage 6B.2

By commit `a955d7c`, the repository had a complete controlled chain from
provider-neutral interaction contracts through guarded planning and exact fact
binding to provider-neutral communication/radio contracts and the first thin,
field-validated SRS adapter. Production domain expansion, normative phraseology
coverage, broad radio ownership, active preemption and a future second radio
transport remained explicitly separate work.

This historical end-state is not the current roadmap checkpoint. Consult the
top of `docs/ORION_PROJECT_MEMORY.md` and the Master Architecture Checkpoint for
the newer canonical C3/C4 position before planning further implementation.
