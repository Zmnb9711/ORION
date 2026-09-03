# ORION Development History — 2026-09-02

Status: **DAILY DEVELOPMENT / FIELD-EVIDENCE CHECKPOINT**

This document records the ORION work completed during the 2026-09-01/02 development session. It is a historical checkpoint, not a replacement for the authoritative Master Architecture Checkpoint or Master Decision Register.

## 1. Starting architectural context

The session began after the complete historical reconstruction and Master checkpoint update. The canonical architecture remained MODEL C:

- known pure operational contracts may bypass Qwen;
- free, mixed, ambiguous and complex requests may use Qwen/Planner;
- Core owns operational truth;
- protected operational wording is Core-owned;
- TTS/radio transport do not own semantics;
- Communication Profile infrastructure exists, but production normative content remains incomplete;
- bounded capability migration remains the required development method.

The Master historical checkpoint had already recovered 70 grouped decisions and established DO NOT REBUILD / ACTUALLY MISSING registers.

## 2. Communication Profile infrastructure checkpoint

Communication Profile pack infrastructure and Launcher UI were completed before the field work summarized here.

Implemented:

- ICAO / FAA_US / NATO_MILITARY / FAP_RUSSIAN_ATC profile IDs;
- local versioned pack store;
- schema/source-registry/pack version separation;
- ACTIVE / CANDIDATE / PREVIOUS_KNOWN_GOOD lifecycle;
- compatibility, hash and signature-verification seams;
- offline behavior;
- persisted profile selection;
- Launcher profile table;
- Check for Updates / Update / Details / Roll Back controls.

Important boundary preserved:

- profile selection may change communication rules/presentation only;
- profile selection may not change operational truth, ToolGateway permissions, provider selection, mission state or safety authority;
- separate operational Response Language selector is not part of the final architecture;
- FREE/conversational language remains FOLLOW_USER;
- operational language is profile/domain/pack governed.

Production normative profile entries remain incomplete.

## 3. Persistent ATC session + ATC_STATUS_QUERY implementation

Commit:

`6dea803e9deac09d0ed9e59d7b60cb6368a7a83e`

Subject:

`feat: persist ATC session for status queries`

Implemented one bounded MODEL C contract:

`ATC_STATUS_QUERY`

Semantic meaning:

`atc.current_flight_controller`

The new route reads only authoritative Core ATC state:

`VirtualAtcService.status(session_id).authority[FLIGHT_TRAFFIC]`

It does not infer the controller from wording, procedural-state text, frequency or Qwen.

Persistent ATC session binding is Core-owned and survives multiple PTT interactions inside the controlled Live Golden run.

Pure supported status forms bypass Qwen exactly like pure takeoff.

Expected Qwen calls:

- pure takeoff: `0`;
- pure ATC status query: `0`.

Status query is read-only and must not create or mutate ATC truth.

## 4. First Test B attempt exposed SRS TX-state stale failure

Evidence:

`ORION-Test-Evidence-20260901-185106.zip`

The test failed before the ATC semantic route.

Observed error:

`RuntimeError: SRS TX-state stream became stale during an active radio turn`

Forensic audit established:

- official SRS Client UDP7082 heartbeat had historically been approximately 200 ms;
- after an observed SRS disconnect/reconnect, current UDP7082 snapshots slowed to approximately 1.589–1.613 s;
- DCS simultaneously reported repeated `SAME MODEL TIME`;
- ORION still used a fixed 1.0-s TX-state freshness threshold;
- a packet-derived candidate was exposed to stale handling before authoritative `is_sending=true` arrived;
- the failure occurred before SpeechKit final/EOU semantic dispatch, persistent ATC proof and ATC_STATUS_QUERY;
- the new ATC code was not causal.

Historical recovery confirmed that UDP7082 remains the correct authoritative physical PTT source and `true→false` remains the sole authoritative EOU boundary.

The defect was in freshness/candidate timing assumptions, not in the ownership model.

## 5. UDP7082 cadence-aware liveness fix

Commit:

`5cc976a26b12be0520d560cda88ac47fbd1cda4b`

Subject:

`fix: adapt SRS TX-state liveness to sender cadence`

The transport patch changed only the SRS TX-state/candidate implementation and its tests. ATC, Qwen, InteractionRouter, WorldModel, ToolGateway, Phraseology, Communication Profiles, RadioRouter and SpeechKit protocol were not changed.

The linked fixed 1-second assumptions were replaced by one bounded cadence-aware contract covering:

- TX-state stream freshness;
- packet-candidate confirmation;
- candidate PCM retention horizon.

Estimator:

- last eight valid UDP7082 inter-arrival intervals;
- monotonic time;
- repeated same-state snapshots count;
- malformed packets/audio/TCP/provider events do not count.

Formula:

`budget = min(5.0 s, max(1.0 s, 3 × max(last 8 valid intervals)))`

Examples:

- 0.20-s heartbeat → 1.0-s budget;
- 1.60-s heartbeat → 4.8-s budget;
- hard maximum → 5.0 s.

Bootstrap before a valid cadence interval uses a bounded 5.0-s budget.

Candidate PCM retention was expanded to match the bounded confirmation horizon while remaining bounded.

Critical invariants preserved:

- UDP7082 remains authoritative physical PTT state;
- only `true→false` creates authoritative EOU;
- packet-gap EOU remains forbidden;
- provider VAD does not own physical PTT end;
- STT settle heuristics are not restored;
- audio packets do not reset authoritative TX-state freshness;
- confirmed active turns still fail closed if the heartbeat genuinely disappears.

Automated validation reported:

- focused: 44 passed;
- relevant regressions: 294 passed;
- full isolated repository suite: 1730 passed;
- Ruff PASS;
- Pyright 0 errors / 0 warnings;
- compileall PASS;
- privacy/secret scan PASS.

## 6. Physical Test A — long PTT transport/STT gate

Evidence:

`ORION-Test-Evidence-20260901-201622.zip`

This test intentionally exercised the transport/STT path without requiring Live Golden semantic response generation.

Field result:

**PASS for UDP7082 long-PTT + SpeechKit STT robustness.**

Observed chain:

`physical SRS PTT → UDP7082 authoritative true → repeated true snapshots → voice PCM → authoritative false → exactly one SpeechKit EOU → exactly one STT final`

The physical turn lasted approximately 9.6 seconds by TX-state timing, well beyond the old 1-second stale threshold.

The recognized user transcript was:

`хорошая погода как твои дела скажи пожалуйста`

No ORION voice answer was expected from this transport-only Test A because Live Golden semantic response generation was not active. The absence of an assistant response was therefore not a TTS/SRS failure.

The cadence-aware fix survived the long physical turn without the previous stale/session error.

## 7. First persistent-ATC Test B attempt — review-gate mismatch

Evidence:

`ORION-Test-Evidence-20260901-203039.zip`

PTT #1:

- transcript: `разрешите взлет`;
- deterministic known-contract route;
- Qwen calls: 0;
- takeoff response generated and transmitted successfully;
- persistent ATC session created/bound.

PTT #2 and PTT #3:

- both physical SRS turns completed;
- both had authoritative UDP7082 true→false;
- both produced SpeechKit EOU and final transcript;
- both correctly recognized `какой диспетчер сейчас управляет моим полетом`;
- neither reached semantic dispatch.

Root cause was not transport, STT, ATC_STATUS_QUERY, InteractionRouter or Qwen.

Live Golden had moved after case #1 from `PROCESSING` to `AWAITING_REVIEW`.

The next corpus case is activated only after the user records the required acoustic review with `RECORD CASE REVIEW`.

While state was not `WAITING_INPUT`, `accept_transcript()` returned false. The finalized utterances were therefore deliberately not admitted to semantic processing.

This exposed a mismatch between the new two-PTT field-test instructions and the pre-existing Live Golden human-review gate.

No production fix was required.

Correct procedure:

1. PTT #1;
2. hear response;
3. review case #1;
4. `RECORD CASE REVIEW`;
5. wait for case #2 / WAITING_INPUT;
6. PTT #2;
7. hear response;
8. review case #2.

Historical audit confirmed that persistent multi-PTT STT had been proven previously, but automatic multiple semantic cases without the Live Golden review step had not been field-proven.

## 8. Successful persistent multi-turn ATC field test

Evidence:

`ORION-Test-Evidence-20260901-221642.zip`

Important test condition:

**DCS was NOT running.**

The test therefore proves the Core/SRS/STT/MODEL-C/persistent-ATC-session chain independently of live DCS truth.

The corrected Live Golden review procedure was followed.

PTT #1:

`Разрешите взлёт.`

Result:

- deterministic MODEL C route;
- Qwen calls: 0;
- takeoff clearance produced;
- TTS → RadioRouter → SRS completed;
- audible ATC response generated.

PTT #2:

`Какой диспетчер сейчас управляет моим полётом?`

Result:

- deterministic MODEL C route;
- Qwen calls: 0;
- status query read the same persistent ATC session;
- TTS → RadioRouter → SRS completed;
- audible diagnostic status response generated.

Persistent ATC session ID observed for both turns:

`a4fd60d8-3f07-4051-9214-93dd2c06cb00`

Status truth:

- authority scope queried: `FLIGHT_TRAFFIC`;
- controller: `airport_tower`;
- procedural phase: `takeoff_cleared`;
- facility: `Golden Tower`;
- status query revision remained `2 → 2`, preserving the read-only invariant.

Run completed with both cases PASS and separate response audio artifacts.

### Correct field claim

**PERSISTENT MULTI-TURN CORE ATC SESSION OVER PHYSICAL SRS — FIELD PROVEN.**

Specifically proven:

`human → official SRS → UDP7082/SpeechKit STT → MODEL C → persistent Core ATC session → deterministic ATC interaction #1 → review gate → deterministic ATC interaction #2 → SpeechKit TTS → RadioRouter/SRS`

with:

`Qwen = 0 + 0`

### Claim explicitly NOT proven

**DCS-INTEGRATED VIRTUAL ATC is NOT yet field-proven by this test.**

Because DCS was not running, the following were controlled fixture/session truth rather than live DCS truth:

- Viper 2-1 identity;
- Golden Tower;
- runway 07/25;
- Tower authority initialization;
- takeoff_cleared procedural state.

This distinction must be preserved in future documentation and claims.

## 9. SRS channel switching observation

During the session an SRS channel-switching issue was observed and compared with previous behavior. It later resumed working and was not a blocker for the successful persistent-ATC field test.

No production change was made for this observation in this checkpoint.

## 10. Current field-proven boundary after this session

The following are now separately supported by field evidence:

1. Production SRS transport and adapter.
2. UDP7082 authoritative physical PTT ownership.
3. SpeechKit v3 External EOU.
4. Persistent multi-PTT SpeechKit session.
5. Cadence-aware UDP7082 robustness across long physical PTT.
6. SpeechKit streaming TTS → RadioRouter/SRS.
7. Pure takeoff MODEL C direct route with zero Qwen calls.
8. Persistent multi-turn Core ATC session across two physical SRS interactions.
9. ATC_STATUS_QUERY direct route with zero Qwen calls.
10. Read-only ATC status lookup from `FLIGHT_TRAFFIC` authority in the same persistent Core session.

Not yet field-proven as a complete product:

- live DCS truth bound to the persistent ATC session;
- real DCS aircraft/session identity in this two-turn proof;
- real aerodrome/facility resolution;
- TAKEOFF_ROLL / AIRBORNE detection;
- Tower → Departure handoff;
- authoritative Departure frequency;
- proactive ATC publisher;
- full Virtual ATC lifecycle;
- persistent RadioEntity → VoiceProfile mapping;
- populated verified normative Communication Profile packs.

## 11. Next recommended bounded implementation

The next recommended vertical is:

**LIVE DCS FLIGHTCONTEXT → PERSISTENT ATC SESSION BINDING + AIRCRAFT IDENTITY MODEL C VERTICAL**

Purpose:

replace controlled identity/context with real DCS FlightContext truth without yet implementing AIRBORNE, handoff or facility-frequency authority.

Preferred first read-only live-DCS contract:

`В каком самолёте я нахожусь?`

Expected route:

`DCS → Flight Bridge / FlightContext → Core/WorldModel → deterministic MODEL C aircraft-identity query → semantic response → SpeechKit TTS → SRS`

The response must use observable DCS truth and provenance, not Qwen inference or fixture data.

After that proof, migrate the persistent takeoff session from controlled fixture identity toward live DCS binding, then add authoritative TAKEOFF_ROLL/AIRBORNE and only afterwards Tower → Departure.

## 12. DO NOT REBUILD / DO NOT REGRESS

Future work must preserve:

- MODEL C routing boundary;
- zero-Qwen direct route for safely recognized pure contracts;
- Core-owned operational truth;
- persistent ATC session work from `6dea803`;
- cadence-aware UDP7082 liveness from `5cc976a`;
- UDP7082 true→false as sole authoritative physical EOU;
- SpeechKit persistent multi-PTT;
- streaming TTS;
- RadioRouter/SRS;
- Live Golden review semantics while it remains an experimental evidence harness;
- Communication Profile infrastructure;
- Test Evidence and privacy/build identity controls.

Do not interpret the successful no-DCS Test B as proof of DCS-integrated ATC.

## 13. End-of-session status

Current implementation baseline after today's code work:

`5cc976a26b12be0520d560cda88ac47fbd1cda4b`

Major new field result:

`PERSISTENT MULTI-TURN CORE ATC SESSION OVER PHYSICAL SRS — FIELD PROVEN`

DCS in final successful Test B:

`NOT RUNNING`

DCS-integrated Virtual ATC:

`NOT YET FIELD PROVEN`

Recommended next family:

`LIVE DCS CONTEXT / ATC SESSION BINDING`

Recommended first contract:

`AIRCRAFT_IDENTITY_QUERY`

Recommended subsequent progression:

`live DCS identity/context → live-bound persistent ATC session → TAKEOFF_ROLL/AIRBORNE → Tower→Departure → broader ATC lifecycle`

## 14. Aircraft identity implementation checkpoint and Stage 6A ownership correction

The bounded `AIRCRAFT_IDENTITY_QUERY` implementation preserves the field-proven
Stage 6A / 6A.1 ownership split established by `f5c5d474` and stabilized by
`5896c4d9`:

- live DCS telemetry reaches `WorldModelFacade` through the existing telemetry path;
- Core accepts only `KNOWN`, `DCS_EXPORT`, `AUTHORITATIVE` aircraft identity;
- Core and World Model exclusively own the raw identity, normalization,
  freshness, provenance, and unavailable state;
- Qwen performs one informational natural-language formulation step, but receives
  no tool capability and has no fact authority;
- Qwen may return only a bounded sentence shell containing one Core substitution
  marker; Core rejects added aircraft identifiers, extra numeric facts, provider
  facts, guesses, defaults, or the wrong availability state;
- Core substitutes its exact aircraft display identity only after validation and
  preserves the typed source fact in the final semantic response;
- stale, disconnected, no-player, invalid, non-DCS, or non-authoritative identity
  fails closed without fixture or previous-session fallback.

This informational contract therefore does **not** use `Qwen = 0` as its success
criterion. Its criterion is `Core fact authority + Qwen natural formulation +
Core exact-fact binding`. The existing zero-Qwen behavior remains unchanged for
pure protected takeoff and the existing ATC status contract. Phraseology/OSU,
ToolGateway permissions, ATC session state, RadioRouter, SpeechKit and SRS
ownership boundaries are unchanged.

The implementation is not field-proven until a separate live-DCS, physical-SRS
test confirms that the spoken aircraft identity exactly matches fresh Core truth.

## 15. Architecture Guard AG-0 source-discovery foundation

The user approved the Previous Best Solution Gate as durable decision D71.
Before an architecture implementation, ORION development must search prior
approved decisions, historical and current implementations, field-proven
solutions and reusable mechanisms. The preferred progression is `RECONNECT →
ADAPT → EXTEND → REFACTOR → REPLACE`; absence from current HEAD alone does not
prove that a capability is historically missing.

The companion informational-UX constraint is recorded as D72: ordinary
informational answers should remain naturally AI-formulated. Canned/template
phrases are not the normal informational UX. This does not alter the existing
Core-owned protected operational phraseology boundary.

AG-0 adds repository-local development tooling under
`tools/orion_arch_guard/`. It discovers and fingerprints configurable L0/L1/L2
navigation sources and writes a private JSON manifest below the user's local
ORION development-data directory. Primary ChatGPT/Codex archives, Evidence,
runtime logs and release trees remain read-only and outside Git.

AG-0 deliberately does not implement SQLite/FTS, semantic retrieval,
capability/decision ingestion, Previous Best comparisons or Architecture Gate
rules. Those begin with AG-1 and later stages.

## 16. Architecture Guard AG-1 structured history index

AG-1 adds a private SQLite index at
`%LOCALAPPDATA%\ORION\development\architecture-guard\index.sqlite3`. It reuses
AG-0 source identities and fingerprints, preserves source snapshots and
multiple locations, and creates deterministic addressable items for ChatGPT
conversation trees, Codex JSONL, Git `--all`, bounded Evidence/release/runtime
metadata, project-document sections, and Decision Register rows D01-D73.

The index is derived and non-authoritative. L0 sources remain read-only; every
item carries an exact structured L0 pointer. Private text uses only a bounded,
redacted preview plus a content hash. Full bodies, raw logs, Authorization
headers, credentials, and audio are not stored. FTS5 and all semantic/vector,
capability, Previous Best, and PASS/BLOCK behavior remain deferred.

AG-1 is limited to exact source identity, chronology, parent/child and
neighbor/range retrieval. The next stage is `AG-2 — CAPABILITY TAXONOMY +
DECISION/IMPLEMENTATION/MECHANISM GRAPH`.

## 17. Architecture Guard AG-2 capability graph

AG-2 extends the private AG-1 SQLite database with a deterministic taxonomy and
typed decision/implementation/mechanism/evidence graph. Stable capability IDs
remain independent of providers and code symbols; aliases and historical terms
connect renamed or rearchitected behavior without claiming that implementations
are identical.

All D01-D73 rows are imported exactly from their AG-1 document pointers.
Historically significant implementations and reusable mechanisms retain
separate runtime, historical and field/probe states, abandonment classification,
confidence and exact L0 provenance. Ownership assignments explicitly distinguish
Core fact authority, natural informational wording, protected operational
wording, tool permission, STT/TTS, radio/PTT/EOU and persistent state.

Mandatory graph proofs cover Stage 6A versus current aircraft information,
UDP7082/PTT/EOU evolution, language and Communication Profiles, Whisper removal
and SpeechKit STT, Pilot Phraseology `TEST_CORPUS_ONLY`, protected OSU wording,
and pure-takeoff/persistent-ATC/status-query evolution. These are retrieval
facts only: AG-2 does not select Qwen or Yandex Realtime as better, and it does
not produce Architecture PASS/BLOCK.

The next stage is `AG-3 — HISTORICAL DECISION CHECK + PREVIOUS BEST SOLUTION
GATE`.

## 18. Architecture Guard AG-3 operational preflight checkpoint

AG-3 implements the first deterministic Architecture Guard preflight over the
existing AG-0/AG-1 index and AG-2 capability graph. It adds FULL, STANDARD and
LIGHT modes with automatic escalation for authority, ownership, session,
provider, routing and radio/EOU changes.

The preflight performs Historical Decision, Existing Solution, Previous Best,
hybrid-reuse, ownership-drift, performance-boundary and evidence-reuse checks.
Its outcomes are `PASS`, `BLOCK`, `USER_DECISION_REQUIRED` and
`INCOMPLETE_HISTORY`. D71 is mandatory for every resolved task; D72 protects
natural informational formulation while retaining Core ownership of protected
operational wording.

Reports are written only to the private local Architecture Guard directory in
both Markdown and JSON. Exact L0 pointers are retained without copying private
conversation bodies or audio into Git. Same task, HEAD, index and ruleset yield
the same logical signature.

The first real FULL preflight covers the pending low-latency natural
informational formulation task. It surfaces historical persistent Yandex
Realtime, the current Qwen formulation, current Core fact binding and their
different performance boundaries. Because presentation/session ownership has
more than one legitimate direction, implementation remains stopped pending the
reported architecture gate.

## 19. Mandatory visible Architecture Guard status decision

The user explicitly approved D73 as a durable ChatGPT/Codex process rule. Every
assistant response about ORION must begin with a visible first-line Architecture
Guard status: `ON`, `REQUIRED`, or `OFF`.

`ON` requires an applicable, actual Guard result. For architecture-changing
work, AG-3 report generation makes the concrete `AG-...` report ID mandatory on
the status line. `REQUIRED` stops architecture recommendation, approval, or
implementation until the Guard runs. `OFF` remains valid for non-architectural
ORION explanation, status, or chitchat, but cannot accompany a recommendation,
approval, or assertion of a new ORION architecture decision. Omitting the line
is itself a process violation.

The convention is effective immediately. Its documentation-only preflight ran
at starting HEAD `8c406fea09658afdee105bd7b72b444d1c66f883` in FULL mode with
report `AG-20260902-185339-f70f7a7f-8c406fe-r1`, complete history coverage and
gate `PASS`. This checkpoint changes no production ORION runtime behavior.

## 20. Development Console Phase 1 local environment verification

The user approved the bounded Development Console architecture through FULL
preflight `AG-20260902-191448-5aaeb475-1d4e0cb-r1`. Phase 1 implements a
separate development application under `tools/orion_development_console/`; it
is not imported by `orion/**`, is not a Launcher mode, and is absent from the
product installer and frozen runtime.

The vertical adds typed historical/development/machine truth domains,
`VerificationObservation`, independent installed/configured/running/ready
facts, bounded read-only collectors, fingerprint invalidation and aging, a
private `OV-...` report store, and a permanent Tk/ttk panel for Git, History,
Logs, Evidence, Installed ORION, Local ORION Data, DCS Integration and SRS.
The visible `ПРОВЕРИТЬ ВСЁ` action does not fetch, launch ORION/DCS/SRS, open
audio, call providers, repair files, install updates or elevate. Cached Git
upstream is explicitly labelled as a local tracking ref rather than a live
remote result.

The first real local verification produced
`OV-20260902-193603-1d4e0cb-2d21d8b7`. It verified branch
`dev/adr004-post-389` at `1d4e0cbc299c8e2dd3db041bec10099b6172f68c`,
73 decisions, 42 ChatGPT conversations, 14 Codex sessions, 347 bounded logs
and 73 Evidence archives. Installed ORION `0.2.0-alpha` Core/Launcher build
`27e94bdbf843a3f1895db2756eed49e42fe07989` was independently recovered from
`C:\Program Files\ORION` and correctly reported `DIFFERENT` from repository
HEAD while matching the latest known local release. DCS integration payload
matched the expected hash. SRS installation/configuration and passive running
state were observed, while SRS version and all live DCS/SRS/provider/audio
readiness remained explicitly `UNKNOWN` or `NOT_CHECKED` rather than inferred.

Deterministic Phase 1 tests cover Git/cached-upstream state, Guard/D73/index,
log and Evidence deltas, installed-build comparison, missing roots without
creation, DCS configured-versus-ready separation, SRS passive state/access
denial, staleness, forbidden side effects, report privacy and UI mapping. The
focused suite passed 22 tests; all 47 AG-0/1/2/3 regression tests also passed.
Ruff, focused Pyright, compileall, whitespace and credential-pattern checks
passed. Repository-wide Pyright continues to expose its pre-existing baseline
outside this Phase 1 scope and was not suppressed or modified.

The FULL post-implementation Guard report is
`AG-20260902-194514-16892632-1d4e0cb-r1`: history coverage `COMPLETE`, gate
`PASS`, no conflict, no ownership drift and no user decision required. The next
approved Console scope is Phase 2: visible Full/Task Recall, immutable
checkpoint history and previewable prompt generation; direct sending and the
graphical roadmap remain deferred.

The final closure re-check after separating the required architecture preflight
from the newest Guard status is `AG-20260902-194731-34d60d89-438577b-r1`:
FULL, `COMPLETE`, `PASS`, with zero conflicts, zero ownership drift and no user
decision required. The final stable-invalidation check is
`AG-20260902-194939-32e286b9-0267a75-r1`, also FULL / `COMPLETE` / `PASS`
with zero conflicts, zero ownership drift and no user decision required; it
confirms that transient SQLite sidecars cannot make verification invalidate
itself while the dedicated History signature remains authoritative for Guard
index changes.

## 21. Development Console Phase 2 development memory and visible prompts

Phase 2 adds a private, local development-memory layer to the separate
Development Console. The approved architecture was grounded before
implementation by FULL report `AG-20260902-195734-840e21f7-c8aa825-r1` at
starting HEAD `c8aa8253520e22fe0e514bad041b1f4bcfabd15a`; its history coverage
was `COMPLETE`, its gate was `PASS`, and it required no user decision.

Typed, create-once `DevelopmentCheckpoint` and `PromptRecord` documents now
live only under `%LOCALAPPDATA%\ORION\development\console`. They carry bounded
source references and fingerprints, while a rebuildable index is explicitly
non-authoritative. Checkpoint history can compare two records semantically and
surface stage, decision, proof, known-problem, next-step and Git transitions
without treating a changed HEAD alone as a meaningful development change.

The Console now visibly generates complete `FULL_RECALL`, `TASK_RECALL`,
`CONTINUE` and `CHECKPOINT_RECOVERY` prompts. Task Recall runs an actual
Architecture Guard check and embeds its concrete report identity. Prompt text
is previewed in full, copied or exported only by explicit user action, and
retained in private prompt history; direct external sending remains disabled.
The Launcher-family UI adds Overview, History, Guard, Evidence, System and
Future Roadmap views while preserving the Phase 1 verification truth domains.
The roadmap remains deliberately informational: the graphical live roadmap is
the Phase 3 boundary.

The real self-check retained checkpoint `CP-20260902-202904-12498c06`, prompt
records including `PR-20260902-203609-631300b5`, Task Recall Guard report
`AG-20260902-203609-574d1867-c8aa825-r1`, and verification report
`OV-20260902-203950-c8aa825-19eac74a`. It reopened the private checkpoint in
the UI, exercised semantic history comparison and visible recall/continuation
prompts, and confirmed that direct send is unavailable. No product ORION, DCS,
SRS, microphone, audio or provider process was launched, and no network access
was performed.

The Phase 2 focused suite passed 23 tests and the Phase 1 regression suite
passed 24 tests; all 47 AG-0/1/2/3 regression tests also passed. Scoped Ruff,
Pyright, compileall, whitespace and privacy/credential checks passed. The FULL
post-implementation report is
`AG-20260902-204116-b0698a28-c8aa825-r1`: history coverage `COMPLETE`, gate
`PASS`, zero conflicts, zero ownership drift and no user decision required.
Phase 2 changes only development tooling, tests and documentation; production
ORION runtime, product packaging and installer behavior remain unchanged.

## 22. Development Console Phase 3 maximum-detail live Roadmap

Phase 3 activates the existing Roadmap section as a maximum-detail, vertically
scrollable development tree. Its implementation was grounded before editing by
FULL report `AG-20260902-205236-989bb053-f5c4fa9-r1` at starting HEAD
`f5c4fa95d06b66101519a74c1e3b17b8a58f4816`: history coverage `COMPLETE`, gate
`PASS`, zero conflicts, zero ownership drift and no user decision required.

The Roadmap is a read-only, non-authoritative projection over the existing
Architecture Guard SQLite index, Git/history metadata, current durable document
headings, Guard reports, Phase 2 checkpoints and prompt metadata. It creates no
second historical index or Guard graph. Stable source-backed node IDs,
oldest-to-newest ordering, deterministic stage/subsystem grouping, main/test/
alternative/governance/future branches, proof-gated completion, exact bounded
provenance, no-silent-loss classification and private immutable `RM-...`
snapshots support refresh differential, freshness, search, filters, collapse,
selection preservation and Task Recall without elevating Roadmap state to L0.

The first actual Roadmap self-check represented 2,552 nodes and 4,621 edges:
31 stages, 74 subsystems, 74 decisions, 1,099 implementations, 371 tests/probes,
93 field tests, 262 failure/root-cause/fix records, 45 field-proven records, 50
superseded/rejected/removed/disconnected records, 15 Guard events, one saved
checkpoint and two explicitly approved future nodes. A second unchanged refresh
kept stable logical identities and chronology with zero new, changed, missing or
recovered nodes. Typical build time was 0.97-0.99 seconds; the full private
snapshot reconciliation/write path took 1.8-3.0 seconds in this environment.
Search remained interactive, and measured Python memory settled near 19 MiB
after peak work dominated by snapshot serialization.

The real Tk/ttk UI self-check verified Launcher-family styling, oldest-at-top
chronology, the current marker and jump, normal scrolling, exact D71 search and
detail provenance, green/grey proof semantics, distinct cyan test branches,
collapse from 2,552 to 108 visible nodes, unchanged refresh remaining `CURRENT`,
and an empty visible differential. Roadmap Task Recall created private prompt
`PR-20260902-211715-f4c8f83f` through Guard report
`AG-20260902-211715-b9f3dc81-f5c4fa9-r1`; it was not sent anywhere. The compact
overview is intentionally a reliable simplified history indicator rather than
a fragile full minimap, and the detail surface loads provenance only for the
selected node to keep the large tree usable.

Focused Phase 3 tests passed 35 cases; Phase 2 passed 23, Phase 1 passed 24, and
all 47 AG-0/1/2/3 regression tests passed. Scoped Ruff, Pyright, compileall,
whitespace, SQLite integrity and privacy/credential checks passed. The FULL
post-implementation report is
`AG-20260902-212254-a7f6207a-f5c4fa9-r1`: history coverage `COMPLETE`, gate
`PASS`, zero conflicts, zero ownership drift and no user decision required.
No production runtime, Architecture Guard implementation, Launcher/Core,
installer or packaging file changed; DCS, SRS, providers and microphone were
not started.

Final checkpoint candidate `CP-20260902-212012-5b2246d7` is prepared in memory
and `READY_FOR_USER_SAVE`; it was deliberately not persisted because checkpoint
save requires explicit user confirmation. The next approved development step is
`LOW-LATENCY NATURAL INFORMATIONAL PRESENTATION`, preceded by a new FULL
Architecture Guard preflight using the completed Console and the final saved
checkpoint as current development context.

## 23. Architecture Guard ruleset 2 negated-constraint intent fix

The first FULL preflight for the dev-only Development Console Windows entry
point produced false-positive report
`AG-20260902-213455-67e26cbd-c493563-r1`. Although the task prohibited SRS and
production-radio changes, ruleset 1 flattened every task field and constraint
into one normalized string. It therefore combined `SRS` from `do not start ...
SRS` with the unrelated word `rebuild` from `without frozen-executable rebuild
churn`, activated `rebuild_srs`, and incorrectly emitted both
`RADIO_TRANSPORT_CHANGED` and `DUPLICATE_FIELD_PROVEN_RADIO_STACK`.

The Guard-only correction was approved through FULL report
`AG-20260902-213733-536e3415-c493563-r1`, with `COMPLETE` history, gate `PASS`,
zero conflicts and zero ownership drift. Ruleset 2 now classifies bounded task
clauses as `PROPOSED_CHANGE`, `REQUIRED_PRESERVATION`, `OUT_OF_SCOPE`,
`PROHIBITED_ACTION`, `OBSERVATION_ONLY` or `CONTEXT_ONLY`. All capability
mentions remain visible as constraints/context, but only positive proposed
change clauses feed mutation scenarios, ownership drift and duplicate-work
rules. A separate positive radio-transport proposal still wins over a negated
SRS clause and remains blocked.

The exact Windows-entry semantics were rerun without weakening their safety
constraints as `AG-20260902-214733-67e26cbd-c493563-r2`. The result was FULL /
`COMPLETE` / `PASS`, zero conflicts and zero ownership drift; SRS was retained
as `PROHIBITED_ACTION` with `proposed_change=false`. A real-history positive
control for a new SRS transport remained `BLOCK` with the original duplicate
field-proven-radio-stack conflict and radio-transport ownership drift.

Focused regressions cover the original failure, the positive SRS control, a
mixed positive-radio/negated-SRS proposal, and corresponding Whisper,
SpeechKit, Phraseology, UDP7082 and Qwen negations. This task changes only the
Architecture Guard, its focused tests and Guard/development documentation. The
Development Console, production ORION, Launcher, SRS, RadioRouter, DCS,
providers, installer and packaging remain unchanged. The Windows launcher is
deliberately not implemented in this bugfix task.

## 24. Development Console Windows launch entry

The bounded implementation was approved by FULL preflight
`AG-20260902-214845-6986cd50-e8e13e6-r2` at starting HEAD
`e8e13e6c7de8479f562761661824aed91aad60b9`: history coverage `COMPLETE`, gate
`PASS`, zero conflicts, zero ownership drift and no user decision required.

The existing Development Console now has a normal repository-current Windows
entry without a frozen executable or packaging framework. The Desktop shortcut
`C:\Users\Алексей\Desktop\ORION Development Console.lnk` targets the existing
checkout `.venv\Scripts\pythonw.exe`, passes the absolute dev-only
`windows_entry.py` and checkout root, uses `branding/orion.ico`, and opens no
terminal. A deterministic checked-in PowerShell creator validates every path
before using native Windows shortcut COM; focused tests create only temporary
shortcuts and never alter the actual Desktop.

The Python entry resolves and validates the checkout independently of current
working directory, validates the supported project venv, adds only that
checkout to the import path, and calls the existing Console `run_ui` seam. A
missing/incomplete repository, missing runtime, or launch exception produces a
visible native error and never clones, installs, repairs, elevates or selects a
global fallback interpreter. No single-instance framework was introduced.

The real shortcut self-check first exposed `No module named 'tools'` in the
required visible error dialog, proving failure visibility. The entry-root
resolution was corrected, its regression was added, and the same shortcut then
opened one GUI titled `ORION Development Console` with the ORION icon and
existing Launcher-family design. OVERVIEW, HISTORY, GUARD, EVIDENCE, SYSTEM,
ROADMAP and all required actions were visibly present. The final checkpoint
remained user-controlled and was not saved.

Before/after process evidence retained the same pre-existing SRS client/server
PIDs and added only the repository `pythonw` Console bootstrap plus its
base-runtime child. No production Launcher, Core, DCS, SRS, provider,
microphone or audio worker was started by the Console. Production `orion/**`,
installer and packaging are unchanged. FULL post-implementation report
`AG-20260902-220225-8f54461a-e8e13e6-r2` is `COMPLETE` / `PASS`, with zero
conflicts, zero ownership drift and no user decision required. Focused Windows
entry tests passed 8 cases; Phase 1 passed 24, Phase 2 passed 23, Phase 3 passed
36, and all 56 Guard regressions passed. Scoped Ruff, Pyright, compileall,
PowerShell syntax, whitespace, privacy and scope checks passed.

## 25. Development Console Windows-launch verification context bugfix

The narrow bugfix was grounded by FULL preflight
`AG-20260903-152146-a4d1c659-bfb3a96-r2` at starting HEAD
`bfb3a96a7091de1358377f443fab53ae63c6da1e`: history coverage `COMPLETE`, gate
`PASS`, zero conflicts, zero ownership drift and no user decision required.

The actual Desktop shortcut and Explorer environment reproduced the failure as
`OV-20260903-152930-unknown-6a7c9972`. Its Git observation failed with
`FileNotFoundError: [WinError 2]` before repository inspection, leaving
`repository_head=null`, Git `UNKNOWN`, and overall `ERROR`. The explicit
repository argument was intact through the shortcut, `windows_entry.py`,
`run_ui`, `VerificationContext` and `VerificationEngine`. Direct tests had
passed only because the Codex terminal process inherited a bundled Git on its
private `PATH`; the normal Explorer user/machine environment did not contain
Git, although GitHub Desktop carried a usable embedded installation.

The dev-only Console now resolves an existing Git deterministically from
`PATH`, standard Program Files Git, or the newest GitHub Desktop embedded Git.
It performs no installation, repair or environment mutation. The repository
root remains the one authoritative explicit root for every Git call.

The stale Overview had a different cause: it rendered development stage and
approved next step only from immutable checkpoint
`CP-20260902-202904-12498c06`, which correctly records Phase 2 but was never
intended to be rewritten. Overview and checkpoint preview now derive current
semantic position from the existing Roadmap snapshot model. They resolve
`planned:full-development-console-checkpoint` as `READY_FOR_USER_SAVE` and
`planned:low-latency-natural-informational-presentation` as the
`APPROVED_NEXT_STEP`. The preview no longer asks the user to retype known
technical state; persistence still requires the explicit existing Save action.

The post-fix real shortcut run produced
`OV-20260903-153244-bfb3a96-feaf3738` for `dev/adr004-post-389` at
`bfb3a96a7091de1358377f443fab53ae63c6da1e`. Git was `CHANGED` because the
bugfix was intentionally uncommitted during proof, not `UNKNOWN`; the local
state was `CHANGED`, not `ERROR`. Overview showed `Full Development Console
checkpoint · READY FOR USER SAVE` and approved next step `Low-latency natural
informational presentation`. Candidate `CP-20260903-153314-6a0bd921` was
visibly inspected in `CHECKPOINT PREVIEW · NOT SAVED` and cancelled. No new
checkpoint was persisted.

This task changes only Development Console tooling, tests and documentation.
Production `orion/**`, Architecture Guard implementation, Launcher/Core,
installer and packaging are unchanged. The Console verification performed no
network access and launched no product process. DCS, SRS, providers and
microphone were not started.

FULL post-implementation report
`AG-20260903-153713-14d044d4-bfb3a96-r2` is `COMPLETE` / `PASS`, with zero
conflicts, zero ownership drift and no user decision required.

## 26. Low-latency informational presentation Phase 1 candidate

FULL preflight `AG-20260903-155714-3884e2bb-2055af6-r2` recovered the
field-proven Stage 6A persistent Yandex Realtime mechanism and approved only a
non-default benchmark candidate. The normal aircraft identity route remains
Core authoritative fact → Qwen natural formulation → Core validation/binding;
no production selector or protected operational path was changed.

The aircraft identity linguistic-shell validation is now provider-neutral.
The existing Qwen path and the candidate both require exactly one Core marker,
the requested language, bounded single-claim wording, no aircraft identifier
outside the marker and no unsupported factual addition. Core performs the
exact authoritative substitution only after complete-shell validation.

`YandexRealtimeInformationalPresenter` is a separate explicit text-only warm
session candidate. It reuses the canonical Yandex Realtime URL, authorization,
session and item/response event helpers, has no microphone, PCM, VAD, output
audio, STT, TTS or radio ownership, and is not wired into production routing.
Its state machine exposes READY/BUSY/reconnect behavior, queue bound one,
request/response identity correlation, generation invalidation, bounded
timeout, cancellation and late-event rejection. Safe scalar diagnostics omit
credentials, full prompts and hidden provider output.

The private A/B harness uses identical synthetic Core facts for RU/EN F/A-18C,
F-5E and unavailable-state cases. Per the subsequent user scope correction,
the field-proven Qwen values (~17.234 s F/A-18C and ~14.516 s F-5E) are the
primary baseline; only five minimal current Qwen smoke attempts were retained
as secondary context, and no large Qwen sample matrix was run.

Private benchmark `IPB-20260903-164033` is
`REALTIME_CANDIDATE_INCOMPLETE`. Ten initial Realtime WebSocket connection
attempts plus bounded diagnostics established no session: DNS resolved, but
TCP 443 connection to the configured Yandex endpoint failed. Consequently no
Realtime formulation request, text event, validator sample or warm-session
latency exists. The requested n≥20 reliability matrix was deliberately not
fabricated or expanded while connectivity was unavailable. This result is not
evidence that current Yandex text event semantics failed; the protocol was not
reached.

All 61 focused tests and the 369-test relevant regression set passed. They
cover validator compatibility, marker/fact/language failures, terminal text
assembly, correlation, duplicate/out-of-order/late events, timeout/cancel,
reconnect, READY/busy gates and an in-memory Core fact → candidate → validation
→ exact binding integration proof. The next step is to rerun only the Realtime
benchmark after endpoint connectivity is restored; no selector or physical
field candidate is permitted until the required correctness, reliability and
latency gates are complete.

The full repository run completed with 1,934 passing tests and three unchanged
Setup Wizard failures. Those old tests assume that the current Windows account
has no real `Saved Games\DCS` profile, while the unchanged production discovery
code correctly found and auto-selected the profile present on this workstation.
Neither Setup Wizard source nor its tests are in this change, so that
environment-dependent baseline inconsistency was recorded rather than hidden
or repaired outside the approved Phase 1 scope.

FULL post-implementation Guard
`AG-20260903-164119-7e4a69e7-2055af6-r2` is `COMPLETE / PASS`, with no
conflicts, no ownership drift, no duplicate-work risk and no user decision
required. Its console print encountered the known local CP1251 rendering
limitation after the complete Markdown/JSON reports had already been saved;
the stored reports were read and verified directly.
