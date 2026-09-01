# ORION Pure Takeoff MODEL C Field Validation — 2026-09-01

Status: **FIELD PASS — PURE TAKEOFF MODEL C ROUTING**

Implementation build: `6f6f2f1aebbbde36aa0f0860df265c1e6013fd7b`

Authoritative architecture baseline: `docs/orion-master-architecture-checkpoint-2026-09-01.md`.

## Purpose

This record closes the first physical field gate for the recovered MODEL C routing architecture. The test verifies that a safely recognized pure standard operational request can be routed by Core without Qwen while preserving the existing Core ATC → OperationalSemanticUnit → Phraseology → StreamSynthesis → RadioRouter/SRS chain.

The validated field phrase was:

`Разрешите взлёт.`

## Field evidence

Two controlled evidence sessions were compared:

- `ORION-Test-Evidence-20260901-135611.zip` — test performed with VPN enabled.
- `ORION-Test-Evidence-20260901-135915.zip` — test performed without VPN.

### Routing result

The pure takeoff path was confirmed in the physical SRS/SpeechKit field chain:

- contract matched: yes;
- pure known operational contract: yes;
- effective route: deterministic known contract;
- Qwen required: false;
- Qwen calls: `0`;
- Core ATC result: one;
- OperationalSemanticUnit: one;
- Phraseology protected fragment: one;
- StreamSynthesis used: yes;
- REST fallback: no;
- one SRS response lifecycle;
- streaming underrun observed in the successful no-VPN runs: none.

The validated response wording remained Core/Phraseology-owned. The routing change did not move operational truth or protected wording into the recognizer or Qwen.

## Latency A/B observation

### VPN-enabled run

The deterministic Core route itself remained effectively immediate, but SpeechKit StreamSynthesis first-audio latency was approximately `5.109 s`. The measured end-to-first-SRS-frame latency was approximately `5.125 s`.

This run demonstrates that removal of Qwen alone does not guarantee low end-to-end latency when the provider/network path is degraded.

### VPN-disabled run

The no-VPN evidence contained repeated pure-takeoff cases with consistent low latency:

| Metric | Pure takeoff #1 | Pure takeoff #2 |
|---|---:|---:|
| PTT end → STT final/barrier | ~59 ms | ~72 ms |
| Core route | ~0 ms | ~0 ms |
| Qwen | 0 calls | 0 calls |
| TTS start → first provider audio | ~422 ms | ~360 ms |
| TTS start → first SRS frame | ~453 ms | ~391 ms |
| PTT end → first SRS frame | ~509 ms | ~462 ms |
| Streaming underrun | 0 | 0 |

Previous Qwen-path comparison baseline was approximately `2968.761 ms` from speech end to first SRS frame, with approximately `2750 ms` attributable to Qwen decomposition.

The no-VPN field result therefore confirms the practical latency value of MODEL C deterministic routing for this bounded contract.

## VPN interpretation

The A/B evidence shows a strong correlation between the VPN-enabled run and severe SpeechKit StreamSynthesis first-audio latency in this test environment. It does **not** establish that every VPN or every VPN route will cause the same delay.

For latency-sensitive ORION field validation, VPN state must therefore be recorded explicitly. Unless a provider specifically requires it, the preferred controlled latency-test condition is VPN off.

## Architecture verdict

The first bounded MODEL C migration vertical is field-validated:

`SRS physical PTT → SpeechKit v3 External EOU STT → Core known-contract route → deterministic ATC truth → OSU → Phraseology → StreamSynthesis → RadioRouter/SRS`

with Qwen absent from the critical path for the validated pure takeoff contract.

This validates the migration pattern, not a universal command grammar. Mixed, free-form, unknown, ambiguous and complex language remains on the Qwen-capable path according to the Master Checkpoint.

## What this does not prove

This field pass does not claim:

- universal deterministic ATC recognition;
- complete real-DCS ATC lifecycle integration;
- completion of landing/taxi/startup/departure/arrival migration;
- completion of Communication Profile packs;
- removal of Qwen from ORION;
- approval of an Operational Lexicon;
- that VPN is always harmful;
- completion of all ATC product scope.

## Next migration priority — ATC

User decision after this field validation: **continue with ATC rather than AAR**.

AAR remains a strong later migration candidate, but it is not the next priority.

The next migration work must stay inside the approved MODEL C strategy and reuse existing ATC domain services/state machines rather than rebuilding them or restoring the old fragmented top-level parser.

Before broad ATC implementation, the next task should identify the best bounded ATC continuation after takeoff from the existing migration map, with particular attention to the existing arrival/approach/go-around services and to preserving a reusable known-contract → Core ATC → OSU → Phraseology pattern.

No voice transport, STT, UDP7082, StreamSynthesis, RadioRouter/SRS, Qwen free/mixed role, ToolGateway authority or WorldModel provenance change is implied by this priority decision.

## Closed field result

`PURE_TAKEOFF_MODEL_C_FIELD_PASS = YES`

`PURE_TAKEOFF_QWEN_CALLS = 0`

`NO_VPN_PTT_END_TO_FIRST_SRS_FRAME = approximately 0.46–0.51 s`

`NEXT_MIGRATION_FAMILY = ATC`

`AAR_NEXT = NO`
