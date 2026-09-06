# Stage 7C — protected SpeechKit-to-radio path

Status: IMPLEMENTED / AUTOMATED GATES PASS / FIELD VALIDATION REQUIRED.
Architecture Guard: OFF for this explicitly authorized historical recovery line.

## Baseline and source boundary

Worktree: `C:\Users\Алексей\Documents\GitHub\ORION-recovery-a955d7c`.
Branch: `recovery/a955d7c-radio-validated`.
Required and verified pre-edit HEAD: `052fb122e06b6f79666c09ff09a54e946f561c91`.
Tracked and staged diffs were empty; Git object integrity passed. Existing
untracked `data/fa18c_value_profiles.json` was preserved. No ORION/Core/DCS/SRS
process was found at preflight. No such application was started or killed.

Sources are this exact historical tree, its tests/docs, the prior preflight,
and the verified direct v1 en-US/john capability and human 037 pronunciation
confirmation. No later history, implementation or Architecture Guard decision
was inspected/imported. The existing dependency interpreter is reused only as a
runtime; repository imports and subprocess PYTHONPATH point to the recovery tree.

## Components and ownership

- `orion/speechkit_tts_adapter.py`: extracted historical HTTP/session/retry and
  48-to-44.1 kHz normalization helpers, plus a bounded protected adapter.
- `orion/yandex_hybrid_probe.py`: imports the extracted helpers and retains its
  existing Russian probe behavior, cases, Realtime arm and UI integration.
  The new protected path does not call that arm or the legacy request builder.
- `orion/protected_presentation.py`: one-event-loop service owning TTS operations,
  correlation and admission; borrows an existing RadioRouter.
- `orion/protected_presentation_probe.py`: explicit separate CLI, direct TTS mode,
  and six-case field mode. It hosts the existing SRS endpoint/adapter/Router;
  never creates a Realtime session, Qwen request or microphone capture.
- Three new focused test modules correspond to these components.

Flow: actual Stage 7A renderer -> actual Stage 7B composer -> finalized protected
text + injected resolved RadioContext -> direct TTS -> validated 48 kHz PCM ->
existing normalization -> FinalizedPcmAudio -> one Router submit -> existing SRS
adapter/TX worker -> correlated terminal result.

No changes to renderer, composer, communication/radio contracts, Router internals,
SRS adapter/protocol/RadioInfo/registration/readiness, Opus, 44.1-to-16 kHz
resampling, framing, 40 ms pacing, half-duplex or PTT semantics. Launcher and
normal production voice workflows are unchanged.

## Admission and exact text

Strictly revalidate frozen finalized/context models and reject unchecked mutation
or normalization. Accept one protected fragment, no envelope, no advisory, the
existing pilot ICAO profile and explicit en-US only. Reuse composer validation and
compare its result to the input; never substitute its result as rewritten text.
No normative ICAO compliance is claimed: these remain synthetic pilot rules.
Historical fragments do not carry an independent render-language/profile witness;
the service validates available finalized context and existing composer policy,
not metadata absent from the historical contracts.

The exact Python string goes to the protected form builder. Form-decode tests
assert both string and UTF-8 equality, including boundary whitespace, decomposed
Unicode and punctuation. No strip, normalization, translation, naturalization,
SSML, language inference, default voice or fallback. Request parameters are fixed:
`lang=en-US`, `voice=john`, `format=lpcm`, `sampleRateHertz=48000`, `speed=1.0`.
Endpoint: `https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize`, Api-Key auth.
Production keys are loaded only by the runner via Windows Credential Manager.

## Bounds, PCM and transport

- Request: finalized contract limit 4096 characters, URL-encoded body <=15 KiB.
- Response: streamed 64 KiB chunks; success <=2,880,000 bytes (30 seconds mono
  PCM16LE at 48 kHz). Reject oversize, never truncate audio. Error inspection is
  limited to 2048 bytes and never exposed in protected public errors.
- Require an appropriate binary/PCM content type, nonempty even byte length;
  reject recognizable container/text prefixes. Raw PCM is not self-describing:
  arbitrary even-length binary cannot prove sample rate, encoding or intelligibility.
  Declared request/response contract and the acoustic gate supply that assurance.
  Prefix rejection is deliberately conservative, not a general audio detector.
- Reuse unchanged `normalize_speechkit_pcm` / StreamingPcm16Resampler. Construct
  FinalizedPcmAudio at 44100 Hz mono PCM16LE only after validation; its existing
  2,646,000-byte bound is enforced. No SRS resampling/Opus/pacing changes.
- Shared session, redirects disabled on protected calls; 5-second connect timeout
  and an overall <=30-second synthesis deadline including session opening,
  requests and retry backoff. Three attempts maximum; 250/750 ms backoff.
- Retry timeout/connection/transient body failure and 429/500/502/503/504 only.
  No retry on 400/401/403, TLS validation error, malformed request, invalid PCM
  or cancellation. Legacy probe behavior remains on its compatibility hooks.

## Identity, radio, failures and lifecycle

Original interaction UUID -> `p7c-<interaction_id.hex>` throughout TTS attempts,
presentation, RadioTransmissionRequest and completion. Retry changes attempt
number only. Validate injected domain, priority and optional interaction against
finalized context; require the deterministic TX ID. Preserve/merge source refs
within the historical provenance bound. No frequency/entity/coalition/WorldModel
resolution occurs in the service.

Same identity + exact finalized/context signature shares one in-flight task or
returns its existing result. Conflicting reuse fails closed. Keep at most 64
lifetime identities without eviction (new identities then fail capacity); this
is a bounded session ledger, not persistent cross-process replay protection.

Only submit after validated normalized PCM. Never resynthesize/resubmit after
acceptance, a throwing/ambiguous submit, timeout or completion. A queued/active
Router snapshot after the <=45-second wait is nonterminal, not success. `get`
can later observe terminal completion without resubmission. Missing/unreadable
accepted state is `unknown`, nonterminal RADIO_ERROR. Only completed is success.

Public result/error objects contain typed codes, safe identity/state, no raw
provider exceptions, protected text, PCM, credentials or headers. Failures cover
all requested admission, TTS, PCM, radio, cancellation/shutdown and replay cases.

`cancel(tx)` cancels owned request/backoff before radio; an explicit scheduling
point prevents submission if cancelled after PCM. After admission it delegates
to Router.cancel. Unsupported active SRS cancellation remains active/unsupported;
it never stops the whole session. Shutdown closes admission, cancels owned tasks,
awaits/ closes TTS within a configurable <=5-second deadline (default 2), and
does not shut down the borrowed Router. Returns false if accepted radio remains
nonterminal. The standalone runner, as runtime owner, subsequently stops its own
endpoint. Callers must use a cooperative async TTS port and a single event loop.

## Privacy and evidence

Service diagnostics retain at most 1024 allow-listed events with correlation,
attempt/timing/byte counts and normalized status. No text, protected values,
provider body, headers, keys or PCM are logged. The runner uses a separate Stage
7C JSON report in a new temporary directory, not IA-1.1 evidence. It filters
legacy endpoint diagnostics and never writes their normal JSONL text/error sink.
RX is drained/discarded solely to keep the existing endpoint healthy; no RX or
microphone recording/provider upload. Explicit synthetic field WAV capture is
opt-in and is pre-SRS 44.1 kHz audio, not proof of reception through SRS.

Machine gate requires all six exact cases in order; matching request hashes;
en-US/john and bounded PCM; unique identities; one synthesis success, submission,
Router enqueue/start/complete, adapter start/complete and SRS start/complete per
case; no duplicate, endpoint error or retry after admission. A machine PASS is
never a human acoustic PASS.

## Automated validation

71 new focused tests passed. Full isolated historical suite: 1614 passed
(1543 historical + 71 new), with the existing Starlette/httpx deprecation warning.
Includes Stage 7A/7B/contracts, Router/SRS, hybrid probe and IA/interaction tests.
The offline six-case integration uses actual renderer/composer/service/Router/
SRS adapter and TX worker; HTTP and socket/codec boundaries are fake. Tests also
reject altered, incomplete, duplicated and reordered evidence. Ruff across
orion/tests and Pyright across touched files plus ten historical CI targets pass.

Full-suite Windows account discovery was isolated by an external test-only
Known Folder plugin and fresh USERPROFILE/LOCALAPPDATA, as documented for 7A/7B;
dedicated discovery fixtures still apply. No unrelated test was changed. One
optional whole-suite coverage run finished all 1612 tests but failed combining
branch/statement coverage from subprocesses; the clean no-coverage rerun exited
successfully. No whole-suite coverage percentage is claimed.

## Physical field gate — user execution only

The implemented direct adapter gate passed on 2026-09-06 for both exact requests:
`Fly heading zero three seven.` (226,938 PCM bytes) and
`Laser code zero one five seven.` (287,124 PCM bytes). Both were HTTP 200,
en-US/john, bounded even-length PCM16LE mono 48 kHz, with no request mutation.
Report and two synthetic WAVs were retained outside the repository in
`C:\Users\Алексей\AppData\Local\Temp\orion-stage7c-z4hn86qw`.
This verifies provider synthesis, not physical SRS reception. No radio ran.

First review the two direct-TTS WAVs returned in the implementation report.
Do not proceed to radio if either direct TTS result failed. Stop the normal ORION
voice session yourself to avoid a competing transmitter; do not kill unrelated
processes. Prepare the existing controlled DCS/SRS test setup and official SRS
Client on the agreed AM frequency. Supply the current server host, port, controlled
frequency in Hz and transmitting callsign; do not change ORION configuration.
The runner reads the existing SRS EAM password and Yandex API key securely.

In PowerShell, use the installed dependency interpreter and explicitly select
recovery imports. This command is a template: replace the four test-target values
with the existing authorized SRS setup before the final invocation.

```powershell
Set-Location -LiteralPath 'C:\Users\Алексей\Documents\GitHub\ORION-recovery-a955d7c'
$env:PYTHONPATH = 'C:\Users\Алексей\Documents\GitHub\ORION-recovery-a955d7c'
$stage7cPython = 'C:\Users\Алексей\Documents\GitHub\ORION\.venv\Scripts\python.exe'
& $stage7cPython -m orion.protected_presentation_probe --list-cases
$stage7cServer = Read-Host 'Current controlled SRS server host'
$stage7cPort = [int](Read-Host 'Current SRS server port')
$stage7cFrequency = [double](Read-Host 'Controlled AM frequency in Hz')
$stage7cCallsign = Read-Host 'Test transmitter callsign'
& $stage7cPython -m orion.protected_presentation_probe --field --confirm-transmit-six --host $stage7cServer --port $stage7cPort --frequency-hz $stage7cFrequency --callsign $stage7cCallsign --capture-synthetic-audio
```

This final command explicitly transmits SIX sequential synthetic cases, no parallel
submissions; next starts only after terminal completion and a 250 ms guard.
It stops on the first failure/nonterminal result. Do not rerun a failed/ambiguous
run automatically: each new CLI invocation has new identities and will transmit
again. Inspect evidence and wait for confirmed radio completion first.

Expected text, in exact order:

1. `Fly heading zero three seven deg.` — hear zero-three-seven.
2. `Frequency 264.500 MHz.` — frequency unchanged and understandable.
3. `TACAN 44X.` — 44X distinguishable.
4. `Laser code zero one five seven.` — hear zero-one-five-seven.
5. `Altitude correction -850 ft.` — negative sign meaning preserved.
6. `Heading unavailable.` — no invented heading.

Verify through the official SRS Client: all six audible; no clipping, acceleration,
distortion, overlap or wrong order. Return the printed evidence directory's
`report.json` plus one human PASS/FAIL per case and any audio defect. WAVs are
optional synthetic aids, not microphone/RX evidence. The runner always leaves
`human_review=REQUIRED`; closure requires review of machine AND human evidence.

## Stop boundary

No Realtime presenter, mixed/social envelope, broad PresentationRouter, normative
KB, STT/PTT redesign, domain migration/expansion, entity registry, voice profiles,
DCS Voice Chat, Launcher redesign, WorldModel/ToolGateway/planner changes or radio
rewrite. No push/merge or automatic DCS/SRS launch. Stop after the focused commit
and implementation report; Stage 7C is not CLOSED before physical validation.
