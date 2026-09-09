# Level-0 event-contract correction — offline gate STOP, 2026-09-09

ORION ARCHITECTURE GUARD: OFF

This is an incomplete working-tree checkpoint, NOT an implementation PASS.
No provider request, build, install, host integration, commit or push was made.
Stop required by prompt section 48 / failure policy section 72. No assertions
were weakened and no timeouts were increased after the failure.

## A. Recovered baseline

- Worktree: `C:\Users\Алексей\Documents\GitHub\ORION-level0-conversation`.
- New isolated branch: `codex/level0-yandex-event-contract`.
- Unchanged HEAD: `9ccab967dfe018f29302fb87e8105a4bb11a89de`.
- Canonical recovery docs: `d0f58b5693e4a5f7467e32566be88674e24d4001`,
  `C:\Users\Алексей\Documents\GitHub\ORION-eod-20260908`.
- Both original branch refs matched direct GitHub ref checks before changes.
- Frozen Hybrid runtime `f0c9e364ed653e9497d7e2ef8ef8f35dc97157d4`;
  doc freeze `dca668d530dc6cbc4de05064400b22c2216ada3f`.
- Broader ORION development worktree and all pre-existing artifacts untouched.

## B. Context

The Level-0 experiment was already committed clean at 9ccab967, not still seven
untracked files. It remains unwired. Historical Qwen conversation evidence is
not authorization to import its old speech-to-speech stack. Existing Hybrid,
ownship and source/provenance boundaries remain frozen. Source labels silent
by default remains the approved policy; this tranche does not change the
frozen runtime's historical spoken source prefix.

## C. Support contract

Reuse canonical `docs/history/2026-09-09-yandex-support-DT403405.md` at d0f58b56.
Text-only generation may acknowledge text+audio capabilities. Null audio
envelopes are structural; audio.delta is actual audio. output_text.done is
authoritative. Support reproduced behavior but did not inspect our old session.
Question 2 remains non-blocking pending clarification. The old blocker is closed.

## D. BEFORE characterization

Passed expected-negative offline characterization: original adapter rejected
the reconstructed historical multimodal session.updated with `nontext_session`;
one fake close, no owned task, zero network. This is not a fresh provider result.

## E–L. Implemented draft protocol contract

- E: one request/session/response; text capability separate from generated audio.
- F: only production file changed: `orion/yandex_realtime_text_conversation.py`.
  `_TextOperation` adds correlated parsing; `_identifier`, `_capabilities`,
  `_no_audio_payload` validate envelopes. `generate` delegates parsing and adds
  timestamp observations and terminal cancellation checks. No new provider or
  owner. Remaining risk: incomplete offline validation and no live contract gate.
- G: created/updated session identity, unique events, valid text capability.
- H: one response identity, assistant item, output/content binding, completion.
- I: exact delta equality and output_text.done; no strip or normalization.
- J: known structural audio envelopes with absent/null/empty audio permitted.
- K: any audio.delta (including empty) or actual audio field rejected; no decode.
- L: user input echo checked exactly; assistant empty-to-content progression
  bound to the same item; tool/system/wrong-item events rejected.

## M. Authority isolation

No change to conversational eligibility, SocialDraft, Core admission,
INSTRUCTIONS, Planner, ToolGateway or facts. Raw protocol text is not admission.
Unsafe synthetic candidates remain rejected after a valid protocol replay.

## N. Cancellation / cleanup

Existing connection/task/close budgets unchanged. Added terminal cancellation
checks prevent returning a candidate when cancellation races text completion,
response completion or close. Focused fake cancellation/close tests passed;
broader Qwen/STOP regression was not run after the failed aggregate gate.

## O. Exact offline result and first failing boundary

Command (canonical existing Python environment):

```text
python -m pytest tests/test_level0_event_contract.py tests/test_conversation_prerequisites.py tests/test_conversation_presentation.py -q
```

Result: **2 failed, 369 passed, 6 warnings in 2.23s**, process exit 1.
Failure nodes preserved also by `.pytest_cache/v/cache/lastfailed`:

- `test_conversation_presentation.py::test_fake_complete_exact_candidate_to_tts_once[Сегодня как-то непросто летится.]`
- `test_conversation_presentation.py::test_fake_complete_exact_candidate_to_tts_once[Что-то я сегодня не в форме.]`

Both fail line 52: expected one fake TTS/transmit, actual zero. Code establishes
the earlier cause: line 48 constructs `events(SAFE[SOCIAL.index(text)])` without
its new explicit `source` argument. `events` defaults that argument to SOCIAL[0]
(`Что-то сегодня полёт тяжело идёт.`). These two requests use SOCIAL[1]/SOCIAL[2].
Their fake user-item acknowledgement therefore does not match the requested
source. `_TextOperation.feed` rejects `user_item_correlation` before generating
a candidate; presentation correctly does not call fake TTS. The first variant
passes. This is an incomplete migration of OFFLINE fixtures, not observed
Yandex behavior or a production voice-stack defect.

Minimum prospective correction: pass the current `text` explicitly as the
fixture's source at that test callsite. Do NOT change the matching assertion,
production admission, voice behavior or deadlines. NOT applied after STOP.

## P. Preserved-sequence replay

`tests/level0_protocol_fixture.py` preserves 28-event order and historical
12 text deltas, anchored to original projection SHA256
`C45012C772FBB45D5B5B1C0B30135401548046D08A5127980B7A90A1088E6DAD`.
Missing content/item/audio/transcript bodies are explicitly reconstructed with
DT403405 audio:null semantics, NOT claimed raw captured fields. Historical plain
prose passes protocol replay but fails SocialDraft schema, intentionally.
Synthetic structured variants are labelled separately and pass exact admission.

## Q. Negative mutations

Focused tests passed for bad/missing/duplicate capabilities, audio payloads in
all tested envelopes, audio delta even empty/late, tool/VAD/unknown events,
session/response/item/content mismatch, duplicate terminals, missing done,
text mismatch/bounds/whitespace, bad completion, unsafe admission and cancellation.
The sealed parser rejects events after response.done in direct replay. Runtime
closes at its single terminal; this does not claim observation of unread events
after that terminal. No post-terminal drain or persistent session was added.

## R–T. Frozen regressions

- R: presentation file's existing provider-free routing tests and byte-identity
  check passed in the focused run. Full Hybrid regression NOT RUN.
- S: ownship code untouched; full ownship regression NOT RUN.
- T: Qwen cleanup and truthful STOP code untouched; broader regression NOT RUN.

## U. Static gates

NOT RUN after focused gate failure: broader regression, Pyright, Ruff,
compileall, diff whitespace gate and dedicated forbidden-import gate. No static
PASS is claimed. Read-only Git status/diff inventory was inspected for this receipt.

## V–W. Provider gate and timings

NOT RUN. Zero connection/request/retry/provider calls in this tranche.
No new model result, admission, provider latency, audio or physical latency
claim. Historical measurements are not substituted for this gate.

## X. Change audit

Production changes limited to the experimental text adapter. Focused fixture
changes in `tests/test_conversation_prerequisites.py`; new fixture and mutation
tests in `tests/level0_protocol_fixture.py`, `tests/test_level0_event_contract.py`.
This receipt is documentation only. Nothing staged.

All NO: Launcher, FullVoiceService, InteractionRouter, SpeechKit STT/TTS,
SRS protocol/transport, RadioRouter, ToolGateway, WorldModel, Qwen Planner,
truthful STOP, Qwen cleanup, DCS integration, packaging. INSTRUCTIONS, Core
admission and closed grammar unchanged. No installed/runtime configuration edits.

## Y. Checkpoint / next step

No implementation commit, docs commit or push. HEAD remains 9ccab967.
Working changes and failed-test evidence preserved; do not treat as validated.
The success marker ORION_LEVEL0_TEXT_CONTRACT_VALIDATED_HOST_INTEGRATION_NEXT
is NOT set. Resume only at the failed fixture boundary; all required gates must
subsequently pass before the still-unconsumed one provider gate. Host integration
is not authorized here and is not yet ready.

## Z. Stop

Offline fixture protocol mismatch blocks the current gate. This is not a newly
discovered provider failure. Stop before remaining gates, provider call or commit.
