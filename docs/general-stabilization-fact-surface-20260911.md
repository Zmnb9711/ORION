# General interaction stabilization and safe fact surface

ORION ARCHITECTURE GUARD: OFF

CONTRACT READ: `ORION_NATURAL_LANGUAGE_FIRST_CONTRACT_V1` in
[the unchanged canonical contract](architecture/ORION_NATURAL_LANGUAGE_ARCHITECTURE_CONTRACT.md).
This is an implementation/evidence record, not a policy amendment or field PASS.

## Recovery and scope

Continues the uncommitted Gate A/B work on
`codex/general-natural-language-ingress-tranche1`, parent
`7b6981a9eb56ddc455c8a166842f867725152f41`. No reset/reconstruction from baseline.
The user's untracked `data/fa18c_value_profiles.json` remains outside the commit
and installer, SHA256 `4975E243EE95FDF997CCC5ECC4537EAFF87947265C1C9A7F876ECF3CCEE15C1F`.
Canonical contract SHA256 remains
`DE59126CB79EFC010996F4F8357AB80B641109B7ED3CD60CCBC7856D53C2A128`.

## Gate A — stabilization and length correction

Preserved prior changes: exact opt-in RAW/NORMALIZED/PARSED terminal evidence,
safe validation fields, one owned fresh recovery for a FUTURE turn after dirty
semantic failure, and explicit context separating meaning from delivery.
No same-turn retry, hidden provider memory, new worker or TTS/SRS algorithm.
The saved streaming files have observation-only hooks; optional observer failures
cannot alter synthesis. No new recorder/audio capture architecture.

The immediate351-character valid DIALOGUE failed only the inherited300 schema
bound. The older bounded Conversation precedent is9ccab96; general ingress7b6981a
used the same number. No downstream300-character technical requirement was found.
Correction: hard400, soft usually200/one or two short sentences. DialoguePlan,
ContextExchange and exact opt-in evidence aligned; legacy Conversation remains300.
No truncation, shortening model or retry. Existing30-second PCM bound unchanged;
400 characters do not guarantee an acoustic duration or voice-quality PASS.

One separately authorized live continuation passed normal125chars, deliberate
developer output-length377chars, synthetic malformed result, real owner recovery
1094ms, future Dialogue91chars and current-heading selector. Four real operations
plus one injected failure; two connections, one recovery, zero remaining tasks.

## Gate B — actual source inventory, not theoretical API coverage

[Machine manifest](general-fact-surface.json) and [full matrix](general-fact-matrix.md)
contain134 records: raw families and leaves, not134 executable capabilities.
Registry version `orion.facts.ca5f8a3c354c5973`. Seven exposed selectors:
aircraft.identity, ownship.position, ownship.heading, ownship.altitude_msl,
ownship.pitch, ownship.bank, ownship.yaw. EXPOSED means this code admits them,
not that each has current live values or new field validation.

Actual path: Export -> TelemetryEnvelope -> Core receive time/LiveTelemetryStore
-> WorldModelFacade.ownship -> existing ToolGateway -> strict selected FactPlan
-> deterministic finalized text -> existing presentation. Multi-fact performs
one coherent ownship read. Only selected typed leaves may enter response text;
receipt, source, authority, generation, units, bounds and freshness remain checked.
Partial unknown/stale/restricted facts have named typed unavailable components.
Provider receives compact id/meaning metadata, never current telemetry values.

Fuel is NOT EXPOSED: internal_raw/external_raw are explicitly module_dependent;
no validated per-module mass/fraction denominator or normalized fraction mapping.
TAS fallback can become ground-vector magnitude; missing vector components can
be manufactured zero. Those speed facts stay blocked. Negative AGL clamp loses
source-quality information; AGL not exposed. Raw configuration/engines/payload,
Hornet observations without per-leaf calibration receipt, sensors/contacts and
Mission World remain separately classified and not admitted through ownship.
Mission truth is not observed AWACS knowledge. Radio cockpit data is not SRS state.

One separately justified source-quality bug fix under original §108/§203:
Export adds heading_valid, model accepts optional strict bool, WorldModel withholds
manufactured/ambiguous zero. Real0 with explicittrue is known; legacy0 without
quality is unknown; legacy nonzero remains usable. Heading numeric formula,
callbacks/ports/pacing otherwise unchanged. No exporter redesign or deployment.

Coordinates are output-only spoken DDM with hemisphere words and .01minute
precision; values are not rounded in WorldModel. Whole-minute rounding could
lose926m peraxis, versus9.26m peraxis at .01minute. New MSL output rounds metres,
attitude.1degree; heading preserves existing decimal precision. No input grammar.

## META correction — separately authorized after Gate B STOP

First B gate passed seven checks, then a capability-description question produced
FACT_REQUEST of all seven IDs. Schema accepted it; the test stopped before Core
admission. This is semantic role misselection, not a faulty catalog or provider
billing/transport failure. Production structural validation alone would not have
identified that wrong meaning. Exact raw evidence remains preserved.

New typed `META_REQUEST(topic=capabilities|identity|help)` carries no text, values
or capability list. Core produces `CORE_CAPABILITY_METADATA` from actual registry
entries and existing output labels, or approved ORION identity/help description.
No Gateway access (including definition lookup), no simulator readiness claim,
no Planner or second LLM. Description is bounded to eight categories and explicitly
says when partial; it distinguishes category availability from current value health.
No duplicate capability list was added to provider instructions.

META context retains topic/described IDs rather than current fact prose. Context
remains two exchanges/4096UTF8bytes/300s; provider item deletion/isolation unchanged.
One additional field distinguishes metadata from factual output. Follow-up plumbing
tested with the same warm owner; broad natural-language accuracy still needs field.

STATE_SUMMARY no longer enumerates CATALOG. Explicit Core projection:
heading, geometricMSL, pitch, bank. Registry growth cannot automatically widen it.
The output identifies itself as limited parameters, not a full aircraft assessment.
All seven facts remain selectable in a genuine explicit multi-fact request.
General knowledge about other people/aircraft remains DIALOGUE; ORION metadata is
META; unsupported current needs are CAPABILITY_GAP; true ambiguity CLARIFICATION.

Only two production files changed in this correction: general_semantic_contracts
and general_semantic_core. Tests and source-identity hashes aligned. No input
keyword/regex/few-shot rule, no STT/TTS/SRS/Launcher/Planner change.
Base prompt3394 ->4071UTF8bytes (+677,19.95%), category boundaries only.

## Personal context

Explicitly authorized personal fact lives outside repository/package in the normal
user runtime personal-context.json. Authority USER_PROVIDED, source
EXPLICIT_USER_AUTHORIZATION, separate from recent context/DCS/provider history.
Read-only bounded loader:4facts/4096bytes; no automatic conversation retention.
No name/relationship intent, input phrase/synonym matcher, or extra inference.
Tests use fictional data. Real personal fact was not sent in these unrelated
provider probes. Blind natural-language/personal-context field proof remains pending.

## Validation and limits

123 targeted semantic/Core/registry/META tests PASS. Full final regression:
3259PASS,3SKIP,4 independently preserved baseline failures (IA0 import allowlist
and three machine-sensitive Saved Games SetupWizard tests). Zero new failures.
Ruff, changed-scope Pyright, compileall, diff checks and frozen source/host gates PASS.
Initial obsolete prompt-wording test was updated to require the new META role;
no baseline failure was hidden or removed. Every exposed fact has real local
WorldModel/Gateway fixture coverage. Context, typed injection, permissions,
wrong provenance, late/replay/cancel and no-extra-telemetry regressions pass.

Single new provider continuation, six operations on one connection:

| Boundary | Outcome | Semantic+admission ms |
|---|---|---:|
| capability description | META, Core description,0fact reads |672|
| general knowledge | generated DIALOGUE |672|
| aircraft identity | correct FACT_REQUEST |547|
| position+heading+MSL+pitch+bank | exact multi-selector |766|
| broad current status | STATE_SUMMARY without IDs |469|
| unsupported fuel | CAPABILITY_GAP/fuel |515|

One connection, zero retries/recoveries, stopped owner/zero tasks. Content reviewed.
Facts were admitted but NOT executed in the provider gate; actual Gateway mapping
was tested offline. No DCS/SRS/TTS/PTT/provideraudio involved. This gate is finite
evidence, not a guarantee against every future semantic misclassification.

Gate A and B code/offline/provider gates now pass at those stated levels. Canonical
contract remains a larger target: new MIXED/reasoning/domain execution and full
Russian/English acoustic coverage are not claimed complete. Existing typed
NOT_IMPLEMENTED behavior and historical fast paths remain. No end-to-end<1s claim.
Earlier position zeroPCM incidents remain unexplained; diagnostics were preserved,
not used to claim an unrelated transport fix. Existing64-operation bound remains.

## Receipts and handoff

Historical failure and A–M receipt:
`C:/Users/Алексей/Documents/ORION-Restoration/stabilization-fact-surface-20260910`.
New META A–S, parent A–III closure, exact delta, regression XML, live RAW/NORMALIZED/
PARSED and artifact receipts:
`C:/Users/Алексей/Documents/ORION-Restoration/meta-discrimination-20260911`.
Live report SHA256 `76D60C8D6BAC4BE65E99D6A58E4ACB5288BBE60F205B484B25E678F3CF1F0DFC`.
Final regression XML SHA256 `F9666E4F6D9860E943D44F73F01759A4BC9975846B7970F034C7E5C01468A3D8`.
Raw machine status pending-content-review is unchanged; this record confirms review.

One committed-source normal installer is authorized only after these gates.
Exact commit/tree, executable hashes and package smokes belong in external receipt
to avoid self-reference. NO INSTALL, push, user action or physical field test in
this tranche. Blind user-selected field validation is the next acceptance level,
not a completed result; do not hand the user prepared test phrases.
