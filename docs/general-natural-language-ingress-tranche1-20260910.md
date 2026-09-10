# General Natural-Language Ingress — implementation tranche 1

ORION ARCHITECTURE GUARD: OFF

Policy: [canonical contract](architecture/ORION_NATURAL_LANGUAGE_ARCHITECTURE_CONTRACT.md),
`ORION_NATURAL_LANGUAGE_FIRST_CONTRACT_V1`. This record implements a tranche;
it does not replace or amend that contract.

## Source and authority

Runtime preservation parent: `2c58b3752ad79a639db6e406e2eeb1927b21086d`.
Policy parent: `7d0b5487d074c24f3c3a84dcf2f91ba108f32d87`, its direct child,
containing only policy/docs changes. Work branch:
`codex/general-natural-language-ingress-tranche1`. No production branch merge,
push, installation, DCS/SRS or physical test is authorized by this record.
Generated `data/fa18c_value_profiles.json` is preserved, not added or packaged.

## Normal host / roles

Existing golden ownship → local aircraft/Hybrid/FREE_ONLY → existing bounded
Conversation routes retain precedence. A clean whole-source unresolved miss
now reaches one generalized warm Yandex semantic operation instead of
aircraft-only `not_applicable` → final silence. No new user phrase recognizer,
regex vocabulary or per-capability classifier is added. Existing protected
failure/ambiguity handling is not converted into permission to execute.

The strict provider-neutral union is DIALOGUE, FACT_REQUEST, CLARIFICATION,
CAPABILITY_GAP, MIXED, REASONING_REQUEST, DOMAIN_REQUEST. Extra keys, duplicate
JSON keys, unknown capabilities, model-supplied values, tool output and multiple
JSON objects are rejected. Existing whole Markdown-fence normalization is reused;
no substring extraction or speculative repair. FINAL text/hash stays exact.

DIALOGUE includes the generated <=300-character reply in the SAME operation.
It does not call the old Conversation provider or Planner afterward. Core owns
the admitted non-authoritative DialoguePlan, finalization and presentation ledger.
No phrase-level prose whitelist is used. A JSON schema cannot prove the truth of
arbitrary dialogue prose: simulator claims remain forbidden by provider policy,
and the bounded live response was inspected for them. Universal freedom from
hallucination is NOT established by these tests or this three-operation gate.

Facts contain selectors only. InteractionRouter validates provider, exact source,
request/operation/turn, catalog, context revision, deadline, cancellation and
single-use admission. GeneralSemanticCore maps admitted selectors to the actual
`orion.world.ownship.get@1.0` definition and `world.ownship.read` permission.
No dynamic model-supplied handler, tool name or argument dictionary is executed.

## Implemented capability declaration

| Capability | Current evidence | Boundary |
| --- | --- | --- |
| aircraft.identity | Prior 2c58 FIELD VALIDATED; new host OFFLINE + PROVIDER VALIDATED | Existing Hybrid authoritative identity tail and display-name mapper reused |
| ownship.position | IMPLEMENTED OFFLINE / HOST VALIDATED / PROVIDER VALIDATED | Latitude + longitude only; no altitude or place-name inference |
| ownship.heading | IMPLEMENTED OFFLINE / HOST VALIDATED / PROVIDER VALIDATED | Existing heading_deg in degrees; no magnetic/track claim |
| general dialogue | IMPLEMENTED OFFLINE / HOST VALIDATED / PROVIDER VALIDATED | Genuine one-operation reply; still historically FIELD FAILED pending new blind test |
| position + heading | IMPLEMENTED OFFLINE / HOST VALIDATED / PROVIDER VALIDATED selector | One authoritative Gateway read, three selected numeric leaves |
| explicit follow-up context | IMPLEMENTED OFFLINE | Minimal bounded general-turn history, not full conversational memory |
| clarification / capability gap / unavailable | IMPLEMENTED OFFLINE / HOST VALIDATED | Core-owned bounded wording, no fabricated alternatives |
| new MIXED / aircraft + other facts | NOT IMPLEMENTED | Contract representable; truthful NOT_IMPLEMENTED, no competing TX |
| general reasoning / operational execution | NOT IMPLEMENTED | Typed placeholders; existing Planner/domain code and fixture coverage preserved |
| LOCAL_SOCIAL | Prior behavior preserved / HOST VALIDATED | Existing typed Hybrid FREE_ONLY constant; zero provider calls, not generated dialogue |

No raw fuel, speed, altitude, systems, contact, Mission World or observed/AWACS
facts become exposed merely because they occur in the source snapshot.

Position uses existing `WorldModelFacade._format_coordinates`: degrees/decimal
minutes, hemisphere, two decimal minute places. Heading uses the exact selected
degree value with `Текущий курс ... градусов.`; no new reference-frame conversion.
Source labels remain silent. Both require known authoritative `dcs_export`,
correct units/key/generation/provenance/receipt and <=5-second freshness. Only
selected typed leaves reach FactPlan; unrelated snapshot fields are discarded.
Unknown/stale/unavailable/restricted data produce typed truthful outcomes. Invalid
provenance/receipt produces admission rejection, never a generic telemetry dump.

## Ownership, context and deadlines

The normal FullVoiceService remains sole host. GeneralSemanticVoice borrows the
existing warm owner and radio endpoint, and owns only Core plan/context and a
typed subclass of existing streaming protected presentation. No additional SRS,
Core, WorldModel or worker owner; no Launcher START/STOP/readiness changes.
Cleanup uses finally ownership so a general presentation cleanup failure cannot
skip the borrowed interpreter shutdown. Old truthful lifecycle errors propagate.

Context is in-memory: at most TWO completed exchanges, 4096 serialized UTF-8
bytes, 300-second TTL. It stores exact user text, non-authoritative dialogue reply
only, selected capability topic and language. Factual answer values are NOT sent
back to the provider as context. Current facts always require another Core read.
Reset on new owner/STOP, expiry or changed observed Test Session / mission ID /
aircraft-type metadata. Same-type aircraft replacement not visible in that metadata
is not claimed to be detected. Old fast-path/Conversation history is not imported;
this is explicitly minimal continuity, not global dialogue memory. Failed provider
or admission outcomes do not update accepted context. Revisions bind proposals.

Warm native owner behavior remains: optional <=3s warmup, no automatic retry,
one operation at a time, 64-operation bounded session, fail-closed dirty owner.
Both exact item deletion ACKs are required before READY. The existing independent
500ms isolation barrier is unchanged and excluded from the current answer path.

Simple typed facts retain <=1s interpretation/admission. For general protocol,
`kind` is requested as the first JSON field. A schema-header prefix (NOT user
language matching) arriving within the selector budget may extend DIALOGUE to
12s. It is not admission: strict terminal parsing must agree; duplicate/changed
kind cannot use this to relax fact admission. Dialogue terminal >1s is tested
offline. A delayed/missing role header can still fail the initial 1s budget; this
is a declared first-tranche limit, not an end-to-end voice latency achievement.
The old 64-operation cap also remains; continuous unbounded sessions are not
claimed. TTS start latency is unchanged and remains separate debt.

## One live provider gate — PASS, no retry

Evidence: `C:\Users\Алексей\AppData\Local\Temp\orion-general-ingress-20260910\provider-gate.json`.
One warm connection, exactly three operations, all parsed/admitted, two deletion
ACKs per operation, stopped owner with zero owned tasks. No DCS, SRS or TTS.
Core fact execution was separately proved offline, not presented as live DCS.

| Operation | First text ms | Terminal + admission ms | Isolation ms |
| --- | ---: | ---: | ---: |
| DIALOGUE | 360 | 594 | 250 |
| aircraft.identity | 359 | 469 | 234 |
| position + heading | 360 | 547 | 266 |

Cold handshake 1156ms. Parse/normalization and admission are individually below
the existing coarse monotonic timer's resolution (recorded 0ms deltas); these are
not asserted to have zero cost. Raw terminal, normalized envelope, parsed result,
correlation and event timestamps preserved. DIALOGUE text:
«Мне интересно обсуждать технологии, космос и интересные факты из истории. А вам
что больше всего нравится?» — non-authoritative dialogue, no current DCS claims.
Provider returned whole Markdown fences; existing normalization accepted them.
No second model call, tools, audio or authoritative values appeared.

## Offline / preservation / scope

Tests cover strict schema, correlation, value injection, extra telemetry, bad
authority/source/generation/receipt/units/range/freshness, cancellation and replay;
context bounds/TTL/reset/re-read, dialogue/fact deadline distinction, independent
isolation, normal host one-response ownership and privacy. Historical six FINALs
are replayed as test data only: four general DIALOGUE, one LOCAL_SOCIAL, one
aircraft selector. Future blind field phrases remain UNKNOWN.

Full regression before live: **3099 PASS, 4 pre-existing FAIL, 3 SKIP**. The four
failures were reproduced against exact 7d0 parent archive: IA0 consumer allowlist
already missing four historical consumers; three Setup Wizard expectations
affected by local Saved Games discovery. Only this tranche's newly approved
general Core consumer was added to the list; the old baseline failure remains
visible. No xfail or unrelated production repair.

Post-provider complete regression repeated: **3099 PASS, 4 baseline FAIL,
3 SKIP**, 72.82s. Final focused general set **99 PASS**, including one subsequently
added explicit coalesced position+heading normal-host replay; no production change
after live validation. Ruff orion/tests, compileall, changed-production Pyright
(zero errors/warnings), diff whitespace and frozen-source checks PASS.
Provider JSON SHA-256:
`2EDFDC6ADCBFC810D61E0B20B91D0F0FF2E0411293B9C04A1A1132DC7492BF7C`.

Golden differential still compares RX/PCM/STT options/EOU, Core selected facts,
positive protected response/TX and lifecycle against 57a563a. Its old unsupported
Core remains unsupported; the explicit new outer response is truthful provider
unavailability with offline semantic infrastructure. Old tests expecting silence
were changed only at that authorized boundary. New tests cover actual general
operation/typed plan/presentation instead of hiding differences in a baseline.

`tests/general_ingress_hashes.json` fixes exact reviewed normalized source hashes
for nine production files. Historical hunk restoration runs only after those
complete-file hashes pass, then compares original checkpoints. Both in-hunk and
outside-hunk mutation tests fail. Everything else under orion/packaging/dcs-export
must match 2c58. This is not a dynamic/broad allowlist.

## Exact production surface and frozen boundaries

| File / symbols | Necessary integration |
| --- | --- |
| general_semantic_contracts.py | New provider-neutral union, Core catalog, request/context/proposal |
| general_semantic_core.py | New Core admission consumption, selected mapper, plans/render/context |
| general_semantic_voice.py | New typed presentation adapter borrowing old streaming mechanics |
| full_voice_service.py | Replace clean miss tail, LOCAL_SOCIAL evidence, metadata reset and owner cleanup |
| yandex_warm_aircraft_interpreter.py | Shared general union operation/prompt and dialogue time domain; same transport/isolation |
| interaction_router.py | Typed single-use general admission; existing routes unchanged |
| hybrid_aircraft_core.py | Single granted entry into existing identity tail; no recognizer edit |
| protected_presentation.py | Explicit finalized-type union for inherited admission; old base path retains type guard |
| realtime_test_evidence.py | Existing opt-in scalar projection gains role/counters/selected facts; no recorder redesign |

No changes to WorldModel/Gateway implementation, Planner, local grammar,
Conversation admission/output policy, DCS export, STT, protected TTS request text,
streaming/radio algorithms, SRS registration/RadioInfo/EAM, Launcher or packaging.
No new casts/Any/type-ignore bridge. Normal mode retains no new text/fact events;
optional evidence failures are non-fatal. No raw microphone/audio capture added.

## Contract post-check / release boundary

Sections 1–7, 10–14: open unresolved input, one semantic hop, Core values, no
phrase additions, no new Planner chain, historical paths preserved. Sections 8–9:
new mixed execution deferred explicitly by tranche authorization; minimal context
implemented with stated limits. Sections 15–20: offline/provider/field levels kept
separate, canonical source unchanged, blind utterances not requested or encoded.
No template/authority/provider-history/transport drift trigger observed.

Previous bounded proof slices repeatedly became de facto language boundaries.
This tranche keeps capability types bounded but input language open, with blind
field acceptance and explicit preservation. This is a regression lesson, not a
claim that this implementation already satisfies the complete target product.

After final offline confirmation: one coherent commit, ONE installer candidate,
package identity and non-transmitting isolated smoke. DO NOT INSTALL here.
No field success claim until unseen user wording is tested and all turns audited.
Future categories only: ordinary and unrelated conversation, aircraft identity,
position, heading, optionally unavailable facts/context. No scripted field phrases.
