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
metadata, project-document sections, and Decision Register rows D01-D72.

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

All D01-D72 rows are imported exactly from their AG-1 document pointers.
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
