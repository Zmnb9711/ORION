# ORION Master Architecture Checkpoint — 2026-09-01

Status: **APPROVED AUTHORITATIVE BASELINE**

Repository baseline at approval: `dev/adr004-post-389` @ `a716b4456a6923e55620417362ab3e5014157cb4`.

This checkpoint exists to preserve the recovered target architecture after loss of part of the original development conversation. It must be consulted before future architectural changes. Current runtime behavior is not, by itself, proof of intended target architecture.

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

The current Live Golden route is not the target universal router. It is a controlled experimental vertical in which Qwen is invoked directly for each case, including pure operational control cases.

## 2. Mandatory product requirements preserved

ORION remains both an operational assistant and a free-form conversational AI interface.

Required interaction modes include:

- Russian and English;
- standard aviation phraseology;
- natural free-form requests without memorized command syntax;
- mixed utterances containing both conversational and operational fragments;
- casual conversation such as ordinary small talk;
- random chatter;
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

## 13. Current vs target status summary

### FIELD_PROVEN

- official SRS radio RX path;
- UDP 7082 TX ownership/end;
- SpeechKit v3 External EOU STT;
- persistent multi-PTT SpeechKit RPC;
- correlated PCM-before-EOU lifecycle;
- StreamSynthesis production path;
- streaming RadioRouter/SRS TX lifecycle;
- response-ID suppression;
- controlled real Qwen calls in proven verticals.

### CURRENT

- Interaction contracts;
- narrow IA-6 Router;
- PlannerProvider/Qwen adapter;
- ToolGateway;
- WorldModelFacade;
- domain Core state machines/services;
- Flight/Mission Bridge separation;
- buffered REST TTS alternative/fallback.

### TARGET

- general Core-owned semantic routing;
- deterministic known-contract routing where safe;
- broad production Phraseology KB/Engine;
- preservation of free-form/mixed/conversational AI paths;
- wider domain migration through the provider-neutral contracts.

### EXPERIMENTAL

- Pilot Phraseology KB/resolver;
- Golden Takeoff vertical;
- Mixed Composition probe;
- Live Golden Mode A;
- StreamSynthesis selector/tuning values such as prebuffer size.

### LEGACY / SUPERSEDED

- Yandex Realtime radio STT path;
- Realtime `LiveGoldenPttCoordinator` merge semantics for the SpeechKit native-final path;
- 400-ms packet quiescence as authoritative SpeechKit EOU;
- legacy dialogue/realtime-domain gateways where superseded by newer provider-neutral routing.

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

## 16. Approved next implementation step

Exactly one next implementation task is approved:

**Wire one bounded pure-takeoff deterministic Core route before Qwen.**

Constraints:

- reuse the existing bounded RU/EN takeoff classifier rather than duplicating it;
- bypass Qwen only when the utterance is safely classified as a pure supported operational request;
- mixed/free/unknown/conflicting/ambiguous input falls back to the existing Qwen path;
- route the deterministic result through existing ATC truth → `OperationalSemanticUnit` → Phraseology → streaming TTS;
- do not change protected wording;
- do not expand landing/taxi/AAR/AWACS/JTAC in the same task;
- do not change SpeechKit STT, StreamSynthesis, SRS/7082 or RadioRouter;
- use the intended mixed-phrase corpus as a negative-routing regression corpus, not as a production KB-size assumption.

Field latency testing comes only after deterministic implementation/regression succeeds.

## 17. Performance consequence

Latest field route is approximately:

`STT final → Qwen ~2.75 s → semantic ready → first streaming SRS frame ~0.22 s`.

For a pure supported takeoff contract, removing Qwen from the valid deterministic route could save approximately 2.75 seconds in the current measured case.

This is a **performance estimate**, not field proof. A new field test is required after the deterministic route is implemented.

## 18. Future unresolved decisions

The following are not required to implement the approved bounded takeoff route:

- final normative source packs and licensing/acceptance process for production ICAO/FAA/NATO/FAP phraseology;
- whether trivial conversational envelopes such as greetings may later be handled deterministically while preserving free-form semantics;
- whether an Operational Lexicon becomes an approved explicit component and, if so, its exact contract/API and emergency priority model.

## 19. Authority and update rule

This file is the approved architecture baseline as of 2026-09-01.

Future implementation tasks should cite this checkpoint when they affect semantic routing, Qwen use, Phraseology, STT/TTS ownership, Mixed Composition or operational/free-form interaction behavior.

A future contradictory change requires an explicit architecture decision; it must not arise merely because an experimental vertical happens to behave differently.
