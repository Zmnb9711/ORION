# Frozen full-voice latency measurement (no optimization)

## Baseline and scope

Production baseline: `05c832762a73ed38f98984942227dbdee1e89ef3`, branch
`codex/fallback-20260906-1800`. Entry check: clean tracked/staged/untracked tree;
local/origin ahead-behind 0/0; live remote branch SHA matched. The frozen
declaration remains in `recovered-working-checkpoint.md` unchanged.
Architecture Guard OFF for the expressly authorized historical line.

This change measures, not repairs, the already field-validated path. It does
not import discarded productionization or latency/evidence implementations.
No Launcher, service owner, START/STOP, configuration, provider options,
semantic rules, protected text, PCM buffering, radio algorithms or installer
architecture changes. No audio capture or new Test Session UI/export feature.

## Existing observability inspected before edits

| Boundary | Frozen symbol / existing observation | Profile boundary |
|---|---|---|
| T0 | `PhysicalRadioTurn.snapshot` `_end`; `FinalizedUserUtterance.physical_end` | Accepted official UDP7082 sending true-to-false edge, before drain |
| T1 | `NativeSpeechKitTurns.accept` `final_received` | Accepted native FINAL |
| T2 | `FinalizedUserUtterance.barrier_closed`; existing `stt_core_boundary` wall time at later host handoff | Future completed after matching FINAL/External EOU |
| T3 | `FullVoiceCore._run` `interaction_started` | Core run starts, before InteractionRouter execution |
| T4 | `FullVoiceCore._run` `composed` | Exact protected composition completed |
| T5 | `StreamingProtectedPresentation._run/produce` `tts_started` | Finalized text about to enter TTS stream |
| T6 | No existing mark at actual client RPC invocation | `ProtectedStreamingTts.stream`, immediately before `method(...)` |
| T7 | presentation `tts_first_pcm` | First validated nonempty PCM chunk yielded by TTS |
| T8 | `FullVoiceSrsEndpoint.transmit_srs_stream` `radio_started` | Adapter streaming entry accepted (stream lock held), before prebuffer/physical guard |
| T9 | endpoint `radio_first_frame`; existing `srs_tx_started` wall log | First `send_voice` returned successfully |
| T10 | endpoint `radio_completed`; existing `tx_completed` wall log | TX pacer and final-frame duration completed |

Existing host/Test Session logs did not persist all in-memory boundaries.
The successful previous turn's 2.658 s was wall-clock **STT handoff to first
SRS frame**, not PTT-release-to-audible latency. No exact hardware button or
headphone onset timestamp exists.

## Why high-resolution hooks are necessary

Direct runtime inspection on this Windows/Python environment returned:

- `get_clock_info('monotonic')`: `GetTickCount64()`, resolution `0.015625` s.
- `get_clock_info('perf_counter')`: `QueryPerformanceCounter()`, resolution
  `0.0000001` s; monotonic, not adjustable.

The existing marks establish semantics but are not high-resolution enough for
the requested small adjacent intervals. They are deliberately NOT replaced.
Eleven scalar QPC observations are placed next to these boundaries. T6 fills
the missing RPC boundary. This is not a second competing runtime timer.

`full_voice_timing.observe` reads `perf_counter` before recording into the
existing bounded, explicit Test Session buffer. It catches observer exceptions.
`realtime_test_evidence._ALLOWED_FIELDS` adds only `perf_counter_seconds`.
The pre-existing export persists these events; no filesystem operation was
added to any callback. Normal non-Test-Session operation retains no new events.
No text, PCM, credentials, provider bodies or headers are supplied to this hook.

T0-T7 carry the existing turn ID; T8-T10 carry the existing `p7c-<UUID hex>`
response ID. The existing `stt_core_boundary` supplies runtime/session/turn
correlation; Test Session ID is attached by the recorder. Only the TTS observer
turn ID is passed from presentation to the TTS object (no request alteration).

## Interpretation and limits

- All duration subtraction uses `perf_counter_seconds` within one Core process
  and correlated turn. Never subtract QPC from `monotonic` or UTC timestamps.
- Event `timestamp` is recorder wall-clock correlation, not the precise boundary.
- T0 is ORION accepting the official client's falling-edge snapshot, not the
  physical switch sample. Client reporting/network/dispatch delay before that
  observation is not measured. The existing drain delay is included after T0.
- T1 is native adapter acceptance of FINAL, not provider server generation.
- T6 is client RPC invocation, not DNS/TLS completion or server receipt. T6-T5
  includes local channel/method preparation. Network setup and provider work
  inside T7-T6 cannot be separately ranked without evidence; do not guess.
- T8 is adapter entry, not the earlier Router submit call nor successful first
  frame permission. Radio admission precedes PCM production in this runtime;
  T8-T7 may be negative. T9-T8 overlaps TTS generation, so do not sum overlapping
  durations or classify that whole interval as independent radio overhead.
- T9 is first local frame send, not arrival at the user's headphones.
- Missing/failed boundaries remain UNKNOWN; do not infer or retry a failed turn.
- Recording overhead is nonzero, bounded scalar work; tests establish functional
  equivalence, not zero perturbation or identical wall-clock execution.

## Offline proof / field procedure

`tests/timing_oracle.py` enumerates each permitted added source fragment. Removing
only those exact fragments must reproduce the frozen and golden components.
`full_voice_service.py` remains literally frozen. Existing Launcher/Core/SRS
lifecycle invariants still compare against the historical Launcher baseline.

Differential replay executes both the exact frozen runtime and exact golden
field host against the instrumented runtime, using identical PCM and explicit
FINAL fixtures (not live ASR). It compares STT options/audio, finalized utterance,
Core result, bounded semantic values, protected/TTS text, call order and STOP.
Supported Russian ownship and unsupported queries retain their exact outcomes.
Separate tests compare actual TTS stream calls, serialized requests, PCM bytes,
exceptions and cancellation; actual deterministic SRS packet sequence/count;
bounded memory, privacy, export and failing observers. No provider/PTT calls.

Pre-build validation: **120 passed**, one pre-existing FastAPI/TestClient
deprecation warning. Focused set: `test_full_voice_timing`,
`test_stt_core_observation`, `test_fallback_baseline`, `test_full_voice`,
`test_full_voice_srs`, `test_realtime_test_evidence`,
`test_fallback_voice_equivalence`, `test_recovery_stream`, `test_srs_transmission`.

After offline proof: one instrumented artifact, source/archive/install identity
verification, existing non-transmitting smoke, then normal installed Launcher.
Do not alter DCS/SRS settings. Enable existing Test Session before the first turn.
Use: «Какой мой текущий курс и координаты?» Only user PTT/speech/acoustic report
is manual. The agent exports and reads existing automatic evidence.

At most two turns. A second is allowed only after complete successful first-turn
timing and acoustic confirmation and only for a useful cold/warm comparison.
STT opens its persistent stream at normal startup; it is already open for a
turn and reused for a second turn in that runtime. TTS creates a fresh channel
and RPC per response. Neither behavior is changed or deliberately warmed.
Actual lower-level DNS/TLS/cache/server warmth remains unknown unless observed.

Field results and artifact identity are pending. Do not mark this document as
measurement completion. No optimization or profiling push is authorized.
