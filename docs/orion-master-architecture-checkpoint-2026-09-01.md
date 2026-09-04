# ORION Full-Product Master Architecture Checkpoint — 2026-09-01

## 2026-09-04 C3 canonical position update

C1 is complete and D75 is current/clarified. The historical HR01 persistent
Realtime presenter is now reconnected through the existing
`AIRCRAFT_IDENTITY_QUERY` path behind the explicit non-default
`REALTIME_D75_CANDIDATE` selector. Core/WorldModel fact authority, semantic
validation and exact binding remain mandatory; `CURRENT_QWEN` remains the
default. C3 is complete at automated/integration proof level only. The next
stage is C4, a controlled physical DCS/SRS field proof. The earlier
`IPB-20260903-171624` result remains immutable historical evidence rather than
the current development position.

## 2026-09-03 canonical development baseline

D74 establishes `STRATEGY_A_CURRENT_RECONNECT`: current lineage is the
canonical baseline, historically superior mechanisms are reconnected/adapted,
stronger current mechanisms are preserved, and approved unfinished ideas stay
visible. The required layers are CURRENT BEST, HISTORICAL BEST, and RECOVERED
UNIMPLEMENTED IDEA. The durable register is
`docs/orion-canonical-development-policy.md`.

Current position: **CANONICAL ORION BASELINE ESTABLISHED**. Next exact step:
**REALTIME INFORMATIONAL PRESENTER RELIABILITY CORRECTION**, followed only on
PASS by an isolated benchmark, bounded selector, and controlled DCS/SRS field
test. Persistent Realtime remains `KEEP / NON_DEFAULT / BENCHMARK_NO_GO` under
`IPB-20260903-171624`; it is not a production default.

Status: **AUTHORITATIVE FULL-PRODUCT MASTER CHECKPOINT**

Current repository baseline for this historical checkpoint update:

- branch: `dev/adr004-post-389`;
- local `HEAD`: `01a499eac7bb81951e86f4aaa64f2419ab718c48`;
- `origin/dev/adr004-post-389`: `01a499eac7bb81951e86f4aaa64f2419ab718c48`;
- divergence at update start: `0 ahead / 0 behind`;
- tracked and staged state at update start: clean;
- pre-existing generated/untracked artifacts: preserved and outside this
  documentation-only checkpoint.

This checkpoint preserves the approved full-product intent recovered after loss
of part of the original development conversation while retaining the
field-proven voice architecture and current MODEL C direction. It must be
consulted before future product or architecture changes. Current runtime
behavior is not, by itself, proof of intended target architecture.

The complete historical reconstruction behind this update inspected 26 ORION
conversations and 6,602 messages and recovered 70 grouped Master decisions,
including 56 explicit user-approved decisions. The full approval-provenance
register is maintained in
[`orion-master-decision-register-2026-09-01.md`](orion-master-decision-register-2026-09-01.md).
That register is an inseparable authoritative appendix to this checkpoint.

### Authority and precedence

Use this order when sources appear to conflict:

1. the latest explicit user decision;
2. the complete chronological historical decision register;
3. current Git implementation state;
4. an approved ADR or this Master checkpoint;
5. field evidence;
6. tests;
7. summaries, project memory and prior audits;
8. clearly labelled inference.

Current code proves what exists; it does not necessarily prove what was
historically intended. Implementation status and approved target are different
facts. When they differ, both must be recorded; the target must not be silently
rewritten to match incomplete or experimental code. An assistant proposal is
not approved unless the user explicitly accepted it or later adoption is
clearly established. A later summary does not silently override a direct
historical user decision.

## Full product identity

ORION is an **AI copilot, tactical assistant, mission-control layer and
airspace-control / Virtual ATC system for DCS World**. It is not merely a voice
command utility.

The target product understands and correlates aircraft, cockpit, mission,
friendly/enemy, radio and phase-of-flight context. It assists the pilot across
the mission lifecycle through operational services, recommendations,
coordination, conversation and post-flight analysis.

Approved scope invariants:

- DCS is the first simulator integration;
- all supported fixed-wing aircraft and helicopters are the product target;
- generic support comes first, with deeper aircraft adapters added
  incrementally;
- F/A-18C is the first deep proof aircraft, not the only target aircraft;
- voice is a major interaction surface, not ORION's entire product identity;
- ORION does not silently take autonomous control of the user's aircraft. Any
  future change to that boundary requires a separate explicit decision.

## 1. Executive architecture verdict

The approved target is **MODEL C — hybrid routing**.

- Core owns the Semantic Router and decides whether an utterance uses a deterministic operational path or Qwen.
- Qwen must not decide whether Qwen is required.
- A pure, safely recognized standard operational contract may bypass Qwen.
- Free-form, mixed, unknown, complex, ambiguous, conversational, advisory and reasoning-heavy language may use Qwen.
- ToolGateway, WorldModel and domain Core services establish operational truth.
- Phraseology consumes only validated operational semantics (`OperationalSemanticUnit`).
- Protected operational wording is Core-owned and may not be rewritten by Qwen after rendering.
- TTS and radio transport present/transport the result; they do not own semantics.

The current Live Golden route is not the target universal router. It is a
controlled experimental vertical in which Qwen is invoked directly for each
case, including pure operational control cases.

**Mandatory Qwen for every operational utterance is SUPERSEDED EXPERIMENTAL
DRIFT.** The canonical policy is:

- known pure operational input → deterministic Core path;
- free, mixed, unknown, ambiguous or complex input → Qwen/Planner when
  appropriate.

The pure takeoff MODEL C route is now **FIELD_PROVEN**. A safely recognized
pure takeoff request bypasses Qwen with zero expected Qwen calls. Operational
truth remains Core-owned, and the downstream route is
`OperationalSemanticUnit → Phraseology → SpeechKit StreamSynthesis →
RadioRouter/SRS`. This result does not prove or authorize direct routing for
all ATC interactions.

## 2. Mandatory product requirements preserved

ORION remains both an operational assistant and a free-form conversational AI interface.

Required interaction modes include:

- Russian and English;
- standard aviation phraseology;
- natural free-form requests without memorized command syntax;
- mixed utterances containing both conversational and operational fragments;
- casual conversation such as ordinary small talk;
- random/contextual chatter;
- discussion of current/world news when an authorized current-information source is available;
- complex mission, planning and tool-requiring requests.

Deterministic routing must never reduce ORION to a rigid command grammar.

## 3. Local-vs-external-AI constraint

ORION must maximize use of external AI where linguistic breadth, general reasoning and conversational flexibility are required. The local Core must remain compact and deterministic rather than becoming a huge local database or hand-built replacement for an LLM.

Local/Core responsibilities:

- truth ownership and validation boundaries;
- deterministic operational contracts where latency/safety justify them;
- fail-closed routing and protection rules;
- WorldModel/tool access and domain state machines;
- protected operational phraseology;
- compact lexical/contract metadata if later approved.

External-AI responsibilities:

- free-form language understanding;
- ambiguous/unknown/mixed language interpretation;
- planning and reasoning;
- conversational/advisory text;
- broad/general knowledge where appropriate.

## 4. Field-proven voice architecture

### Radio input and turn ownership

`official SRS Client → SRS voice UDP → Opus decode → candidate PCM`.

Local SRS TX ownership/end is observed through localhost UDP 7082 `RadioSendingState.IsSending`.

The authoritative end boundary is `IsSending: true → false`.

The previous 400-ms packet-quiescence heuristic is **SUPERSEDED** as authoritative SpeechKit EOU for this path.

### SpeechKit STT

Current field-proven path:

`candidate PCM → 7082 correlation → SpeechKit v3 RecognizeStreaming → explicit Eou{} → FINAL + EOU_UPDATE cursor barrier → FinalizedUserUtterance`.

Closed invariants:

- candidate PCM is distinct from confirmed local user turn ownership;
- false-only incoming radio traffic must not become a local SpeechKit turn;
- PCM drains before `Eou{}`;
- one persistent SpeechKit RPC can process multiple PTT turns;
- terminal FINAL + EOU_UPDATE with matching cursor barrier closes the provider turn;
- an empty terminal FINAL closes the barrier without creating a semantic utterance.

### Streaming TTS and SRS output

SpeechKit v3 StreamSynthesis is field-proven in the production path.

Current approved low-latency presentation chain:

`final response text → SpeechKit StreamSynthesis → bounded PCM stream/prebuffer → RadioRouter → one SRS TX lifecycle`.

Buffered SpeechKit REST TTS remains an explicit alternative/fallback; it is not the target low-latency primary path.

Latest field result at checkpoint:

- Qwen decomposition: approximately `2750 ms`;
- semantic response ready → first SRS frame: approximately `219 ms`;
- speech end → first SRS frame: approximately `2969 ms`;
- streaming used: yes;
- REST fallback: no;
- underrun/silence insertion: zero.

This demonstrates that Qwen is currently the dominant latency component for the tested standard operational phrase.

## 5. Phraseology ownership and meaning of “Core-owned after semantic truth”

“Core-owned after semantic truth” means:

`input interpretation / deterministic recognition / Qwen planning → required Core tools/domain state → validated operational truth → OperationalSemanticUnit → Core Phraseology`.

It does **not** mean Qwen must always precede Phraseology.

Semantic truth may originate from:

- a deterministic known-contract path;
- Qwen Planner + ToolGateway + Core validation;
- direct Core/domain state-machine events.

Phraseology must not receive raw user questions, provider reasoning or unvalidated tool claims.

## 6. Deterministic intent recognition vs Phraseology rendering

These are separate responsibilities.

### A. Deterministic intent recognition

`transcript → known semantic intent/contract`.

Current status: **PARTIAL**.

A bounded RU/EN takeoff classifier exists, but no universal production recognizer exists for standard ATC/AAR/AWACS/JTAC/Mission Control contracts.

### B. Deterministic Phraseology rendering

`validated OperationalSemanticUnit → ProtectedOperationalFragment`.

Current Pilot resolver already proves this layer experimentally with exact deterministic selection, protected values and fail-closed behavior.

Therefore the next deterministic-routing work must not incorrectly assume that Phraseology rendering itself is a complete input recognizer.

## 7. Role of Qwen

Approved target roles for Qwen:

- free-form language interpretation;
- mixed/unknown/complex utterance decomposition;
- planner/reasoner for requests requiring tools or multi-step interpretation;
- conversational/advisory/free wording;
- current/world-news conversation when paired with an authorized current-information source.

Qwen is **not**:

- operational truth owner;
- protected phraseology owner;
- mandatory universal hop for every utterance.

### Pre-Qwen historical lesson

Before Qwen, ORION already contained several bounded deterministic mechanisms:

- legacy dialogue classification and canned responses;
- voice rules, priority commands and executors;
- domain APIs and state machines;
- Flight/Mission bridges;
- partial ATC, AAR, AWACS, JTAC and Mission Control services.

Those mechanisms proved useful operational subsets, but they were fragmented.
There was no unified Core Semantic Router, free-form language breadth was weak,
mixed semantic decomposition was weak, and current/news discussion was absent.

Qwen was introduced to **extend deterministic Core** with free natural
language, conversation, reasoning/planning, governed tool selection,
complex/mixed interpretation and cloud AI capability with low local CPU/GPU
load. It was not introduced to replace Core or domain truth. Mandatory Qwen use
in Live Golden is an **experimental artifact**, not final product architecture.

## 8. Pure known operational routing

Target route for a safely recognized pure standard contract:

```text
FinalizedUserUtterance
  → Core Semantic Router
  → deterministic known-contract recognition
  → required domain/world/tool truth
  → OperationalSemanticUnit
  → Core Phraseology
  → finalized text
  → streaming TTS
  → RadioRouter
  → SRS
```

Qwen is bypassed only when the **entire relevant utterance** is safely classified as a supported pure operational contract.

A cue word alone is never sufficient for bypass.

Example: the presence of “взлёт” in a sentence does not by itself imply `TAKEOFF_CLEARANCE_REQUEST`.

Unknown, conflicting or ambiguous input must fail closed to the non-deterministic route rather than forcing an operational interpretation.

## 9. Free-form and mixed routing

Target route for free-form/unknown/complex language:

```text
FinalizedUserUtterance
  → Core Semantic Router
  → Qwen interpreter/planner
  → ToolGateway / WorldModel / domain Core as needed
  → validated semantics
  → Phraseology for operational fragments
  → conversational/advisory text as appropriate
  → deterministic composition
  → streaming TTS
  → RadioRouter / SRS
```

Mixed utterances must preserve both classes of content. A free conversational envelope must not be silently discarded merely to qualify the operational fragment for deterministic bypass.

Example: `“Добрый день! Разрешите взлёт.”` is mixed unless a future explicitly approved policy handles the social envelope deterministically.

## 10. Pilot 20–30 phrase corpus clarification

The previously approved “20–30 phrase” Pilot scope was **only a bounded test corpus for Mixed Composition testing**.

It was never:

- the target size of the Phraseology KB;
- the intended number of production intents;
- evidence that one phrase equals one semantic contract;
- an architectural limit on standard aviation language.

The long-term Phraseology KB remains expandable, profile/domain-specific, versioned and source/provenance-aware.

The current 29-entry Pilot rendering catalog is a useful proof of the rendering layer, but it must not be mistaken for the intended product KB size or for the original 20–30 mixed-phrase test objective.

## 11. Operational Lexicon — candidate, not yet approved target component

An “Operational Lexicon” is a promising candidate implementation for a compact fast semantic front-end, but it is **not yet an approved TARGET component**.

If later approved, it must remain compact and contract-oriented rather than becoming a giant local aviation database.

Potential responsibilities:

- known operational concepts and protected terminology;
- support for standard-contract recognition;
- routing hints for mixed utterances;
- controlled normalization of aviation terms where safe;
- priority detection for urgency/emergency messages.

If approved, emergency/urgency contracts must be part of its mandatory priority core. Examples may include MAYDAY/PAN PAN and clearly expressed engine fire/failure, critical fuel, ejection, emergency landing and similar high-priority operational states. False positives must remain fail-closed; a word occurring in an informational question must not automatically create an emergency semantic event.

Emergency/urgency recognition must not depend on a slow general AI path when a safe deterministic contract is available, and priority handling must be able to preempt lower-priority response work according to approved Core policy.

## 12. IA-6 scope

IA-6 is a **narrow controlled vertical**, not the final universal interaction router.

Its purpose is to prove:

- Core-owned route policy;
- a direct path without Qwen;
- a controlled Qwen/Planner/ToolGateway/WorldModel slice;
- exact provider fact-to-Core truth binding;
- provider-neutral communication seams.

Its current small policy surface must not be interpreted as the final routing coverage for all ATC/AAR/JTAC/AWACS/Mission Control interactions.

## 13. Recovered full-product status matrix

| Area | Approved target | Current checkpoint status | Field-proven boundary / principal gap |
|---|---|---|---|
| Product identity | AI copilot + tactical assistant + Mission Control + Virtual ATC | TARGET / PARTIALLY_IMPLEMENTED | Voice/runtime slices proven; full product not complete |
| Airport ATC | Full flight lifecycle | PARTIALLY_IMPLEMENTED | Architectures/state machines exist; no complete unified field route |
| Carrier ATC | Complete carrier lifecycle | PARTIALLY_IMPLEMENTED | Detailed designs/components exist; complete product route not field-proven |
| AWACS/GCI | BRAA, Picture, Bogey Dope, Declare, tactical support | PARTIALLY_IMPLEMENTED | Bounded services exist; unified routing/radio behavior incomplete |
| AAR/Tanker | Availability, location, frequency, TACAN, workflow | PARTIALLY_IMPLEMENTED | Domain workflow exists; complete product interaction not field-proven |
| JTAC/FAC | Talk-on, laser/code, smoke, supported continuation | PARTIALLY_IMPLEMENTED | Sessions/actions exist; unified interaction incomplete |
| Mission Control | Unit/threat/support awareness and coordination | PARTIALLY_IMPLEMENTED | Mission services exist; full conversational layer incomplete |
| Aircraft Knowledge | Detection, profiles, manuals, procedures, recommendations | PARTIALLY_IMPLEMENTED | Architecture and bounded implementation exist; broad coverage incomplete |
| Cockpit Mapping | Validated deep per-aircraft adapters | PARTIALLY_IMPLEMENTED | F/A-18C first proof; all-aircraft depth is TARGET |
| Flight Bridge | Own-aircraft telemetry and bounded local commands | CURRENT / FIELD_PROVEN | Broader generic/deep coverage remains incremental |
| Mission Bridge | Structured mission capabilities | CURRENT / PARTIALLY_IMPLEMENTED | Capability set and field coverage remain bounded |
| Debrief | Post-flight analysis and recommendations | NOT_YET_IMPLEMENTED | Approved TARGET |
| Free speech | RU/EN natural interaction and conversation | CURRENT / PARTIALLY_IMPLEMENTED | Qwen paths proven; not unified with all domains |
| Mixed interaction | FREE + OPERATIONAL decomposition and protected composition | EXPERIMENTAL | Mixed/Live Golden prove bounded behavior, not universal routing |
| Communication Profiles | Persisted selector and profile-specific presentation | INFRASTRUCTURE_IMPLEMENTED / CONTENT_MISSING | IDs, local pack store, lifecycle, source registry, persistence and Launcher UI exist; verified normative entries are not installed |
| Pure takeoff MODEL C | Safely recognized pure request bypasses Qwen | FIELD_PROVEN | Expected Qwen calls `0`; Core truth → OSU → Phraseology → StreamSynthesis → RadioRouter/SRS |
| RadioEntity voices | Persistent recognizable voice per role/entity | DISCONNECTED / NOT_PRODUCTION_WIRED | Provider feasibility evidence exists; production RadioEntity → VoiceProfile resolver is missing |
| Qwen | Extension for free/mixed/complex/planning | CURRENT / FIELD_PROVEN in controlled verticals | Must not be a universal mandatory hop |
| Phraseology | Broad normative profile/domain KB | EXPERIMENTAL | Pilot architecture validated; source packs/wiring incomplete |
| WorldModel | Provenance-aware facade over authoritative truth | CURRENT | Must not become a duplicate truth store |
| ToolGateway | Core-governed typed tool execution | CURRENT | Initial catalog remains bounded/read-only |
| RadioRouter / SRS | Provider-neutral routing over production SRS | FIELD_PROVEN | Wider service/radio awareness remains incomplete |
| STT | Provider-neutral radio STT with native EOU path | FIELD_PROVEN | SpeechKit v3 proven; Realtime retained as legacy option |
| TTS | Low-latency provider-neutral streaming presentation | FIELD_PROVEN | StreamSynthesis proven; tuning remains bounded/experimental |
| Launcher | Single main runtime control surface | CURRENT | Profile and complete module controls incomplete |
| Runtime Modules | Installed-module enable/disable policy | PARTIALLY_IMPLEMENTED | Complete selector/enforcement is a TARGET |
| Installer | Safe canonical Windows product install/upgrade | CURRENT | Modular and aircraft selection incomplete |
| Uninstaller | Full plus selective removal with explicit data policy | PARTIALLY_IMPLEMENTED | Selective UX/policy completion remains TARGET |
| Radio awareness | Roles, frequencies, busy-channel priority, persistent identities | PARTIALLY_IMPLEMENTED | Transport proven; full situational product behavior incomplete |
| News/current information | Authorized current-source conversation | NOT_YET_IMPLEMENTED | Requires an authorized current-information source/tool |
| Emergency/priority | Unified urgent Core-owned fail-closed routing | PARTIALLY_IMPLEMENTED | Legacy bounded rules exist; modern unified front-end incomplete |

No percentage-completion claim is implied by these statuses.

Additional field-proven elements are official SRS radio RX, UDP 7082 TX
ownership/end, SpeechKit v3 External EOU STT, persistent multi-PTT,
correlated PCM-before-EOU, StreamSynthesis, streaming RadioRouter/SRS,
response-ID suppression and controlled real Qwen calls in bounded verticals.

Yandex Realtime radio STT and its `LiveGoldenPttCoordinator` remain available
for the legacy path. For SpeechKit native finalization, Realtime merge semantics
and 400-ms packet quiescence are **SUPERSEDED** as turn-final authority.

## 14. Closed decisions — do not reopen without contradictory evidence

1. Provider selection and radio transport are independent architecture axes.
2. Local SRS TX-end for the current official SRS integration is UDP 7082 `IsSending true→false`.
3. 400-ms packet quiescence is not authoritative EOU for the SpeechKit path.
4. Candidate PCM requires authoritative local-TX correlation before promotion.
5. PCM drain precedes the single explicit `Eou{}`.
6. One persistent SpeechKit RPC may serve sequential PTT turns.
7. FINAL + EOU_UPDATE matching the turn/cursor barrier closes the provider turn.
8. Empty terminal FINAL closes the barrier without emitting a semantic utterance.
9. StreamSynthesis can feed a bounded streaming SRS TX lifecycle without waiting for full buffered synthesis.
10. Protected operational wording is Core-owned and must not be returned to Qwen for rewriting.
11. Phraseology operates only after validated semantic truth.

## 15. Do not confuse

- SRS packet-derived candidate turn ≠ authoritative local SRS TX state.
- Physical button state ≠ SRS `IsSending` logical TX state.
- Provider barrier completion ≠ meaningful transcript.
- Intent recognition ≠ Phraseology rendering.
- Semantic truth ≠ final wording.
- Qwen planner ≠ Core authority.
- STT provider ≠ semantic owner.
- TTS provider ≠ presentation/semantic owner.
- Live Golden test harness ≠ final production architecture.
- IA-6 narrow vertical ≠ universal final routing.
- 20–30 mixed test corpus ≠ product KB size.

## 16. Completed first bounded migration and continuation principle

**PURE TAKEOFF DETERMINISTIC ROUTE BEFORE QWEN** is complete and
**FIELD_PROVEN**.

The implementation reused the bounded RU/EN takeoff recognition and existing
ATC truth. A safely classified pure request bypasses Qwen; mixed, free,
unknown, conflicting and ambiguous input remains on the non-deterministic
route. Field evidence recorded zero Qwen calls and preserved
`OperationalSemanticUnit → Phraseology → StreamSynthesis → RadioRouter/SRS`.

Current safe continuation principle: migrate one bounded operational
capability at a time under MODEL C:

```text
recognition
  → Core route
  → existing domain truth/service
  → OperationalSemanticUnit
  → profile-aware Phraseology
  → TTS/radio
  → deterministic regression and field evidence
```

Reuse proven domain services and tests. Do not rewrite an entire historical
domain at once, recreate a legacy universal parser/router, or broaden a
single-slice field result to unrelated interactions.

The next implementation family is **ATC**, because the user explicitly
prioritized continuing ATC before AAR. This documentation checkpoint does not
select the exact next ATC contract.

## 17. Performance consequence

Latest field route is approximately:

`STT final → Qwen ~2.75 s → semantic ready → first streaming SRS frame ~0.22 s`.

For the pure supported takeoff contract, removing Qwen from the valid
deterministic route was expected to remove approximately 2.75 seconds from the
previous measured route. The completed no-VPN field run subsequently measured
approximately `462 ms` from PTT end to first SRS frame, with zero Qwen calls.
This is field proof only for the bounded pure takeoff route.

## 18. Approved functional product scope

The following are approved product targets. A current bounded service is not,
by itself, proof that the full target or its unified interaction route is
complete.

### Virtual ATC

Target lifecycle:

- startup and clearance;
- ground and taxi;
- tower and takeoff;
- departure;
- approach and arrival;
- landing;
- emergency, divert and conflict handling;
- airport operations;
- carrier operations.

Current status: **PARTIALLY_IMPLEMENTED**. Airport and carrier architecture,
state machines and bounded services exist, but there is no complete unified
production voice route for the full lifecycle. Golden Takeoff is an
experimental bounded proof, not full ATC field validation.

Field-proven status: **not proven as a complete lifecycle**.

### AWACS / GCI

Approved targets include BRAA, Picture, Bogey Dope, Declare, threat assessment
and tactical support using mission-observable facts.

Current status: **PARTIALLY_IMPLEMENTED** through bounded domain, mission and
voice components. Unified MODEL C routing and complete radio product behavior
remain incomplete. The complete target service is not field-proven.

### AAR / Tanker

Approved targets include tanker availability, callsign/location, frequency,
TACAN, relative range/position and refuelling workflow/coordination.

Current status: **PARTIALLY_IMPLEMENTED** through AAR state, rendezvous,
contact, monitoring and voice/domain components. Unified routing and the full
product workflow remain incomplete. The complete target service is not
field-proven.

### JTAC / FAC

Approved targets include talk-on, target assistance, laser designation and
code, smoke marking, JTAC/FAC workflows and an approved continuation/9-line
scope where the mission exposes authoritative support.

Current status: **PARTIALLY_IMPLEMENTED** through JTAC sessions, assets,
Mission Bridge actions and Mission Control coordination. Unified interaction,
Phraseology and complete field workflow remain incomplete. The complete target
service is not field-proven.

### Mission Control

Approved targets include awareness of relevant units and movement, threats,
supporting assets, mission continuity, recommendations and coordination.

Current status: **PARTIALLY_IMPLEMENTED** through MissionStore/context,
mission-control picture, support coordination and bounded domain services. It
is not yet a complete unified conversational mission-control layer and is not
field-proven as that complete target.

### Aircraft Knowledge and cockpit assistance

Approved targets include automatic aircraft detection, deep per-aircraft
profiles, validated cockpit mapping, manuals/procedures, checklists,
troubleshooting and recommendations.

Current status: **PARTIALLY_IMPLEMENTED**. A generic telemetry foundation and
Aircraft Knowledge architecture exist, with F/A-18C as the first deep proof.
Basic DCS/F/A-18C integration has field evidence; broad all-aircraft Aircraft
Knowledge is not field-proven.

### Debrief

Post-flight analysis of mission execution, relevant events, errors and useful
recommendations remains an approved **TARGET / NOT_YET_IMPLEMENTED as the full
product capability**.

## 19. Aircraft, telemetry and bridge architecture

The approved telemetry model is a universal normalized core plus validated
aircraft-specific adapters:

`Identity → Kinematics → Airframe → Propulsion → Fuel → Navigation → Radios →
Payload/Weapons → Warnings → EW/RWR → Sensors → Cockpit`, with Mission World
kept alongside rather than mixed into the high-rate aircraft packet.

Four data layers remain distinct:

1. generic DCS telemetry;
2. module-dependent generic APIs;
3. aircraft-specific cockpit telemetry;
4. Mission World state.

Flight Bridge and Mission Bridge remain separate. Flight Bridge owns
own-aircraft telemetry and a very small allowlist of cockpit-local commands.
Mission Bridge owns structured mission capabilities and registration. The
WorldModel is a provenance-preserving facade over authoritative sources, not a
duplicate truth store.

Unavailable, restricted, unsupported or not-yet-mapped data must be explicit.
ORION must respect multiplayer/server export restrictions and must not infer
denied state. Aircraft-specific argument mappings must be validated, not
guessed.

## 20. Communication Profile architecture

A user-facing **Communication Profile** selector is an approved product
requirement. The stable profile contracts are:

- `ICAO`;
- `FAA_US`;
- `NATO_MILITARY`;
- `FAP_RUSSIAN_ATC`.

The approved Launcher model is a separate section/menu/table with exactly one
active profile and a persisted per-user selection. Communication Profile and
input/conversation language are independent settings.

A profile may control operational phraseology, terminology, callsign/runway/
frequency formatting and radio-procedure presentation. A profile may **not**
change operational truth, ToolGateway permissions, WorldModel visibility,
mission state, provider selection, authority or safety policy.

Current infrastructure status:

- Communication Profile IDs: **IMPLEMENTED**;
- provider-neutral Communication Profile API: **IMPLEMENTED**;
- local pack store: **IMPLEMENTED**;
- schema/version/source-registry contracts: **IMPLEMENTED**;
- candidate/ACTIVE/PREVIOUS_KNOWN_GOOD lifecycle: **IMPLEMENTED**;
- hash/compatibility/signature trust seam: **IMPLEMENTED**;
- offline behavior: **IMPLEMENTED**;
- Launcher profile selection and persistence: **IMPLEMENTED**;
- Update/Details/Rollback UI: **IMPLEMENTED**;
- production registry host/trust roots: **NOT CONFIGURED / INCOMPLETE**;
- verified production normative phraseology content: **MISSING / NOT
  INSTALLED**;
- cross-profile operational rendering: **NOT YET PROVEN**.

All bootstrap packs are research-only and contain no active normative entries
or language realizations, so profile selection currently cannot activate a
production Phraseology pack. `Russian Military` was deferred and must not be
conflated with `FAP_RUSSIAN_ATC`; profile names alone do not define normative
content.

Historical user-facing UI intent is simpler than the internal pack model. The
main Launcher concept is:

| Selection | Communication Profile | Basis | Purpose | Phraseology KB action |
|---|---|---|---|---|
| one active | ICAO | International | civil/international presentation | Update phraseology data |
| one active | FAA / US | United States | US presentation/procedure | Update phraseology data |
| one active | NATO / Military | NATO publications | military presentation | Update phraseology data |
| one active | ФАП / Russian ATC | Russian ATC basis | Russian ATC presentation | Update phraseology data |

Detailed source, verification and technical pack state may be shown under
Details; it must not replace the simple user-facing profile model.

## 21. Launcher product requirements

Launcher is the single main user-facing runtime control surface. Approved and
current direction includes:

- start/connect/status control for the separated Core;
- tray and explicit lifecycle behavior;
- voice, provider, device and settings controls;
- a Communication Profile selector;
- a runtime Modules selector;
- DCS discovery, integration repair and launch control;
- Normal and OpenXR DCS launch profiles where applicable;
- diagnostics, field-evidence and build-identity visibility;
- avoiding unnecessary browser, console or extra control windows;
- keeping future approved controls inside Launcher where practical.

The mature Launcher/Core lifecycle is **CURRENT**: window close hides to tray,
while explicit Exit terminates only the exact Launcher-owned Core and preserves
an external compatible Core. Communication Profile selection, persistence and
pack lifecycle controls are implemented. Full runtime Modules selection and
enforcement remain incomplete product targets.

## 22. Installer, upgrade and uninstaller

Approved installer target:

- complete installation of the canonical product;
- modular installation and module selection;
- aircraft selection;
- all available selections enabled by default unless later product policy says
  otherwise;
- safe upgrade/in-place replacement;
- exact build identity for packaged and installed Core/Launcher.

Installation selection and runtime enablement are different decisions. The
installer controls what is present on disk; Launcher controls what installed
modules participate in the runtime.

Approved uninstaller target:

- full uninstall;
- selective Core, Launcher or module removal;
- explicit policy for credentials, user data and generated evidence.

Current state: full product packaging, safe build markers and ordinary
install/upgrade paths exist. Modular installation, aircraft selection and
selective uninstall UX remain **PARTIALLY_IMPLEMENTED or TARGET** and must not
be represented as complete.

## 23. Radio product targets

The current SRS transport, RadioRouter boundary, registration, Opus/pacing and
TX completion behavior remain field-proven and authoritative.

Approved product direction also includes:

- clear Direct Voice versus SRS role separation: direct local interaction,
  device testing and appropriate non-radio assistance are distinct from
  operational radio services carried through SRS;
- service-specific radio roles and frequencies for ATC, AWACS/GCI, JTAC,
  tanker and related entities;
- relevant third-party radio awareness without treating uncorrelated identity
  claims as authoritative;
- busy-frequency scheduling, priority and preemption policy;
- persistent radio entity identity and stable role voices;
- PTT/transmission boundaries that bound a radio turn, not the provider session
  lifetime.

These wider situational-awareness and scheduling items are
**PARTIALLY_IMPLEMENTED or TARGET**, not FIELD_PROVEN as a complete radio
product.

## 24. Emergency, urgency and priority

Approved semantics include urgent/immediate priority classes and explicit
emergency, divert and conflict handling. Historically, bounded voice rules gave
critical cases such as missile, terrain, fire and stall elevated priority.

Current state: useful old priority/domain mechanisms exist, but a modern unified
emergency semantic front-end behind MODEL C is **PARTIALLY_IMPLEMENTED**.

Future migration must remain fail-closed, Core-owned, able to preempt
lower-priority work under an approved policy and resistant to false emergency
activation from informational or quoted text. This checkpoint does not approve
or design an emergency lexicon.

## 25. Testing, evidence and observability

ORION development relies on deterministic tests, bounded provider protocol
probes, controlled field evidence, exact Git/build SHA identity, privacy-safe
bounded diagnostics, secure credential handling and ordinary Launcher/Core
product artifacts for real field validation.

A test-only executable or synthetic probe must never be mistaken for product
field validation. Generated audio or transmitter-side WAV evidence proves only
the stage it observes; it does not prove audio reached the user's headphones.

## 26. Migration rule for existing domain capability

Useful pre-Qwen deterministic capability remains fragmented across legacy
dialogue, voice rules/executors, domain APIs, bridges and ATC/AAR/AWACS/JTAC/
Mission Control services.

The target is **not** to restore the old fragmented parser as the primary
router. The target is:

**ADAPT useful bounded deterministic capability behind the current MODEL C,
provider-neutral, Core-owned Semantic Router.**

Migration should reuse proven domain truth and state machines, remove duplicate
route ownership, preserve fail-closed boundaries and expand one bounded
contract at a time.

## 27. KEEP — do not roll back genuine improvements

Corrective routing work must preserve:

- SpeechKit v3 External EOU and its native finalization barrier;
- persistent multi-PTT SpeechKit sessions;
- UDP 7082 authoritative local TX ownership/end;
- candidate PCM promotion, empty-barrier and completeness fixes;
- SpeechKit StreamSynthesis and bounded streaming SRS TX;
- RadioRouter and the production SRS adapter;
- provider-neutral interaction, planner, speech and radio contracts;
- ToolGateway execution policy;
- WorldModel provenance and authority semantics;
- exact semantic value binding;
- protected Phraseology boundary;
- secure credential storage and non-exposure;
- installed/frozen build identity;
- bounded field evidence and observability;
- mature Launcher/Core tray and ownership lifecycle;
- Communication Profile API, local pack lifecycle and Launcher profile UI;
- the field-proven pure takeoff MODEL C route;
- Yandex Realtime availability and response-ID suppression for its existing
  path.

The objective is not a rollback to pre-Qwen code. It is to keep these
improvements, remove accidental drift and migrate useful deterministic domain
capability into MODEL C.

## 28. Drift and priority summary

### C3 HIGH

- A pure known operational path currently pays unnecessary Qwen latency in the
  Live Golden experimental route.
- Major useful domain capabilities are not yet migrated behind the unified
  MODEL C Semantic Router.
- The modern unified emergency/urgency route is incomplete.
- Radio situational awareness, busy-frequency scheduling and service-role
  behavior are incomplete.
- The complete runtime Modules selector/enforcement is incomplete.
- Modular/aircraft-selectable installation is incomplete.

### C2 MEDIUM

- Communication Profile infrastructure and Launcher UI are implemented, but
  verified normative content and cross-profile operational rendering are
  missing/unproven.
- Authorized current/world-news access is not implemented.
- Full debrief is not implemented.
- Broad normative profile/domain Phraseology source packs are incomplete.
- Selective uninstall and explicit credential/data cleanup UX are incomplete.
- Broad Aircraft Knowledge and deep per-aircraft coverage remain incomplete.

Different is not automatically worse. SpeechKit native EOU, RadioRouter/SRS,
streaming TTS, provider-neutral contracts, ToolGateway, WorldModel provenance,
build identity, evidence and lifecycle behavior are improvements to preserve.

## 29. Evidence basis for this expansion

This checkpoint integrates and reconciles:

- the complete chronological reconstruction of 26 ORION conversations and
  6,602 inspected messages;
- the authoritative 70-decision Master Decision Register appendix;
- the previous Master Architecture Checkpoint;
- the completed pre-Qwen routing recovery and exhaustive pre-loss approved
  concept inventory;
- the recovered original ChatGPT ORION archive;
- accessible earlier Codex task history and recovered architecture audits;
- `docs/ORION_PROJECT_MEMORY.md`;
- current Git history and implementation status;
- ADR-001 and ADR-003 through ADR-007;
- airport/carrier ATC, Aircraft Knowledge and telemetry documents;
- IA-0 through IA-6 decisions;
- Stage 6B.1/6B.2 radio decisions;
- Pilot Phraseology, Golden, Mixed and Live Golden records;
- current code/tests where needed to avoid overstating implementation status.

Only architecture/product decisions were retained. Raw private conversation,
credentials, provider payloads and unrelated personal data are not reproduced
in this repository document.

## 30. Future unresolved decisions

The following are not required to implement the approved bounded takeoff route:

- final normative source packs and licensing/acceptance process for production ICAO/FAA/NATO/FAP phraseology;
- whether trivial conversational envelopes such as greetings may later be handled deterministically while preserving free-form semantics;
- whether an Operational Lexicon becomes an approved explicit component and, if so, its exact contract/API and emergency priority model.
- exact modular-installer, aircraft-selection and selective-uninstall UX;
- detailed provider/tool policy for authorized current information;
- final service-specific busy-frequency and preemption policy;
- any future autonomous-aircraft-control boundary change.

None of these invalidates the field-proven bounded pure-takeoff route. They do
not authorize choosing a new exact ATC contract in this documentation task.

## 31. Historical roadmap and status

The recovered last approved pre-loss sequence is preserved here so later work
does not rename, reorder or recreate completed stages:

| Stage | Historical purpose | Current status |
|---|---|---|
| IA-0 | Provider-neutral interaction contracts | COMPLETED |
| IA-1 | Yandex presentation contract probe | COMPLETED / PROBE_PASS |
| IA-1.1 | Realtime versus SpeechKit hybrid presentation | COMPLETED / FIELD_PROVEN |
| IA-2 | WorldModel facade | COMPLETED |
| IA-3 | ToolGateway | COMPLETED |
| IA-4 | PlannerProvider contract | COMPLETED |
| IA-5 | Yandex Qwen planner adapter | COMPLETED / PROVIDER_PROVEN |
| pre-IA-6 | Launcher-owned Core lifecycle correction | COMPLETED |
| IA-6 | Narrow InteractionRouter vertical | COMPLETED; not universal routing |
| Stage 6B.1 | Radio contracts and RadioRouter | COMPLETED |
| Stage 6B.2 | Production SRS adapter | COMPLETED / FIELD_PROVEN |
| Stage 6B.2 field gate | Official-SRS physical/acoustic validation | FIELD_PROVEN |
| Pilot Phraseology | Bounded non-normative resolver/corruption probe | EXPERIMENTAL / PROBE_PASS |
| Golden | Deterministic authority/protected wording proof | COMPLETED / PROBE_PASS |
| Mixed | FREE + OPERATIONAL composition proof | COMPLETED / PROBE_PASS |
| Live Golden | Physical end-to-end conversational experiment | EXPERIMENTAL; mandatory-Qwen route SUPERSEDED |

The first MODEL C migration after this roadmap, pure takeoff before Qwen, is
also complete and field-proven. Current continuation remains bounded ATC
capability migration; this checkpoint does not select the next ATC contract.

## 32. Field-proven register

`FIELD_PROVEN` is reserved for evidence from the normal or intended physical
product path, not merely deterministic tests or a synthetic probe.

| Capability | Field-proven boundary |
|---|---|
| Qwen voice baseline | Normal realtime voice operation was observed in the installed product, including controlled VPN/no-VPN runs |
| SRS/Yandex radio chain | Official radio RX → provider → SRS TX proved after canonical RadioInfo correction |
| Stage 5.1 frequency isolation | `251 → 252 → 251 MHz` routing behavior observed |
| FlightContext | Real DCS telemetry/context passed through the bounded provider path with provenance |
| IA-1.1 hybrid presentation | 20/20 SRS transmissions, semantic PASS, 20 WAV artifacts and human `CLEAR` review |
| Stage 6B.2 SRS adapter | 20/20 adapter-start → SRS-start → tx-completed → adapter-completed sequences with acoustic review |
| SpeechKit v3 External EOU | Complete PCM, one explicit EOU and native final/cursor barrier observed |
| Persistent multi-PTT | Sequential physical PTT turns completed within one SpeechKit RPC |
| UDP 7082 turn ownership | Official SRS `IsSending true→false` proved as authoritative local TX end |
| Streaming TTS | SpeechKit StreamSynthesis fed one bounded streaming SRS lifecycle without REST fallback |
| Pure takeoff MODEL C | Zero Qwen calls; Core-owned truth; approximately `462 ms` PTT end → first SRS frame in the no-VPN run |

Pilot Phraseology, Golden/Mixed offline cases, isolated provider protocol
probes and generated WAVs are valuable evidence but are not independently a
complete product `FIELD_PROVEN` result.

## 33. DO NOT REBUILD — already exists

Future tasks must extend, connect or migrate the following components. They
must not create parallel replacements:

- Flight Bridge and Mission Bridge;
- FlightContext;
- WorldModel and its provenance contracts;
- ToolGateway and receipts;
- PlannerProvider and the Yandex Qwen adapter;
- InteractionRouter;
- OperationalSemanticUnit and protected-fragment contracts;
- airport ATC state machines, controllers and services;
- AAR services;
- AWACS briefing/prioritization services;
- JTAC runtime, assets, status and voice services;
- Mission Control query, coordination and bounded autonomy services;
- Aircraft Knowledge API and existing adapters;
- radio contracts and RadioRouter;
- production SRS transport/adapter and canonical SRS RadioInfo;
- SpeechKit v3 External EOU STT;
- UDP 7082 authoritative turn ownership;
- persistent multi-PTT SpeechKit sessions;
- SpeechKit REST TTS and SpeechKit StreamSynthesis;
- response-ID suppression;
- Test Evidence recording/export;
- credential storage and secret boundaries;
- installed/frozen build identity;
- Launcher/Core ownership and tray lifecycle;
- Communication Profile API, local pack store and pack lifecycle;
- Launcher Communication Profile selection/update/details/rollback UI;
- Pilot Phraseology, Golden and Mixed probes;
- pure takeoff MODEL C route.

## 34. ACTUALLY MISSING / PARTIAL / DISCONNECTED / DEFERRED

These terms are not interchangeable:

- **MISSING**: no complete production capability was found;
- **PARTIAL**: useful implementation exists but does not meet the full target;
- **DISCONNECTED**: components/contracts exist but are not production-wired;
- **DEFERRED**: explicitly postponed rather than accidentally lost.

| Capability | Status | Required future work |
|---|---|---|
| Verified normative phraseology entries | MISSING | Source/licensing acceptance, verified entries and language realizations |
| General deterministic recognizer beyond bounded slices | MISSING | Extend MODEL C one contract at a time |
| Complete Carrier ATC runtime | MISSING / PARTIAL DESIGN | Implement without duplicating airport/domain truth |
| RadioEntity → persistent VoiceProfile resolver | DISCONNECTED / MISSING RESOLVER | Bind stable entity identity to provider-neutral voice selection |
| Busy-channel/collision/preemption scheduler | PARTIAL | Unify role priority, wait and emergency interruption policy |
| Trusted third-party radio identity correlation | PARTIAL | Add provenance-safe correlation before WorldModel promotion |
| Runtime Modules UI/persistence/enforcement | PARTIAL | Complete module inventory and runtime behavior |
| Modular aircraft/component installer | PARTIAL | Add installation selection distinct from runtime enablement |
| Selective uninstall/user-data choices | PARTIAL | Complete explicit credentials/data/evidence policy UX |
| Debrief | MISSING | Add privacy-aware post-flight analysis product path |
| Current-information/news connector | MISSING | Add authorized current source with freshness/provenance |
| Mission-editor assistant | MISSING | Add bounded module later |
| Broad all-aircraft knowledge adapters | PARTIAL | Expand from generic/F/A-18-first foundation |
| Native VR status overlay | DEFERRED | Implement only under a later bounded UI decision |

## 35. Durable rejected and superseded knowledge

The full provenance is in the Master Decision Register. At minimum, future
work must not revive these as unexamined ideas:

- ORION-managed VR tuning/settings — rejected;
- duplicate manual callsign — rejected;
- Free Russian/Free English as profile-menu choices — superseded;
- four hard language modes — superseded;
- immediate Russian Military fifth profile — deferred;
- permanent Whisper fallback — superseded;
- always-on Qwen session — rejected;
- Qwen inside Core or owning domain truth — rejected;
- Qwen-owned protected Phraseology — no-go;
- Hybrid C as sole protection — no-go;
- critical output through Realtime only — superseded;
- provider/VAD-owned physical radio turn — superseded;
- packet-gap EOU — superseded;
- universal mandatory-Qwen operational route — superseded experimental drift;
- 20–30 as production KB size — rejected interpretation;
- test-only GUI/probe as production field proof — rejected;
- DCS audio ducking as a requirement — rejected/not required;
- premature full Launcher cleanup before architecture/radio gates — deferred.

## 36. Phraseology packs and RadioEntity status

Pilot Phraseology is an **EXPERIMENTAL PROBE**. The 20–30 figure means
**TEST_CORPUS_ONLY**. It does not limit the production KB or imply one final
intent per phrase.

The pack mechanism is implemented, but ICAO, FAA, NATO and FAP production
rules are not yet verified or installed. Communication Profile may affect
presentation rules, operational language and phraseology. It may not affect
truth, permissions, provider selection, mission state or safety authority.

The historical RadioEntity target is a persistent recognizable voice per role
or entity. Multi-voice provider feasibility and acoustic evidence exist, but
the current production streaming path remains fixed/default-oriented. A
production RadioEntity → VoiceProfile resolver is **MISSING**. This is not a
regression from a previously complete production resolver; the historical
target was never fully wired.

## 37. Full-product scope preservation

This Master continues to cover the complete product rather than only voice or
takeoff ATC. Approved targets include Virtual ATC, Carrier ATC, AWACS/GCI,
AAR, JTAC/FAC, Mission Control, Aircraft Knowledge, cockpit assistance,
debrief, free conversation, authorized current/world news, all-aircraft and
helicopter coverage, radio situational awareness, Runtime Modules, modular
installation, selective uninstall and a future graceful VR overlay.

## 38. Authority and update rule

This file is the authoritative full-product architecture baseline as of
2026-09-01.

Future implementation tasks should cite this checkpoint when they affect
product scope, semantic routing, Qwen use, domain migration, Phraseology,
Communication Profiles, STT/TTS/radio ownership, Launcher/module/installer
behavior, or operational/free/mixed interaction.

A future contradictory change requires an explicit architecture decision; it must not arise merely because an experimental vertical happens to behave differently.
