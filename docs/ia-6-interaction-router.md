# IA-6 Interaction Router and controlled Planner slice

Status: **IMPLEMENTED — CODE AND LIVE PROVIDER VALIDATED 2026-08-27**.

IA-6 adds the first Core-owned policy boundary that selects a deterministic
path or the IA-4 Planner. It also closes exact semantic value binding and adds
only the provider-neutral communication seams approved for future phraseology
work. It does not implement phraseology, radio routing or presentation.

## Routing before IA-6

Before this stage, product interaction entry points were independent:

- `/v1/dialogue` called the legacy keyword-based `classify_dialogue` path;
- Realtime providers used `RealtimeToolService`, including its separate
  Virtual ATC gateway and ready-made ATC replies;
- Virtual ATC/domain APIs called their domain services directly;
- IA-4 exposed a provider-neutral Planner lifecycle and IA-5 implemented the
  real Yandex Qwen adapter, but ordinary Core traffic did not select that path;
- Realtime, SpeechKit and SRS owned presentation/transport concerns and did not
  provide a general semantic interaction router.

IA-6 does not migrate or remove those paths. It introduces one narrow canonical
Core boundary for new controlled interactions without changing their existing
behaviour.

## Core policy and production boundary

`POST /v1/interactions` accepts bounded text and presentation context. The API
does not accept a capability allowlist, permission set, provider ID or tool
catalog. Core creates the IA-0 `InteractionRequest`, deadline and communication
context.

The first policy version, `ia6.router-policy.v1`, recognizes only:

1. a small exact health/test vocabulary, executed directly without Qwen;
2. a heading-and-position ownship situation query, sent through the controlled
   Planner slice;
3. everything else, returned as typed `unsupported` rather than being sent to
   Qwen by default.

For the Planner route, Core replaces any caller capability hints with exactly
`world.ownship.read`. IA-4 therefore exposes only
`orion.world.ownship.get`. The flow is:

```text
InteractionRequest
  -> IA-6 policy decision
  -> IA-4 PlannerTaskRunner
  -> real IA-5 YandexQwenPlannerProvider
  -> IA-3 ToolGateway
  -> IA-2 WorldModelFacade.ownship
  -> retained ToolResult
  -> IA-5 continuation
  -> IA-0 SemanticResponse
  -> exact Core value binding
```

The Router passes one Core absolute deadline and cancellation token into IA-4;
IA-4/IA-5 retain provider cancellation, tool cancellation, cleanup and bounded
retry semantics. A bounded replay ledger returns the recorded result for an
identical interaction ID/signature. Reusing the ID with changed semantic input
fails with `replay_conflict`, so tools are not executed twice.

Router diagnostics contain only typed stages, IDs, route, reason, domain,
capability and policy version. They contain no user text, tool payload,
provider body, credential or reasoning.

## Exact fact-to-ToolResult binding

IA-4 previously established only that an authoritative semantic fact cited a
completed tool result whose aggregate provenance included an authoritative
source. That permitted a provider to cite the correct call while changing a
value or choosing an unrelated key.

Core now extracts scalar leaves directly from retained typed WorldFact data.
An authoritative `SemanticFact` is accepted only when exactly one leaf has:

- the same WorldFact key;
- a `known` status;
- `authoritative` authority for that specific fact;
- the same semantic unit;
- the same typed scalar value, allowing only lossless numeric equality such as
  integer `137` and JSON number `137.0`.

Booleans are not integers, strings are exact, structured values are addressed
by deterministic paths such as `ownship.position.latitude`, and derived facts
cannot be upgraded to authoritative. A sourced unavailable/unknown input must
likewise bind to the matching null WorldFact and status. No natural-language
comparison or cryptographic layer is involved.

## Communication seams only

`communication_contracts.py` adds immutable contracts for:

- profiles `ICAO`, `FAA_US`, `NATO_MILITARY`, `FAP_RUSSIAN_ATC`;
- domains `GENERAL`, `ATC`, `AWACS_GCI`, `JTAC`, `AAR`,
  `MISSION_CONTROL`, `NAVIGATION`;
- input, conversational and future operational language separation;
- priorities `ROUTINE`, `IMPORTANT`, `URGENT`, `IMMEDIATE`;
- output classes `CONVERSATIONAL`, `ADVISORY`,
  `OPERATIONAL_PROTECTED`;
- typed protected values, bounded provenance and immutable
  `OperationalSemanticUnit`;
- optional/untrusted/droppable conversational envelope;
- immutable Core-rendered protected fragments and a future deterministic
  composition plan.

No rule renderer or aviation formatter exists. Snapshot/version fields are
optional opaque seams and default to null; IA-6 does not invent an active KB.
The contract makes `IMMEDIATE` envelope suppression expressible and keeps a
Core-rendered protected fragment separate from any future Qwen envelope.

Communication context is orthogonal to routing. All four profiles produce the
same route, exact capability allowlist and tool catalog for the controlled
ownship request. A profile cannot change IA-2 visibility, IA-3 permissions,
tool authority, freshness or mission truth.

## Validation and bounded live observation

Deterministic tests cover the direct path, unsupported fail-closed result,
controlled Planner tool loop, exact heading/position acceptance, value and unit
mutation rejection, incomplete semantic rejection, unavailable source binding,
profile/tool-authority orthogonality, replay conflict, deadline, cancellation,
API authority boundary, diagnostics privacy and immutable communication seams.

The initial bounded live-provider checks used synthetic ownship data only. No
DCS, SRS, Launcher or audio device was started. They consistently reached the
real IA-5 provider and executed exactly one completed IA-3 ownship call, but
Qwen's final semantic classification varied. Two responses repeated
`ownship.heading_deg` in both authoritative and derived arrays, which the IA-0
unique-key invariant rejected. Another response downgraded all requested known
authoritative leaves to derived facts and added altitude, which the controlled
IA-6 completeness policy rejected. HTTP, response completion, strict JSON,
tool-call correlation and cleanup were valid; the failure was stochastic
provider semantic non-compliance, not IA-5 translation or IA-6 value binding.

The narrow correction strengthened only this controlled slice's Core
instructions: return exactly heading, latitude and longitude; preserve known
authoritative or sourced-unavailable status; exclude altitude; keep
`derived_results` empty for this non-calculation; and never repeat a semantic
key. No schema, validator, tool policy, retry or provider output transformation
was relaxed or added. One post-fix live gate then completed through Router,
IA-4, real Qwen, one IA-3 call, synthetic IA-2 data and exact value binding.
It accepted heading `137 deg`, latitude `42.1` and longitude `41.2`, all tied to
the completed call ID, with no derived facts. Both stored provider responses
were deleted and the transport closed. No semantic retry or repair was used.

## STOP boundary

IA-6 does not add a Phraseology Engine, templates, normative KB, Source
Registry, updater, communication-profile Launcher UI, social memory, radio
context/router, SRS adapter changes, DCS Native Voice Chat, domain ownership or
legacy ATC/AWACS/JTAC/AAR migration. Those remain later stages.
