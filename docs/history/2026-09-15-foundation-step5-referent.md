# Step 5 — factual referent contract correction, live proof incomplete

ORION ARCHITECTURE GUARD: OFF. UNCOMMITTED. NO BUILD / INSTALL / FIELD PASS.

Subsequent resolution: [bounded deadline correction and RU/EN referent gate PASS](2026-09-15-foundation-step5-deadline.md).
This report preserves the preceding inconclusive state; its stop is no longer
the latest Step5 decision. It is not rewritten as if that timed-out gate passed.

## Identity, scope and authorization

CONTRACT READ: `ORION_NATURAL_LANGUAGE_FIRST_CONTRACT_V1` at
`docs/architecture/ORION_NATURAL_LANGUAGE_ARCHITECTURE_CONTRACT.md`, unchanged.
Worktree `C:/Users/Алексей/Documents/GitHub/ORION-level0-conversation`;
branch `codex/general-natural-language-ingress-tranche1`;
HEAD `31546f9f191b060571cba32998c8cf232b345506`, tree
`7ea6f05fb2b6ce5a8507d83400496cf30d907424`. Existing Step 5 dirty work preserved,
index empty. The new user instruction authorizes bounded referent diagnosis,
generic context correction and a bounded follow-up gate, not a build or commit.
This supersedes the prior report's no-further-live-authorization stop only within
that scope. No provider/transport change or new semantic route.

## Exact original sequence

Primary report:
`C:/Users/Алексей/AppData/Local/Temp/orion-foundation-step5-provider-corrected-20260915/report.json`;
SHA-256 `32b94730b4d0a1dfc466c2efdcf34327046fcbf1c3c740e849c829445ca0746b`.
Developer text inputs, real Yandex semantic calls, fixture Core, no STT/audio/DCS.

| Turn / request context revision | Exact user input | Parsed selection | Accepted plan |
|---|---|---|---|
| 1 / 1 | Коротко объясни, почему стекло прозрачно, и сообщи текущий тангаж моего самолёта. | MIXED, ownship.pitch | MIXED |
| 2 / 2 | Каково сейчас значение того же параметра моего борта? | FACT_REQUEST, ownship.pitch | CORE_FACT_AUTHORITATIVE |
| 3 / 3 | Give a short thought about learning a new craft, and report my present true airspeed. | MIXED, ownship.true_airspeed | MIXED |
| 4 / 4 | Read that same aircraft parameter again now. | FACT_REQUEST, ownship.pitch | NONE: gate stopped before Core |

Each of the first three operations performed one fixture read and accepted its
response into context. The original report preserves generated dialogue,
finalized fixture response text, plan kind and exact projections, but not the
complete accepted plan object. Do not present a reconstructed full plan as saved
primary evidence. No claim that the gate's expected-selection assertion exists
in production Core: it is an independent developer oracle.

Turn 4: interaction `7c5a982b-5bf6-4b49-9566-9e743a5d8fa4`, operation
`ed4d1ae3-44c8-4abe-9c2b-2d34a203c39f`, response
`resp_ce0bcf5dd9964e2286433bbebabb205d`. RAW (with Markdown wrapper), normalized
and parsed all contain `{"kind":"FACT_REQUEST","capabilities":["ownship.pitch"]}`.
No correct TAS result was replaced by the parser or validator.

Full reconstruction, including every saved preceding event, response and exact
before/after context projection:
`C:/Users/Алексей/AppData/Local/Temp/orion-foundation-step5-referent-forensic-20260915/report.json`.
It also contains reconstructed provider-visible instructions for each original
operation. Reconstruction uses the unchanged instruction prefix and exact saved
context; the original base instruction size is confirmed as6211 UTF-8 bytes.
The old gate did not save complete wire instructions, so this is explicitly NOT
a newly recovered raw wire capture. Adapter `_context_ack` checks exact echoed
instructions and session identity before emitting context_applied_ack.

## Root-cause classification and limits

**A — proven context representation/contract deficiency; C — its recency-contract
aspect. The complete causal explanation for the original model choice remains F.**

- A: each exchange retains typed requested_capabilities and topic, but the old
  projection has no explicit most-recent factual referent. Mixed reply contains
  only conversational prose by design; a factual reply is null. The provider
  must infer which typed topic remains current from multiple records.
- B: NOT demonstrated. Revision4 correctly contains the accepted TAS Mixed turn.
- C: the array is correctly appended oldest-to-newest by `_append`, but neither
  the old projection nor provider instructions explicitly defines that direction
  or latest-factual-topic precedence. No actual array reversal was found.
- D: stale selection is directly observed. However, a provider-only root cause
  under a fully explicit recency contract was not established in that run.
- E: excluded for the observed terminal: RAW/normalized/parsed agree; no wrong
  reconstruction after a correct provider selection occurred.
- F: why Yandex chose the older entry internally is unknown. Neither the missing
  explicit recency contract nor an attention/history hypothesis is proven to be
  the sole cause by one observation. Do not label this a proven provider-quality
  failure or a live-verified fix.

## Context before and after

Before at revision4: exchanges `[pitch FACT, true_airspeed MIXED]`; each has its
own interaction ID, topic, requested IDs, source user text, accepted outcome and
delivery metadata. No exchange-level timestamp/order index; revision applies to
the entire projection. There is no top-level current-topic pointer. Existing
delivery is unknown and user_heard remains false.

After, for those EXACT same retained exchanges:

```json
{
  "exchange_order": "oldest_to_newest",
  "latest_factual_referent": {
    "interaction_id": "ad5c00d2-9cd2-4421-9e79-c6e9f7f063d4",
    "capabilities": ["ownship.true_airspeed"]
  }
}
```

The referent is derived from the most recent retained, semantically understood,
admitted exchange with requested capabilities. It is not a second mutable state
owner. No new latest-value cache or independently persistent topic is created.
Fact/Mixed/unavailable topics follow the same generic rule. Multiple requested
IDs remain a set/list, not a guessed singular winner. Semantic acceptance does
not imply availability, current truth, delivery or hearing.

Provider-neutral instructions now explicitly define ordering and latest factual
continuation, including Mixed's non-factual reply representation. An explicitly
older reference/new subject overrides the default; genuinely ambiguous singular
references among multiple IDs require clarification. No language/phrase matcher.
Dynamic values are still reread from Core; two exchanges/4096 bytes/300 seconds,
epoch reset and delivery update behavior remain. Bounds count the new fields too.

## Files and symbols changed in THIS continuation

- `orion/general_semantic_contracts.py`: FactualReferent, ContextProjection fields
  and derive_referent validator; provider_instructions context contract only.
  Conflicting supplied referent metadata is rejected. Strict semantic result
  schema/validation, provider model and deadlines are unchanged.
- `tests/test_foundation_referent.py`:11 generic tests including RU/EN × Fact/Mixed
  × two synthetic ID pairs; JSON roundtrip, multi-fact, unaccepted/inconsistent
  referent, delivery, eviction, expiry and epoch reset. Tests first failed on
  absent representation, then passed after correction. This is representation
  proof, not proof that a mocked model understands language.
- `scripts/foundation_fact_gate.py`: optional explicitly labelled offline
  Core-accepted preceding history; capture its plans and actual instructions for
  a developer gate. No production dependency on the gate.
- `scripts/foundation_referent_gate.py`: four planned live follow-ups, RU/EN,
  two other fact pairs, Fact A→Fact B and Mixed A→Fact B. No pitch/TAS special case.
- `tests/general_ingress_hashes.json`: refresh only the corrected contract-module
  fingerprint. Other reviewed runtime hashes unchanged.
- This report and existing Step5/current status/history/evidence/contradiction
  records. No canonical contract, registry, TTS, SRS, Launcher or lifecycle edit
  in this continuation; earlier reviewed Step5 integration remains uncommitted.

## Regression and anti-template audit

Full suite: **3478 PASS / five unchanged baseline FAIL / one skipped**,87.26sec.
XML `C:/Users/Алексей/AppData/Local/Temp/orion-foundation-step5-referent-regression.xml`.
Same IA import inventory, three setup wizard expectations and stale Project
Memory expectation as the previous run; no additional failures. New tests11/11;
changed runtime Pyright zero errors/warnings; scoped Ruff and diff checks PASS.
Actual host matrix and Step1–4 preservation tests included in the full run.

No production input phrases, new regex, language branches, synonym lists or
fact-specific follow-up handlers. Synthetic IDs are tests only. The four live
follow-ups are developer-created and are not published as physical test wording.
Core current-value authority, one General operation, one response owner,
binding/reset, Step3 TTS and Step4 catalog remain unchanged.

## Bounded live result — NOT a semantic PASS or provider-quality proof

Report:
`C:/Users/Алексей/AppData/Local/Temp/orion-foundation-step5-referent-live-20260915/report.json`.
One connection, **one operation / zero retries**, zero owned tasks after shutdown.
The four-operation gate stopped on operation1, without running the other three.
Two preceding turns are OFFLINE Core-accepted fixture plans, not provider results.

RU fact follow-up interaction `63ae1d6d-1545-4562-bd0a-366db0f979da`, operation
`81705ef9-01bf-4529-9bb7-d9e0204bcf6d`, provider session `e769fd40f7a4`.
Context includes old bank and latest altitude_msl, explicit oldest_to_newest and
latest_factual_referent=altitude_msl, correctly bound to its accepted interaction.
Context ACK at297ms; first text781ms; failure at1000ms:
**INTERPRETER_LATENCY_GATE_FAILED**, exception class ConversationFailure.
Cold handshake1469ms is separate. No terminal RAW/normalized/parsed result exists
in this report; partial text is not retained by the existing bounded recorder.
The selected capability after this correction is therefore UNKNOWN.

RU RESULT: incomplete, deadline failure. EN RESULT: NOT RUN. No Core execution
for the live follow-up, no TTS/audio/SRS. The two offline history reads must not
be misreported as live follow-up execution. Current base instructions6922 bytes
versus6211 before; no causal latency claim follows from that size difference.
No deadline widening, retry, additional call or post-failure runtime modification.

## Step 5 status

The context contract deficiency is corrected and offline-tested, but live generic
referent resolution remains unproven. No pre-field readiness, commit, push, build,
installation, physical turn or Foundation FIELD PASS. User data/index untouched.
Do not infer provider-quality failure from a deadline with no terminal result.
Preserve all three earlier/new provider reports and the forensic reconstruction.

STEP 5 REFERENT ROOT CAUSE REMAINS UNKNOWN — STOP
