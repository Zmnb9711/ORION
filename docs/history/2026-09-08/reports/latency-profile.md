# Full-voice latency profile — 2026-09-08

ORION ARCHITECTURE GUARD: OFF

## Outcome

Two permitted physical turns completed end-to-end; user confirmed both answers
were heard clearly. Each transmitted 385 frames. No third turn, optimization,
provider retry, additional build, configuration change or push.

Machine-observed response start: **3389.0998 ms** and **3039.4132 ms**.
Largest measured contributor: TTS client RPC invocation to first valid PCM,
**2898.5331 ms** and **2537.8177 ms**. This interval includes network/connection
and provider work; these components cannot be separated by this profile.

## Frozen baseline and artifact

- Branch: `codex/fallback-20260906-1800`.
- Frozen HEAD: `05c832762a73ed38f98984942227dbdee1e89ef3`.
- Entry tree clean, origin 0 ahead / 0 behind, remote identity verified.
- Measurement HEAD: `18a3a79917292a15792b7c9b412c638e77fd03f1`.
- Measurement tree: `d14b0085c901dd23f408c7d4c460bd11524b19bb`.
- Final repository clean; 1 ahead / 0 behind local origin tracking reference.
- One source-archived build, one installer, one installation; no push.
- Installed Launcher: `C:/Program Files/ORION/Launcher/ORION-Launcher.exe`.
- Installed version: `0.2.0-alpha`; identity is established by hashes/source
  manifest, not by this nonunique version string.
- Installer: `installer/ORION-Alpha-0.2-Setup.exe`, 84095740 bytes.
- Installer SHA-256: `6b28e7cbe8cc3341023f27eaadbafee58b2395691f5b354ad47716b411b79d44`.
- Source archive SHA-256: `b1b06ad30c9d65bfee3f62daf9be0161a5f17541a35963106e750685c9ac6af8`.
- `artifact-identity.json`: 709 archived files unchanged; all 325 Core and 317
  Launcher ORION module origins match archived source; 3267 installed files match.
- Core/Launcher executable hashes rechecked before field START LIVE: match.
- Installed native/control/integrated non-transmitting smoke: PASS.

## Existing observations and minimal hooks

Repository: `C:/Users/Алексей/Documents/GitHub/ORION-fallback-20260906-1800`.
All paths below are relative to that repository, with source line references
at measurement HEAD.

| Boundary | Existing frozen observation | Measurement location |
|---|---|---|
| T0 | PhysicalRadioTurn._end / physical_end | orion/full_voice_capture.py:94, PhysicalRadioTurn.snapshot |
| T1 | final_received | orion/full_voice_stt.py:183, NativeSpeechKitTurns.accept |
| T2 | barrier_closed; later wall-time stt_core_boundary | orion/full_voice_stt.py:221, native FINAL/EOU future completion |
| T3 | interaction_started | orion/full_voice_core.py:95, FullVoiceCore._run |
| T4 | composed | orion/full_voice_core.py:122, FullVoiceCore._run |
| T5 | tts_started | orion/protected_streaming_presentation.py:39, produce |
| T6 | No actual RPC-invocation timestamp | orion/protected_streaming_tts.py:58, ProtectedStreamingTts.stream |
| T7 | tts_first_pcm | orion/protected_streaming_presentation.py:44, produce |
| T8 | radio_started | orion/full_voice_srs.py:105, transmit_srs_stream |
| T9 | radio_first_frame / srs_tx_started | orion/full_voice_srs.py:169, transmit_srs_stream |
| T10 | radio_completed / tx_completed | orion/full_voice_srs.py:180, transmit_srs_stream |

Existing in-memory marks were not all exported and used GetTickCount64 with
15.625 ms resolution. Eleven QPC observations were therefore added beside
the boundaries without replacing existing timers; T6 additionally fills the
missing RPC boundary. QPC resolution reported by this environment: 0.0000001 s.

`orion/full_voice_timing.py:11` captures perf_counter and records through the
existing bounded explicit-Test-Session memory buffer, catching observer
exceptions. `orion/realtime_test_evidence.py:23` allows the scalar field.
Presentation passes only observation_turn_id to the TTS object. No added
await, file write, timer, queue, provider parameter, PCM or text transformation.

## Offline proof and changed files

120 tests passed, one pre-existing dependency deprecation warning. Differential
replay uses frozen05 and golden57 with identical PCM/FINAL fixtures, supported
and unsupported queries, coalition and missing metadata cases. It compares
call order, native utterance fields, Core result, protected/TTS text, STT/TTS
options, PCM, exceptions, cancellation and STOP. Actual deterministic SRS
tests compare packets, sequence and count. Exact-source-fragment oracle proves
only the enumerated observation additions differ. Launcher and service-owner
lifecycle invariants remain intact. No provider calls in offline proof.

Production changes are exactly the eight `orion/` files in the map/helper
description above. Additional changed files:

- `docs/frozen-full-voice-latency-measurement.md`
- `tests/fallback_voice_replay.py`
- `tests/test_fallback_baseline.py`
- `tests/test_fallback_voice_equivalence.py`
- `tests/test_full_voice_timing.py`
- `tests/test_stt_core_observation.py`
- `tests/timing_oracle.py`

Focused suite: test_full_voice_timing, test_stt_core_observation,
test_fallback_baseline, test_full_voice, test_full_voice_srs,
test_realtime_test_evidence, test_fallback_voice_equivalence,
test_recovery_stream, test_srs_transmission.

## Field evidence and correlation

Installed normal Launcher, live F/A-18C telemetry, user's existing SRS setup,
251.000 AM. Same voice runtime for both turns:
`905e8eaaf21d4e83a8f84d6cb88957f7`.

Evidence root: `C:/Users/Алексей/AppData/Local/ORION/runtime/test-evidence`.

| Run | Test Session | Turn | ZIP |
|---|---|---|---|
| 1 | c3e60b2fb0774a5d8fcd8c1be167d45c | 47613e3e-3cbb-4ec3-8e8a-5d576d743f76 | ORION-Test-Evidence-20260908-123259.zip |
| 2 | e778258e81ac470a874384d98fd46adc | 7cbef17b-a1d8-41e7-bd1c-1af42a53f1a6 | ORION-Test-Evidence-20260908-123800.zip |

Both exact finalized transcripts: **какой мой текущий курс и координаты**.
Both boundary outcomes: FinalizedUserUtterance; protected response produced,
first PCM and first frame observed, 385 frames and completed TX, user acoustic
confirmation clear. All eleven timestamps appear once per turn. T0-T7 use
turn UUID, T8-T10 use `p7c-` plus the same UUID without hyphens.

ZIP event counts: 151 and 153; dropped counts both zero; one user transcript
each. Existing ZIP metadata says `orion_build_sha=unknown`; it is not embedded
source attestation. Source linkage instead uses verified installed artifacts.
No assistant transcript/source coordinates or audio WAV were added/captured.
These samples do not independently re-audit numerical response fidelity.

Detailed runtime log:
`C:/Users/Алексей/AppData/Local/ORION/runtime/srs-radio/srs-radio-905e8eaaf21d4e83a8f84d6cb88957f7.jsonl`.
First-frame/TX-completion lines: run1 74/90-91; run2 217/234-235.

## Full timing tables

Timestamps are QPC seconds; deltas are milliseconds rounded to 3 decimals.
UTC recorder correlations for T0/T9/T10:
run1 12:31:51.532 / 12:31:54.921 / 12:32:10.329;
run2 12:34:13.353 / 12:34:16.393 / 12:34:31.807, 2026-09-08 UTC.
UTC is not subtracted from QPC.

### Run 1

| Boundary | QPC seconds | Delta from previous, ms | Delta from T0, ms |
|---|---:|---:|---:|
| T0 observed TX end | 569220.5146192 | — | 0.000 |
| T1 accepted FINAL | 569220.9351694 | 420.550 | 420.550 |
| T2 FINAL/EOU complete | 569220.9353176 | 0.148 | 420.698 |
| T3 Core start | 569220.9953007 | 59.983 | 480.682 |
| T4 protected response | 569220.9977062 | 2.406 | 483.087 |
| T5 TTS text handoff | 569220.9986000 | 0.894 | 483.981 |
| T6 TTS RPC invocation | 569220.9988005 | 0.200 | 484.181 |
| T7 first valid PCM | 569223.8973336 | 2898.533 | 3382.714 |
| T8 radio adapter admission | 569221.0000483 | -2897.285 | 485.429 |
| T9 first frame sent | 569223.9037190 | 2903.671 | 3389.100 |
| T10 TX complete | 569239.3098959 | 15406.177 | 18795.277 |

### Run 2

| Boundary | QPC seconds | Delta from previous, ms | Delta from T0, ms |
|---|---:|---:|---:|
| T0 observed TX end | 569362.3213133 | — | 0.000 |
| T1 accepted FINAL | 569362.7470415 | 425.728 | 425.728 |
| T2 FINAL/EOU complete | 569362.7472278 | 0.186 | 425.914 |
| T3 Core start | 569362.8143687 | 67.141 | 493.055 |
| T4 protected response | 569362.8158927 | 1.524 | 494.579 |
| T5 TTS text handoff | 569362.8165568 | 0.664 | 495.244 |
| T6 TTS RPC invocation | 569362.8167419 | 0.185 | 495.429 |
| T7 first valid PCM | 569365.3545596 | 2537.818 | 3033.246 |
| T8 radio adapter admission | 569362.8175843 | -2536.975 | 496.271 |
| T9 first frame sent | 569365.3607265 | 2543.142 | 3039.413 |
| T10 TX complete | 569380.7730399 | 15412.313 | 18451.727 |

T8 precedes T7 because radio consumption starts concurrently with TTS. Negative
T8-T7 is real ordering, not negative physical latency. T9-T8 includes waiting
for TTS PCM; it is not an independent 2.5–2.9 second radio overhead.

## Aggregate breakdown

| Interval, ms | Run 1 | Run 2 |
|---|---:|---:|
| T2-T0 observed turn end to finalized utterance | 420.6984 | 425.9145 |
| T4-T2 finalized utterance to protected response | 62.3886 | 68.6649 |
| T7-T5 protected text to first PCM | 2898.7336 | 2538.0028 |
| T9-T7 first PCM to first sent frame | 6.3854 | 6.1669 |
| T9-T0 machine-observed response start | 3389.0998 | 3039.4132 |

Contributors ranked without overlapping intervals: TTS time to first PCM;
observed turn end to FINAL/EOU (~421–426 ms, including existing drain);
handoff to Core start (~60–67 ms); first PCM to first frame (~6 ms);
Core processing itself (~1.5–2.4 ms); remaining local handoffs below 1 ms each.
The 15.4-second T9-T10 response transmission duration is not startup latency.

Two-sample response-start mean: 3214.2565 ms; range 3039.4132–3389.0998 ms.
Measured values exceed 1000 ms by 2389.0998 and 2039.4132 ms. No optimization
was attempted. The first observed TTS wait was 360.7154 ms longer; two samples
do not establish why or demonstrate a cold/warm causal effect.

## Connections, limits and end state

STT stream was created by normal START LIVE, already open before run1, and
reused for run2 without runtime restart. SRS connection likewise reused.
TTS code creates a fresh channel/RPC per response and closes it afterwards;
run2 is not a reused TTS channel. No deliberate warm-up/preconnection occurred.
DNS/TLS transport reuse, provider cache state and setup/inference split unknown.

T0 is ORION accepting the official UDP7082 falling sending edge, not a hardware
PTT-switch timestamp. Delay before that acceptance is unmeasured. T2 marks
FINAL/External-EOU future completion, not the later host poll. T6 is client RPC
invocation, not server receipt. T8 is adapter stream entry under its lock,
before prebuffer/physical guard, not first-frame permission. T9 is successful
local send, not headphone onset. Acoustic confirmation proves audible success
only. Observation overhead is nonzero; tests establish functional equivalence,
not zero timing perturbation. Two samples are not a percentile benchmark.

After run2 completed at 12:34:31.807 UTC, adapter shutdown was logged clean at
12:35:53.057 UTC. The later STOP response retained `provider_transport_failure`.
Exact underlying provider exception is not present in the inspected evidence;
no timeout/billing/network cause is asserted. This is after both completed
turns, not a failed measured response. No retry, repair or new live call made.
Normal STOP was issued; Test Session exported and inactive. DCS/SRS untouched.

Repository remains at measurement HEAD with no new code/doc commit. This report
and updated measurement-status.md are external analysis artifacts, not changes
to the installed runtime or its source archive.

FULL-VOICE LATENCY PROFILE —
MEASUREMENT COMPLETE / NO OPTIMIZATION PERFORMED.
