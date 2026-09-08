# Hybrid Aircraft decomposition contract fix — 2026-09-08

ORION ARCHITECTURE GUARD: OFF (explicit historical recovery exemption).

## Baseline and scope

Exact parent: `4ca5effe2c5772a3268ba1f131bbad77a095c7ea`.
Ancestry: `333ca5e` -> `7b041d6` (truthful STOP) -> `474d11b`
(bounded Qwen cleanup) -> `4ca5eff` (bounded Hybrid Aircraft slice).
Worktree: `ORION-hybrid-aircraft-contract-fix`.
Branch: `codex/hybrid-aircraft-decomposition-contract-fix`.

Only four production files change:

| File/symbol | Required change |
| --- | --- |
| `hybrid_aircraft_contracts.HybridAircraftDecomposition` | Remove provider-owned classification; retain strict language/spans only. |
| `hybrid_aircraft_core.validate_decomposition`, `derive_route`, `_run` | Preserve literal source/grammar checks; derive route only after validation; forward bounded timing observations. |
| `yandex_qwen_planner.YandexQwenPlannerProvider.decompose_aircraft` | Correct schema instructions; non-fatal scalar result/cleanup observations around the same single request and cleanup call. |
| `realtime_test_evidence.record_aircraft_slice` | Admit two timing event names and explicitly named `core_derived_route`. |

No changes to FullVoiceService, Launcher, SRS, STT, ToolGateway, WorldModel,
informational/protected presentation, TTS, DCS integration, truthful STOP,
STOP timeout, model, credentials, retry policy or cleanup implementation.

## Immutable physical evidence — first field attempt FAILED

Original ZIPs remain in
`C:\Users\Алексей\AppData\Local\ORION\runtime\test-evidence`.

| Archive | SHA-256 |
| --- | --- |
| `ORION-Test-Evidence-20260908-155651.zip` | `0f6cdafa6dbdf46362c162fd174cbabc52b8ca3746bb4b67254f04d2e6c18057` |
| `ORION-Test-Evidence-20260908-155733.zip` | `be50102c7b0e61116fb4fe3b986de435baa5f1bf4ed367cf2600022ab1e82393` |

Both completed provider outputs are in ZIP 1. Both have exact STT FINAL:
`добрый день в каком самолете я нахожусь` (39 Unicode characters).
Both sessions record `orion_build_sha=unknown`: the archives alone do not
establish installed artifact/source identity.

CASE A, turn `eca5f73e-811f-463b-8062-119d784f492b`:
provider classification AIRCRAFT_IDENTITY; GREETING [0,11), aircraft [12,39).
Spans are valid. Baseline rejects with `decomposition_class_mismatch`.
Start 15:55:55.931 UTC; validation 15:56:09.878 UTC;
monotonic interval 13.953 seconds, including cleanup.

CASE B, turn `f6093267-12b2-4a8e-a44e-9e8982ed58c2`:
provider classification UNSUPPORTED; GREETING [0,10), aircraft [11,39).
GREETING is literally `добрый ден`; `ь` at position 10 is uncovered.
Baseline first rejects with `rejected_decomposition_has_spans`.
After removing classification, it MUST still reject with `invalid_social_span`.
Start 15:56:19.342 UTC; validation 15:56:29.882 UTC;
monotonic interval 10.531 seconds, including cleanup.

Neither completed turn records authoritative read, informational response,
TTS or response TX. Exact baseline replay likewise produces zero reads and no
finalized response. STT was correct; CASE B spans were NOT correct.

ZIP 2: turn `a6b72725-5c97-44ad-a4bd-cace7e2946ba`, same FINAL;
decomposition started 15:57:21.125 UTC; session stopped 15:57:33.054 UTC.
No decomposition result or terminal outcome was saved. NOT OBSERVABLE;
no timeout/cancellation/provider result is inferred.

## Corrected contract and acceptance triangle

Provider describes structure. Core owns route.

New strict JSON output has only `language: "ru-RU"` and `spans` (at most 3).
Each span has strict integer `start` (0..4000), `end` (1..4000), and one act:
GREETING, THANKS_ACKNOWLEDGEMENT, SOCIAL_WELLBEING_QUERY,
AIRCRAFT_IDENTITY_QUERY. Additional properties are forbidden at both levels.
No provider route, aircraft value, response wording, tools or facts.

The runtime REJECTS obsolete classification. Only the test fixture helper
removes it to represent equivalent new-schema output; it never repairs spans.

| Fixture | Origin | Span validation | Core outcome |
| --- | --- | --- | --- |
| Real A | Exact physical payload, classification removed only in test adapter | PASS | FREE_PLUS_AIRCRAFT_IDENTITY; one authoritative read and informational plan |
| Real B | Exact physical payload, classification removed only in test adapter | FAIL: invalid_social_span | No derived route/read/response/TTS/TX |
| Corrected-B | Explicitly SYNTHETIC: A's valid offsets, historical UNSUPPORTED claim | PASS | FREE_PLUS_AIRCRAFT_IDENTITY |

The synthetic fixture is NOT a physical result. No correction is applied to
the real CASE B, either in the stored fixture or in production.

Core validates schema, ordered nonoverlapping source bounds, exact grammar,
meaningful full coverage and allowed intent multiplicity BEFORE route derivation.
The approved pre-existing matrix remains bounded:

| Validated acts | Derived route |
| --- | --- |
| One aircraft act | AIRCRAFT_IDENTITY |
| One aircraft + 1..2 distinct approved social acts, either existing allowed order | FREE_PLUS_AIRCRAFT_IDENTITY |
| 1..2 distinct approved social acts | FREE_ONLY |
| Empty/unknown/excess/duplicate combination | UNSUPPORTED; invalid source/schema rejects before mapping |

Pure whole-utterance aircraft remains deterministic, zero Qwen.
Frozen ownship remains first, zero Qwen. Corrupted FINAL
`какой мой текущий вкус или оригинал` remains unsupported. No fuzzy matching.

## Offline proof and evidence compatibility

`tests/fixtures/hybrid_aircraft_physical_20260908.json` retains original
turn-correlated events, exact FINALs, original classifications/offsets, archive
hashes and session summaries. Synthetic corrected-B is constructed separately
and explicitly labelled in tests, never inserted into those physical events.

`tests/test_hybrid_decomposition_contract.py` covers exact baseline failures,
strict schema, triad, normal host replay (real Core/ToolGateway/presentation
request builder/RadioRouter with fake STT/audio/network), obsolete authority,
closed act matrix, source negatives, unchanged 15-second deadline, timing,
non-fatal observer errors, cleanup propagation, replay and literal source guards.

Existing focused/ownship/golden, authority, informational/protected presentation,
TTS equivalence, Qwen planner, cleanup, truthful STOP, evidence and SRS/Launcher
source-invariance suites remain release gates. Test execution blocks external
network with the existing truthful-STOP offline test guard.

Historical evidence is generic persisted JSONL and remains readable/exportable
unchanged. It is NOT revalidated as the new runtime provider schema. New evidence
stores provider `decomposition` separately from `core_derived_route` on accepted
validation. `status=checking` is not PASS; accepted is PASS, and a `failed` event
with `failure_stage=decomposition_validation` is FAIL.

## Timing — measurement only, no optimization

New observations use the existing explicit Test Session recorder and correlated
turn/session IDs, UTC and monotonic times:

1. decomposition_started;
2. provider_result_received (single request boundary result, before cleanup);
3. cleanup_completed (after the original cancel/cleanup returns or raises);
4. decomposition_validation checking/accepted, or failed with failure stage.

This order preserves the original cleanup-before-Core-validation lifecycle.
On transport timeout/cancellation, the existing request helper returns a
normalized failure result; its category is recorded, not claimed as a received
provider body. No credentials, headers, hidden reasoning or provider bodies are
added. Cleanup errors are re-raised unchanged; observation failures are non-fatal.
Times identify synchronous boundaries, not hidden provider processing phases.
The 15-second deadline is unchanged; mocked 15.001-second completion fails closed.

## Build gate and future field acceptance

One normal Core/Launcher/installer package only, using unchanged packaging.
To obey commit-after-build policy, build from an archived staged Git TREE; after
all offline/package/smoke gates pass, commit exactly that tree. The external
artifact manifest links its source tree to the final commit and file SHA-256s.
Build logs, three isolated non-transmitting smokes, bytecode/source verification
and artifact identity live together under the new contract-fix build directory.
No automatic installation, provider request, DCS/SRS run or physical retest.

Physical status: FIELD RETEST PENDING. No physical PASS is claimed here.

After separate installation/authorization, first test ONLY:
`Добрый день! В каком самолете я нахожусь?`

Require correct FINAL, valid spans, Core-derived mixed route, authoritative
aircraft fact/provenance, exact finalized RU text/TTS input and completed TX with
frame count, plus user acoustic confirmation. Invalid spans must still fail.
If this passes, run frozen ownship `Какой мой текущий курс и координаты?`.
If it fails, stop and inspect captured evidence before another physical attempt.
