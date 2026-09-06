# Full voice milestone: implementation-readiness evidence

Historical recovery baseline: `9362f18bd320da8e92daf6b680d68cfd08c6b8ad`.
Authorized read-only voice reference: `42520a57b01cd314978bcb51bdf4bbc75b38c156`.
Architecture Guard is OFF by the historical-line exemption. This document is
not a new stage, a field pass, or a claim that the milestone is implemented.

## Observations on 2026-09-07

### Official local SRS / UDP7082

The official `SR-ClientRadio.exe` was running from the installed SRS Client
directory. An exclusive localhost UDP7082 receiver obtained 40/40 valid
CombinedRadioState snapshots in eight seconds. Intervals were approximately
187–219 ms. Radio index 1 reported 251000000 Hz, modulation 0 (AM).
`RadioSendingState` provided boolean `IsSending`, integer `SendingOn`, and
integer `IsEncrypted`; the initial state was false, 1, 0.

A subsequent observation recorded false at +110 ms, true at +3750 ms, and
false at +7188 ms, with SendingOn=1 and IsEncrypted=0 throughout. The user's
later clarification stated that PTT had not been used and that an installed
Yandex SRS voice runtime was already active. Therefore these transitions are
retained as observations, NOT accepted as an unambiguous user physical-turn
field pass. Isolation and explicitly correlated user confirmation were initially open.
No microphone audio was captured by these observers; neither invoked STT or TX.
Sockets were closed after each bounded observation.

After the user stopped installed ORION, an isolated 58-second window received
288 snapshots but no sending transition. It was not counted as a PTT pass.
A subsequent bounded 180-second observer was confirmed ready before prompting
the user. It received 195 snapshots and observed false at +0 ms, true at
+34750 ms, false at +39187 ms: radio 1, no encryption, 4437 ms held PTT.
This isolated observation passed, and its socket closed immediately afterward.

### SpeechKit v3 STT transport and auth

One bounded actual RecognizeStreaming readiness call used the existing Windows
Credential Manager key, recovery-imported protobuf/transport, general/ru-RU,
mono LINEAR16 PCM at 16000 Hz, disabled text normalization, and external EOU.
The input was the existing known Russian source WAV, paced in 40 ms blocks.
112824 PCM bytes were submitted. The provider returned exactly one FINAL and
one EOU_UPDATE, final_index=0, with matching received/final/EOU cursors of
3400 ms. Terminal barrier latency after EOU was 311.786 ms. The final contained
35 characters and the expected lexical markers. No early final was observed.
The provider cursor is NOT asserted to equal the submitted sample duration.
Resources were closed; no credentials or raw provider body were recorded.
This is transport/auth readiness, not the yet-unimplemented integrated turn gate.

### Core ownership

Recovery `orion/app.py::store_telemetry` updates the shared
`orion/live_telemetry_store.py::live_telemetry`; `store_heartbeat` updates that
same owner. `orion/app.py::lifespan` acquires the actual UDP bridge and closes it
on exit. `orion/world_model.py::WorldModelFacade` defaults to that shared owner;
the exported `world_model` is its shared facade. A dedicated recovery host must
use this existing ownership chain, reject a conflicting bind, and validate fresh
ownship facts before enabling a turn. It must not construct a separate empty
telemetry owner or consume facts from the installed later Core.

The installed `ORION-Core.exe` PID 37228 was observed owning localhost UDP45100.
It has not been stopped by the assistant. Runtime isolation remains required
before starting the recovery field host; installed Launcher/voice status is not
evidence that the recovery host owns live DCS state.

The user subsequently closed installed Launcher/Core. The dedicated recovery
live owner acquired UDP45100, received a NEW DCS packet (generation 1), and
reported heading and position KNOWN through the shared recovery world_model.
Its listener was then closed. Existing secure Qwen configuration was successfully
loaded from `C:/Users/Алексей/AppData/Local/ORION/runtime` without logging secrets.

### Protected streaming TTS compatibility

The authorized later helper transforms text with `.strip()`; that transformation
must NOT be imported. One bounded v3 StreamSynthesis compatibility call sent the
exact string `Fly heading zero three seven.` with voice john, speed 1.0, raw
LINEAR16 PCM at 48000 Hz. The request boundary was checked for exact equality.
No role or text/language rewrite was added. Result: gRPC OK, 226938 PCM bytes,
even length, one audio chunk, first PCM at 2359.0 ms. No SRS TX or playback was
performed; no new acoustic user confirmation is claimed. The call and channel
were closed. This proves protocol/voice compatibility, not sub-second latency
or a functioning bounded streaming radio implementation.

## Offline checks

- `tests/test_srs_tx_state.py`: 11 passed.
- Existing `test_world_model`, `test_live_telemetry_handshake`,
  `test_speechkit_tts_adapter`, `test_protected_presentation`, and
  `test_phraseology_renderer`: 113 passed; one existing Starlette/httpx warning.
- An initial test invocation included nonexistent test paths and collected no
  tests; the corrected invocation above passed.

At the initial readiness checkpoint only isolated untracked reference files had
been added. Implementation subsequently proceeded; its current status and
unresolved provider semantic gate are recorded in `full-voice-implementation-status.md`.
No commit, push, START LIVE change, or full user-spoken field closure has occurred.
Existing unrelated untracked artifacts are preserved.
