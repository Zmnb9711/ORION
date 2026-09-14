# Foundation Step 1 — routing collapse only

ORION ARCHITECTURE GUARD: OFF

User-authorized Step 1 implementation; NOT commit/build/Step 2 authorization.
Contract: [ORION_NATURAL_LANGUAGE_FIRST_CONTRACT_V1](../architecture/ORION_NATURAL_LANGUAGE_ARCHITECTURE_CONTRACT.md), unchanged.
Worktree: `C:/Users/Алексей/Documents/GitHub/ORION-level0-conversation`.
Branch: `codex/general-natural-language-ingress-tranche1`.
Parent/HEAD: `be413a802fe4d84ac140db248219b3e450cbb8b4`; no commit created.
Starting tracked/index state clean; existing `data/` preserved.

## Scope and exact route

Before: FINAL -> bounded ownship -> Hybrid aircraft/social/decomposition ->
eligible_conversation -> separate ConversationVoice OR GeneralSemanticVoice.

After: FINAL -> existing whole-turn ownship -> existing whole-turn pure aircraft
-> clean miss/ambiguous/partial/social/mixed -> ONE GeneralSemanticVoice entry.
No local finalized response is emitted before General. The complete same FINAL
object/text reaches it; provider wire receives the exact source text.

Production changes are confined to two files:

- `orion/full_voice_service.py::_voice.answer`: request `full_turn_only=True`;
  bypass separate Conversation imports/branch and LOCAL_SOCIAL observation;
  retain the existing General block, context epoch, owner and shutdown literally.
- `orion/hybrid_aircraft_core.py::run/_run`: optional routing-only flag, default
  false for old execution/helper callers; production abstains before social
  decomposition. Existing exact whole-source aircraft classifier is unchanged.
  The miss is still registered in the bounded replay ledger, required by
  `run_semantic_identity` before its single-use Core admission. No grant,
  provenance, permission, factual mapping or output checks are weakened.

## Fast-path disposition

| Component | Step 1 disposition |
|---|---|
| FullVoiceCore / bounded ownship | KEEP full-turn fast path, same executor/output |
| classify_aircraft_identity_query / pure aircraft | KEEP existing full-turn match |
| Hybrid factual tail / run_semantic_identity | KEEP execution helper and same Core grant path |
| eligible_decomposition / recognize_local_decomposition / local social composition | KEEP helper code, REMOVE from production language admission |
| eligible_conversation / separate ConversationVoice | REMOVE from this host's admission; retain implementations/tests |
| GeneralSemanticVoice | Existing single General entry; no prompt/provider/contract change |

Mixed reaches the existing typed semantic contract, but Mixed execution remains
NOT_IMPLEMENTED/truthful unavailable. Previously local canned mixed/social
composition is deliberately no longer the host policy; historical helper behavior
is retained and tested independently. This is not a claim of preserved mixed
user-facing output or recovered Conversation quality. Pure aircraft and the
AI-selected authoritative aircraft tail remain reachable and tested.

## Offline proof

`tests/test_foundation_routing.py` covers real FullVoiceService routing with
fake FINAL/provider wire/Gateway fixture/PCM/radio I/O. It verifies:

- ownship and pure aircraft: no General operation, one factual read/response;
- unknown, conversational, ambiguous and partial/mixed RU/EN fixtures: exactly
  one General entry/request/wire response.create, exact original text/identity;
- forbidden local decomposition and separate Conversation cannot be invoked;
- valid typed MIXED is observed, with no local factual read/partial response;
- one TTS/RadioRouter admission, duplicate General replay rejected before another
  operation/response; Hybrid cached replay/conflict and cancellation preserved;
- AST equivalence outside the host answer/import removal and the exact Hybrid
  routing flag/abstention: lifecycle/factual executor code stays unchanged;
- no new production string literals/phrases, regex, synonyms or recognizers;
- exact two-file production scope and unchanged complete-file freeze elsewhere.

Existing multi-turn host tests now exercise General instead of the removed
per-turn Conversation owner: success, provider failure, malformed terminal, TTS
failure, evidence failure, inactive evidence and STOP during provider wait,
followed where applicable by the unchanged pure-aircraft factual turn.
Protocol/TTS/radio are fakes; no actual provider request or physical transmission.

Old test expectations for LOCAL_SOCIAL and historical decomposition admission
are explicitly revised; helper contract tests are retained, not silently skipped.
`tests/general_ingress_hashes.json` changes only the two reviewed runtime hashes;
the new independent AST/scope test constrains those changes against `be413a8`.

## Validation

- Before change: targeted 117 PASS / 3 SKIP; full suite 3258 PASS / 5 FAIL / 3 SKIP.
- Expanded routing/host/helper regression: 224 PASS / 1 SKIP.
- Targeted Pyright (both runtime files and new routing tests): 0 errors/warnings.
- Full production Pyright: 199 baseline errors before and after; not a global PASS.
  Initial invocation without explicit Python path could not resolve dependencies;
  reported results use the existing ORION `.venv` interpreter explicitly.
- Ruff, compileall and diff whitespace checks: PASS.
- Final full suite: 3281 PASS / the same 5 baseline FAIL / 1 SKIP (3287 cases).
  No new failures. JUnit: `C:/Users/Алексей/AppData/Local/Temp/orion-foundation-step1-01f2e469a0194658af3dc81cbabded58/regression.xml`.
  The remaining skip is frozen-ownship in the aircraft-only cancellation fixture;
  frozen-ownship cancellation/replay has separate unchanged coverage.

Five baseline failures, not fixed by this task:
`test_interaction_contracts::test_only_approved_architecture_boundaries_import_ia0_contracts`;
`test_setup_wizard_model::{test_manual_dcs_and_saved_games_advance_deterministically,
test_changing_dcs_invalidates_saved_games_and_ready_state,
test_auto_detect_candidate_invalidates_previous_ready_state}`;
`test_srs_packaging::test_project_memory_requires_exact_integrated_field_artifact`.
The fifth reflects a stale pre-governance text expectation, not a runtime change.

User-data check: `data/fa18c_value_profiles.json` is unchanged (SHA-256
`4975e243ee95fdf997ccc5ecc4537eaff87947265c1c9a7f876ecf3ccee15c1f`).
The original 89938 bytes of ignored `data/events.jsonl` retain SHA-256
`12106361001bbfccfbd9162f551609f1a3de34c63294c7115df40812953d41e9`;
the test suite appended generated events. They are retained, not cleaned up.
Contract SHA-256 remains `de59126cb79efc010996f4f8357ab80b641109b7ed3cd60ccbc7856d53c2a128`.

## Evidence levels and stop

CODE / OFFLINE PASS / fake-I/O real-HOST PASS only. Provider PASS, physical TX
PASS, ACOUSTIC PASS and USER BLIND FIELD PASS: NOT RUN / NOT CLAIMED.
No installer, build, DCS/SRS/PTT, live provider, architecture expansion or commit.
Existing TTS defects remain unresolved; Step 2 and all later work require review.
