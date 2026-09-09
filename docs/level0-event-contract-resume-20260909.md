# Level-0 resume — fixture corrected, static gate STOP

ORION ARCHITECTURE GUARD: OFF

## A. Recovered stop state

Worktree `C:\Users\Алексей\Documents\GitHub\ORION-level0-conversation`,
branch `codex/level0-yandex-event-contract`, unchanged HEAD
`9ccab967dfe018f29302fb87e8105a4bb11a89de`.
Canonical docs remain `d0f58b5693e4a5f7467e32566be88674e24d4001` in
`C:\Users\Алексей\Documents\GitHub\ORION-eod-20260908`.
Read current status/diff, Project Memory, DT403405 record and prior stop receipt.
No reset/stash/discard; all previous implementation and evidence preserved.
This receipt supersedes the prior receipt's fixture blocker, not its history.

## B. Root cause confirmation

Before editing, both affected requests were exercised directly through the
current production adapter and the original stale Fake. Both raised exactly
`user_item_correlation`; submitted text was the current test phrase, close
completed once, and no owned task remained. This expected-negative
characterization PASSED. No provider was involved.

## C. Exact fixture diff

- `tests/test_conversation_prerequisites.py::Fake.__init__`: added explicit
  `echo_submitted=False` opt-in. Deliberately hostile replay fixtures stay intact.
- `Fake.send`: when opted in, copy the actual submitted user item's content into
  the pending user-item acknowledgement. No normalization or static substitute.
- `tests/test_conversation_presentation.py::test_fake_complete_exact_candidate_to_tts_once`:
  opt into request-derived acknowledgement. Existing assertions unchanged.
- `tests/test_level0_event_contract.py::test_request_derived_ack_and_explicit_wrong_ack`:
  eight cases (four current phrases times correct/incorrect ACK), including exact
  copied content and distinct-object assertions. Incorrect ACK must still raise
  exactly `user_item_correlation` with no finalized result.

## D. Production diff

Fixture correction changed NO production bytes. Adapter SHA-256 before/after:
`4320D78D7AFFBB6CAF1ABAC93FE8F4720B85ECBE7F0E28508AB98FB9A891B1CF`.
Earlier unfinished adapter implementation is preserved unchanged.

## E. Before/after correlation proof

BEFORE: requests SOCIAL[1]/SOCIAL[2] + stale SOCIAL[0] ACK -> correlation reject.
AFTER: current submitted user item -> copied ACK -> candidate -> admission ->
fake presentation/TTS/transmit, including the previously failing cases.
NEGATIVE: current input + deliberately different ACK -> correlation reject.
No production assertion, safety invariant, schema or timeout was weakened.

## F. Exact re-run result

Same command as the failed gate:

```text
python -m pytest tests/test_level0_event_contract.py tests/test_conversation_prerequisites.py tests/test_conversation_presentation.py -q
```

**379 passed, 6 warnings in 2.02s**, exit 0.
All original 371 cases pass; eight new correlation cases also pass.
Prior result was 369 passed / 2 failed. The warnings are existing deprecation /
intentional malformed-model fixture warnings, not suppressed by this correction.

## G. Remaining offline regression

Focused Level-0, preserved-sequence reconstructed replay, negative protocol
mutations and admission/authority checks were included in the passing rerun.
The original saved projection is still distinguished from reconstructed fields.

## H. Hybrid / frozen / Qwen / STOP regression

Focused presentation tests include provider-free routing composition and frozen
subsystem byte identity; those pass. The broader regression suite was identified
from the previous prerequisite-regression.xml, but was NOT RUN before the new
static blocker. No broad Hybrid/ownship/Qwen/STOP PASS is claimed for this resume.

## I. Static / quality

Ruff correctness checks: PASS for four experimental conversational runtime
modules and four focused test/fixture files.

Pyright with the existing ORION venv, four conversational runtime modules:
**1 error, 0 warnings**:

```text
orion/yandex_realtime_text_conversation.py:378:46
Argument of type "str | None" cannot be assigned to parameter
"provider_response_id" of type "str" in function "__init__"
(reportArgumentType)
```

This is a static typing error in the previously unfinished production draft,
NOT a fixture error or observed provider behavior. The parser has checked a
response identity on its successful terminal path, but generate's variable is
still statically optional. A prospective minimal repair is explicit checked
type narrowing at candidate construction; it must preserve correlation and
must not broaden the accepted protocol. NOT applied after this gate failure.

Per parent STOP policy: no downstream gates/provider call. Compileall, dedicated
forbidden-import audit, final whitespace/scope gate and broad regression remain
uncompleted. The shell's combined command exit was Ruff's zero; this does NOT
override the explicitly reported Pyright failure.

## J. Final diff audit

This resume adds only test fixture/test changes and this receipt. Earlier
production draft and earlier stop evidence remain untouched. No staged changes.
All NO: Launcher, FullVoiceService, InteractionRouter, SpeechKit STT/TTS, SRS,
RadioRouter, ToolGateway, WorldModel, Hybrid Aircraft, frozen ownship, Qwen
cleanup/Planner, truthful STOP, DCS integration, packaging or configuration.
Final comprehensive diff gate is pending; this is a change inventory, not PASS.

## K. Provider-only gate

Authorization NOT USED. Zero provider calls in both the original tranche and
this resume. The one-call authorization remains conditional on all gates PASS.

## L. Provider result

NOT RUN. No new candidate, authoritative text terminal, audio/tool counts,
admission, cleanup or latency from a real provider. Offline fake results must
not be relabelled as external validation.

## M. Commit / checkpoint

No commit/push. HEAD remains 9ccab967dfe018f29302fb87e8105a4bb11a89de.
Working changes preserved on the dedicated branch. No success marker.

## N. Next step

Resolve only the reported Pyright type-narrowing blocker in the existing draft,
then complete remaining offline/static/diff gates before the one provider call.
This receipt does not apply that repair or claim the tranche complete.
Voice host integration remains a separate future tranche. No build/install/PTT.

## O. Final verdict

LEVEL-0 OFFLINE GATE STILL FAILED — PROVIDER NOT CALLED
