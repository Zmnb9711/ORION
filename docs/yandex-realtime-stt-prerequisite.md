# Isolated Yandex Realtime STT prerequisite

Historical recovery only; Architecture Guard OFF by explicit authorization.
This is **not** the full bidirectional voice milestone. No production integration.

## Verified baseline

- Branch: `recovery/a955d7c-radio-validated`.
- Initial HEAD: `72625dc68481826d66c03d7a0719322804258282`.
- Subject: `docs: close Stage 7C as field validated on recovery line`.
- Date: `2026-09-06T23:45:32+03:00`.
- Tree: `6680d69c2ae81b93231fad2e7b61974f02456958`.
- Upstream: `origin/recovery/a955d7c-radio-validated`; local cached divergence 0/0;
  no fetch. Tracked/staged diffs empty before work; object integrity PASS.
- Existing untracked `data/fa18c_value_profiles.json` preserved;
  SHA-256 `4975E243EE95FDF997CCC5ECC4537EAFF87947265C1C9A7F876ECF3CCEE15C1F`.
- `docs/history/2026-09-06-stage-7c-field-validation.md`: Stage 7C CLOSED /
  FIELD VALIDATED, machine PASS and human acoustic PASS 6/6.
- Sources: this exact tree and its documentation/tests only; no later history.

## Why this exists / protocol evidence

The existing `YandexRealtimeSession._handle_event` can observe
`conversation.item.input_audio_transcription.completed` (`transcript`, optional
`item_id`), but historical evidence allowed a transcript to be NOT OBSERVABLE.
That is insufficient for mandatory future IA-6 input.

`orion/yandex_stt_adapter.py` reuses only protocol construction helpers from
`orion/yandex_realtime_provider.py`: URL, authorization, session update, input
audio append. Endpoint: `wss://ai.api.cloud.yandex.net/v1/realtime`; existing
model `speech-realtime-260528`, existing `Api-Key` authentication. Configuration
uses existing ru-RU input languages, PCM rate 44100, server VAD. No invented
transcription configuration or generation-suppression flags. Existing provider
session behavior is not changed and the production session class is not reused.

## Contract / ownership

`YandexRealtimeSttAdapter(api_key, folder_id, deadline_s=15)` owns only its fresh
HTTP/WebSocket session. `transcribe(pcm, interaction_id, ..., cancellation=None)`
returns immutable `SttResult`; exactly one of failure or `FinalTranscript`.
`shutdown()` stops admission and closes owned resources; one event-loop owner,
one operation at a time (concurrent admission returns BUSY).

- PCM16LE, mono, 44100 Hz, bytes/bytearray/memoryview, nonempty even byte length.
- Maximum 10 seconds / 882000 bytes; reject overflow; no truncation/resampling.
- Mutable caller audio is snapshotted once; 20 ms append chunks, last chunk exact;
  no adapter-generated silence, padding, translation, or automatic audio replay.
- Fixed ru-RU; no autodetect or English/bilingual expansion.
- Caller UUID is retained, not replaced by provider identity.
- Frozen `FinalTranscript`: interaction_id, text (excluded from repr),
  input_language, provider_id, optional provider_item_id, UTC started_at /
  finalized_at, final=True. Nonblank text <=4000 characters; original text is
  retained without repair. No fabricated confidence.

## Finality and generated-output isolation

Only the exact input-transcription completed event can supply a result.
Input deltas, silence/VAD, assistant items, response text/audio and tool requests
cannot become a transcript. No audio decoding, tool execution, output callback,
Core/WorldModel/IA-6/Planner access, radio or Stage 7A/7B/7C imports in the adapter.
The existing session may still generate output: this is programmatic isolation,
not a promise of server-side generation suppression.

Exactly one return per operation. Identical final text/item repeats are deduped;
conflicting text or another input item before terminal state fails closed.
After first final, a bounded 100 ms settle window collects queued repeats and
conflicts within the overall deadline; then the operation seals and closes.
No guarantee is made about arbitrary future events: after sealing they cannot
change the result and are not delivered. No unrelated text concatenation.

## Bounds, failures, cancellation, privacy

One session, one audio submission; **no retries**, including after connection
failure. Overall connection/setup/audio/event deadline <=15 s. Cleanup adds at
most 2 s WebSocket close + 2 s HTTP close; shutdown waits at most 5 s for owned
worker cleanup. Successful result requires local WebSocket/HTTP closure and
drained owned tasks; close-handshake status is a separate diagnostic.
Cancellation before connection, during setup/submission/wait returns CANCELLED,
closes resources and cannot expose a late final. After shutdown: SHUTTING_DOWN.

Normalized failures: INVALID_AUDIO, AUDIO_TOO_LARGE, UNSUPPORTED_LANGUAGE,
CONNECTION_ERROR, AUTH_ERROR, PROVIDER_REJECTED, PROVIDER_ERROR,
FINAL_TRANSCRIPT_TIMEOUT, EMPTY_FINAL_TRANSCRIPT, TRANSCRIPT_TOO_LARGE,
CONFLICTING_FINAL_TRANSCRIPT, CANCELLED, SHUTTING_DOWN, BUSY, INVALID_OPERATION.
No final means failure, never promotion of a partial/generated response.

Per-event limit 262144 bytes; aggregate event limit 4194304 bytes / 1024 events;
diagnostic ring <=128 fixed-category records. Normal diagnostics/errors contain
only UUID, category, counts and closure status: no transcript, PCM, raw provider
payload, credentials, headers or arbitrary exception strings. Credentials are
supplied in memory, never persisted by the adapter. Test transcript storage is
allowed only as explicitly opted-in known-phrase evidence outside the repository.

## Validation

### Automated gates

- Focused adapter: 43 passed (including cancellation at four phases, duplicate /
  conflicting finals, no-final timeout, input/event bounds and output isolation).
- Historical suite: 1656 passed, one environment-default test deselected, in
  20.06 s. That test passed separately in its two-test file with normal defaults
  (2 passed in 0.15 s). All 1657 distinct tests therefore have passing evidence.
- Realtime/Yandex, IA-1 presentation, Stage 7A/7B/7C, SRS/radio and IA/interaction
  regressions are included in this historical suite; no real DCS/SRS execution.
- Ruff whole `orion` / `tests`: PASS. Pyright new module/test plus all ten
  historical CI targets: 0 errors / warnings. Tracked and new-file whitespace
  checks: PASS. Existing Starlette/httpx deprecation warning remains unrelated.
- Environment detail: initial run had 29 API startup failures because another
  process already owned UDP 45100 (WinError 10048), with 1628 passed. No process
  was stopped. Test-process-only telemetry port 0 / command and mission port 9
  removed the collision; one defaults assertion then correctly rejected the
  test environment override, hence its separate unmodified-default run.
- Regression uses historical external Saved Games isolation plugin, temporary
  USERPROFILE/LOCALAPPDATA and external event log. No product config changes.

### Single real capability gate — NO-GO

Executed 2026-09-07 with explicit known-transcript capture opt-in. Exactly one
source TTS request and **one STT operation**, no retry, no subsequent live calls.

- Known source: `Какой мой текущий курс и координаты?`.
- Existing SpeechKit v1 ru-RU / jane / neutral generated temporary source audio;
  existing resampler normalized source to 44100 Hz outside the STT adapter.
  The recorded source includes a 0.5 s silence tail; adapter added nothing.
- WAV PCM16LE mono 44100 Hz; duration 3.525714 s; PCM 310968 bytes;
  WAV 311012 bytes; SHA-256
  `a071deada59e1722ae6924c60c67e48f86e4b47423f801e27a5d82e373070a02`.
- Caller UUID `ed0edbe5-9b35-4687-af53-e757ec9ee717` is present throughout the
  bounded event diagnostics. Connected, session ready, one complete audio
  submission, and actual `conversation.item.input_audio_transcription.completed`
  accepted internally with 35 characters. Two generated/item event records were
  discarded; none forwarded, zero output callbacks.
- Operation result: `provider_error`, `session_closed_cleanly=false`, 3.687 s.
  Adapter shutdown subsequently returned true with no active worker; this is
  **not** evidence of a clean prior provider-session close.
- No successful public FinalTranscript was released. Actual candidate text was
  not retained after fail-closed cleanup, so actual transcript, final-result
  correlation and IA-6 lexical compatibility are NOT VERIFIED. The false marker
  fields in the report mean no released text was available, not that the real
  provider omitted those words. No text repair or InteractionRouter call.
- The actual input-final event was observed: this result does **not** establish
  that the provider lacks final transcription. The blocking evidence is failed
  session-closure validation and therefore no usable validated public result.
  No raw close code / reason was captured; underlying closure cause remains
  undetermined. No protocol workaround or lifecycle change was attempted after
  this failed gate, in accordance with the stop condition.
- **NO COMMIT at the first gate.** Files were retained for separately authorized review.

Temporary evidence (not committed):

`C:\Users\Алексей\AppData\Local\Temp\orion-stt-prerequisite-8bd50fbcc91349888c6e70a553bf3aad`

Files: `capability_gate.py` (explicit opt-in, one-shot locks), `source.json`,
`known-russian-source.wav`, `report.json`, `regression-final.xml`; earlier
environment-failure reports are preserved. Credentials, headers and provider
raw bodies are not written. That initial result did NOT validate the prerequisite;
the separately authorized lifecycle investigation follows below.

## Separately authorized session-closure forensic / minimal fix

Baseline reverified at the same HEAD with empty tracked/staged diff and valid
objects. Original failed-attempt files copied without modification to:

`C:\Users\Алексей\AppData\Local\Temp\orion-stt-closure-96a25b80c7b44c65b2a584ab5941bdcf`

Pre-fix SHA-256:

- adapter: `037EEE7D9CB1087455522FDDB8694F6FC36664880318CBA28EEF65AA4E5891E5`
- tests: `A37D06776F874E627BBCF36A0E022BD3A56F84515171AC13DE40C23DDBBCCD13`
- doc: `AC50C42673F3624774716C5074DC9F0A57ED793DE3A53963C0E0AF50A191A52D`

### Root cause: D (timeout policy) with B (close expectation)

The first divergence is expiration of `asyncio.wait_for(receive(), remaining)`
in the 100 ms duplicate/conflict window. It cancels the underlying receive.
The installed aiohttp 3.14.3 runtime's `ClientWebSocketResponse.receive` sets
`_close_code = ABNORMAL_CLOSURE` (1006) on cancellation/timeout. Its `close`
then closes the response immediately if a close code is already set; it does
not replace that synthetic 1006 with an acknowledged 1000.

This was reproduced BEFORE the fix with real aiohttp on a local loopback server:
valid input final, WebSocket closed=true, HTTP closed=true, close_code=1006,
old adapter rejects success. The new loopback regression was red before the
fix and green after it. No provider request was needed. The original real report
did not capture close code/resources/timestamps, so per-frame retrospective
certainty is unavailable; the exact adapter/runtime defect is independently
proven, not evidence that Yandex lacks final transcription or leaked resources.

### Corrected ordering and publication rule

Keep the 100 ms duplicate/conflict window unchanged. Wait on an owned receive
task with non-cancelling `asyncio.wait`. At window expiry seal the operation,
initiate WebSocket close (aiohttp explicitly supports waking an active reader),
close the HTTP session, then drain the reader. There is no independent sender,
retry or backoff task. A bounded cleanup task is shielded from caller cancellation
and awaited before public return. No generated output callback was added.

Success requires genuine validated input final, no conflict or fatal error before
sealing, no cancellation, and verified local WebSocket/HTTP closure plus ended
reader. Normal remote close 1000/1001 after final is accepted. Abnormal remote
close before sealing is CONNECTION_ERROR. Optional semantic close events are not
required. A local handshake timeout/code warning AFTER sealing does not itself
invalidate final text if all local resources are actually closed. An unclosed
resource fails closed; a boolean semantic event cannot substitute for closure.

Precedence: cancellation (including during cleanup) returns CANCELLED after
cleanup; otherwise retain the first specific protocol/auth/provider/finality
failure. Cleanup failure adds PROVIDER_ERROR only if no prior failure exists.
Cleanup warnings remain diagnostics when actual closure succeeds. After sealing,
late generated/lifecycle/final data cannot change or produce a second result.

Emergency ceilings remain 15 s operation, 2 s WS + 2 s HTTP cleanup, 5 s shutdown;
these are NOT acceptable voice latency budgets. No blind timeout increase.

### Monotonic latency instrumentation

Seven timestamps: connection_started, connection_ready (setup acknowledged),
first_audio_sent, last_audio_sent, final_transcript_received (before settling),
cleanup_started, cleanup_completed. Derived metrics use differences of these
monotonic clocks, in milliseconds: connection setup; first-to-last audio append;
last audio append to final; cleanup; total operation. Source duration is separate.
No transcript/body/credential is included in normal metrics or diagnostics.

Classification: <=300 ms EXCELLENT, <=500 GOOD, <=800 MARGINAL, >800 PROBLEMATIC
FOR <1s E2E. Performance classification is not a hard functional acceptance gate.
This prerecorded probe submits chunks without real-time pacing; its post-last-
append metric does not prove microphone/PTT-release to audible response latency.

### Deterministic gates before the single retest

58 focused tests PASS, including actual aiohttp loopback local close, remote close,
missing close ACK/timeout with local resource closure, fatal error precedence,
real resource failure, cancellation during cleanup, no leftover owned tasks,
duplicate/conflicting finals, late data and monotonic metric calculations.
Historical suite: 1671 PASS / one defaults test deselected (21.27 s); that test
passes separately in its two-test file (2 PASS, 0.11 s). All 1672 distinct tests
have passing evidence. Same external account/port isolation as described above.
Realtime/Yandex/IA-1/7A/7B/7C/radio/SRS/interaction included. Ruff PASS; Pyright
new files + ten historical CI targets: zero errors/warnings; whitespace PASS.

### Single real retest

Functional **PASS**, 2026-09-07. Exactly one newly authorized STT operation;
original hash-verified WAV reused, no new synthesis. No DCS/SRS/Core invocation.

- Operation UUID: `84a68f28-9337-4aa7-bc2d-0653e3a1bd40`.
- Actual public input final: `какой мой текущий курс и координаты` (35 chars).
- Event: `conversation.item.input_audio_transcription.completed`.
- Auxiliary item: `ae35ef57-5e54-4908-90ea-b618970021f7`.
- Caller UUID preserved. Existing `курс` / `координат` markers both present
  after existing normalization, with no repair or InteractionRouter invocation.
- Exactly one session and one full 310968-byte audio submission; source duration
  3.525714 s. No retry, playback, microphone, output callback or radio integration.
- Independent observation: WebSocket, HTTP ClientSession and connector all
  closed; no extra pending tasks; adapter active=false; shutdown=true.
- **Close code 1006 remains a warning**, not a normal peer close-handshake claim.
  Local cleanup was independently proven. No fatal provider event was observed
  before sealing. The successful local-loopback fix does not prove the peer's
  reason for 1006 in this real run; that cause is not captured. The corrected
  separation of actual resource closure from handshake metadata is material.
- Generated/other events discarded: 2. Generated audio/text/tool event counts:
  0/0/0 in the observed pre-seal window; no output forwarded. Events after sealing
  are not interpreted or counted as production output.
- Normal diagnostics contain no transcript, raw bodies/audio, headers or keys;
  the known test transcript is present only in explicitly opted-in evidence.

Monotonic timestamps (seconds, process clock; not UTC):

| Milestone | Value |
| --- | ---: |
| connection_started | 428934.390 |
| connection_ready | 428935.765 |
| first_audio_sent | 428935.765 |
| last_audio_sent | 428935.765 |
| final_transcript_received | 428938.078 |
| cleanup_started | 428938.187 |
| cleanup_completed | 428938.546 |

Measured connection/setup: **1375 ms**. Audio submission span: **0 ms at the
sampled clock resolution**, not a claim of physically instantaneous transport.
This Windows Python reports monotonic `GetTickCount64()` resolution 15.625 ms;
sub-tick audio-submission duration is unresolved, not fabricated precision.
Post-last-audio finalization: **2313 ms**. Post-final settle: **109 ms**.
Cleanup: **359 ms**. Total adapter operation: **4156 ms**.

Performance: **PROBLEMATIC FOR <1s E2E**. STT finalization alone exceeds 800 ms
and jeopardizes the <1000 ms end-of-utterance to audible response objective for
this measured path. Do not subtract WAV duration from operation time: audio was
submitted as a prerecorded burst, not paced microphone input. A functional PASS
is not a latency PASS or proof of user-spoken DCS/SRS end-to-end performance.
One observation is not a latency distribution or a reliability claim.

Evidence in the closure temporary directory: `retest.py`, `source.json`,
`one-retest.lock`, `retest-report.json`, `regression.xml` and the original adapter /
test / doc snapshots. Earlier failed evidence is unchanged. No audio, credentials
or temporary reports are added to Git. All functional gates now authorize the
single focused adapter/tests/documentation commit, with no push or merge.

## Explicitly not implemented

SRS RX/TX integration, radio changes, inbound coordinator,
Transcript -> InteractionRequest, SemanticResponse -> OSU, ownship phraseology,
Stage 7C live reuse, Launcher / START LIVE, user-spoken DCS/SRS field gate.
Existing Realtime, Stage 7A/7B/7C, IA-6, Planner, ToolGateway and WorldModel
remain unchanged. Any subsequent milestone requires separate authorization.
