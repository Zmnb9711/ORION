# Level-0 response-ID correction — static PASS, historical scope gate STOP

ORION ARCHITECTURE GUARD: OFF

## A. Recovered stop state

Branch `codex/level0-yandex-event-contract`, worktree
`C:\Users\Алексей\Documents\GitHub\ORION-level0-conversation`.
HEAD remains `9ccab967dfe018f29302fb87e8105a4bb11a89de`.
Canonical recovery docs remain `d0f58b5693e4a5f7467e32566be88674e24d4001`
at `C:\Users\Алексей\Documents\GitHub\ORION-eod-20260908`.
Current diff, Project Memory, DT403405 checkpoint and previous stop records
were recovered. Previous fixture fix and all unfinished changes preserved.
No reset/stash/discard. This receipt closes the previous Pyright blocker only.

## B. Exact Pyright error before correction

Previously captured at `orion/yandex_realtime_text_conversation.py:378:46`:
`str | None` cannot be passed to `provider_response_id: str`
(`reportArgumentType`). One error, zero warnings.

## C. Root cause

`generate` initializes response_id to None and subsequently copies
`operation.response_id`. `_TextOperation.feed` returns terminal text only after
validating the active response identity, but the type checker cannot infer that
relationship between a return value and a separate mutable attribute. Testing
`done_text is not None` alone does not narrow the local response_id type.
No larger ownership/correlation defect was established at this boundary.

## D–E. Chosen fix / exact incremental production diff

Added only this two-line fail-closed guard immediately before setting terminal
and constructing ConversationalCandidate in `generate`:

```python
if not isinstance(response_id, str) or not 0 < len(response_id) <= 200:
    raise ConversationFailure("response_correlation")
```

No cast, type ignore, assertion, invented ID, fallback, schema or timeout change.
All earlier adapter implementation work is preserved. For the whole original
tranche the sole changed production file remains
`orion/yandex_realtime_text_conversation.py`: bounded protocol assembler,
capability/audio-envelope validation, correlation, terminal cancellation checks
and timing observations. No new connection/session owner or voice wiring.

## F. Semantic response-ID invariant

1. Only `response.created` supplies the active ID through `_identifier`.
2. The ID must be a nonempty string of at most 200 characters.
3. Duplicate response.created is rejected by `_once`.
4. All subsequent response events, including text terminal and response.done,
   must match the active response ID; item/output/content binding is checked.
5. Candidate construction is reached only after completed response.done,
   authoritative output_text.done and exact text-representation consistency.
6. The added guard explicitly revalidates the copied ID at construction and
   narrows its type to str. Missing ID uses the existing normalized failure path.

## G. Negative response-ID tests

Existing missing/wrong/duplicate-response mutation tests retained unchanged.
Added four invalid observed IDs (None, empty string, integer, oversized string):
no admission, fake TTS or fake radio transmission; clean close.
Added parser fault injection that loses identity immediately after its normal
terminal validation: the NEW construction guard raises exactly
`response_correlation`, no candidate returned, no finalized result.

## H. Static results

- Pyright with actual existing ORION venv, four conversational runtime modules:
  **0 errors / 0 warnings / 0 informations**.
- Ruff correctness scope: four conversational runtime modules, four focused
  test/fixture files: **PASS**.
- compileall for the same scope: **PASS**.
- git diff --check: **PASS**. Git CRLF conversion warnings are not failures.

No checks were suppressed. Dedicated final forbidden-import/scope admission
gate was not completed after the later regression failure.

## I. Focused offline re-run

Same three-file gate:

```text
python -m pytest tests/test_level0_event_contract.py tests/test_conversation_prerequisites.py tests/test_conversation_presentation.py -q
```

**384 passed, 6 warnings in 2.09s**. All prior 379 cases plus five new tests PASS.
Includes reconstructed historical event-order replay, hostile protocol
mutations, admission/authority and corrected fixture correlation tests.

## J. Remaining regression result and exact blocker

Executed the prior prerequisite-regression.xml suite inventory (26 test files),
plus current event-contract tests, ownship semantic middle, phraseology renderer,
response composer, RadioRouter and radio contracts. Entire run completed:

**1260 passed / 3 failed / 4 skipped / 31 warnings in 43.75s**.

Machine result:
`C:\Users\Алексей\Documents\ORION-Builds\level0-event-contract-20260909\offline-regression.xml`

SHA-256: `F6A5B132E0C559090A993BF668DBC0EE6392348436778661210A86A37014A392`.

Three failures, all at historical Git file-scope allowlists:

| Test / assertion line | Historical comparison base |
|---|---|
| test_hybrid_decomposition_contract.py::test_gate11_literal_span_checks_and_frozen_sources :306 | 4ca5effe2c5772a3268ba1f131bbad77a095c7ea |
| test_hybrid_host.py::test_gate11_no_unapproved_production_delta :156 | 474d11bc |
| test_hybrid_local_routing.py::test_exact_source_invariance :170 | 013a36a956cb67565290c506c0e7bda0a89fdf24 |

In every failure the only extra paths beyond that historical allowlist are:

- orion/conversational_contracts.py
- orion/conversational_core.py
- orion/conversational_presentation.py
- orion/yandex_realtime_text_conversation.py

Git proves all FOUR were already committed by the input baseline 9ccab967,
dated 2026-09-08 23:33:04 +03:00 (`preserve unwired Level-0 experiment`).
Read-only `git diff <each historical base> 9ccab967 --name-only` independently
produces the same four extra paths WITHOUT this working-tree correction.
This establishes a historical scope-assertion/baseline incompatibility, not a
new change to Hybrid semantics or a Yandex behavior failure. It does not turn
the failed gate into PASS. No allowlist was broadened or test skipped to proceed.

The symbol/AST invariance assertions preceding the failing file-scope assertions
in decomposition/local-routing tests passed. Other observed groups:

- Hybrid Aircraft 87 PASS; seams 67 PASS; decomposition 41 PASS + 1 FAIL;
  host 20 PASS + 1 FAIL + 4 SKIP; local routing 267 PASS + 1 FAIL.
- Ownship semantic middle 29 PASS; full_voice/full_voice_srs 35 PASS.
- Planner 27 PASS; Yandex Qwen planner 22 PASS; Qwen cleanup 36 PASS.
- Truthful STOP 4 PASS; voice STOP lifecycle 11 PASS.
- Phraseology 30 PASS; response composer 35 PASS; protected presentation 32 PASS.
- Radio contracts/router 34 PASS; ToolGateway 23 PASS; WorldModel 16 PASS.

## K. Diff audit

`git diff 9ccab967 --name-only -- orion dcs-export packaging` returns ONLY the
experimental text adapter. Frozen subsystem byte-identity tests also pass.
This resume adds two production lines and focused negative tests, plus this
receipt; it does not alter the three historical failing tests.

All NO: Launcher, FullVoiceService, InteractionRouter, SpeechKit STT/TTS,
SRS, RadioRouter, ToolGateway, WorldModel, Hybrid Aircraft, frozen ownship,
Qwen Planner/cleanup, truthful STOP, DCS integration, packaging/configuration.
Contracts, admission and DT403405 modality/audio policies unchanged by this fix.
Final comprehensive provider-admission diff gate is NOT declared passed.

## L–M. Provider authorization / result

Authorization **NOT USED**. Zero provider calls, retries, fallback or second turn.
No external input/model/response ID/candidate/audio count/admission/cleanup/latency
result exists for this tranche. Offline outcomes are not external evidence.
No DCS/SRS/PTT, SpeechKit, audio device, build or installation action.

## N. Commit / checkpoint

No new commit or push. HEAD remains 9ccab967. Working changes and machine failure
evidence preserved; no success marker or claim of host-integration readiness.

## O. Next step

Resolve applicability of the three historical file-scope gates to the already
committed Level-0 baseline, preserving their historical frozen-symbol protection
and strict current-tranche scope. This requires a separately bounded correction
or explicit gate-policy direction; it was NOT implemented after the STOP.
Do not change production voice behavior to address a historical test allowlist.
All required gates must pass before consuming the one provider authorization.

## P. Final verdict

LEVEL-0 STATIC/OFFLINE GATE STILL FAILED — PROVIDER NOT CALLED
