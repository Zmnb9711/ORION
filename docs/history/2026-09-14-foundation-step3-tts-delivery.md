# Foundation Step 3 — TTS delivery, 2026-09-14

ORION ARCHITECTURE GUARD: OFF. Component validation, NOT Foundation field acceptance.

## A. Contract / starting Git state

CONTRACT READ: `ORION_NATURAL_LANGUAGE_FIRST_CONTRACT_V1` at
`docs/architecture/ORION_NATURAL_LANGUAGE_ARCHITECTURE_CONTRACT.md`.
SHA-256 `de59126cb79efc010996f4f8357ab80b641109b7ed3cd60ccbc7856d53c2a128` unchanged.
Worktree `C:/Users/Алексей/Documents/GitHub/ORION-level0-conversation`;
branch `codex/general-natural-language-ingress-tranche1`;
parent `152a2f22c281fc31ab00daf99f4e171af88c05f9`, tree
`93c837f6d71452216cc88176a9df398a2e91a67b`.
Initial index/tracked worktree clean; untracked `data/` preserved.
Step 1 `4b5a46959c241eec6ef8391ee52de4da93f3dc0f` and Step 2 parent are present.
Older uncommitted/failed-gate labels in indices describe earlier snapshots.

Contract compliance: sections 1–3/6/12–13, no input grammar or routing edit;
4–5/7/10, unchanged roles, Core authority and fact admission; 8, no Mixed;
9, unchanged explicit context/semantic ownership; 11, no added LLM/retry and
latency debt reported separately; 14, full host/preservation regressions;
15, no physical or blind acceptance claim; 17–20, read/source/scope/stop discipline,
no canonical amendment. No conflict found within this bounded repair.

## B. Historical failure reconstruction

Primary ZIP:
`C:/Users/Алексей/AppData/Local/ORION/runtime/test-evidence/ORION-Test-Evidence-20260910-213600.zip`
SHA-256 `7e8971fbc4a1e53b196aa0321d3d765666f7f16950c86a445dda411d268aa2c7`.
Session `b09b2c3176734601991bfc67000266e0`, build
`5c9ab2440cc8bf9dfb2ea422b88ef5c498e53314`;
841 events, 20 finalized turns, 12 completed and 8 failed.
UTC window 2026-09-10 21:31:01.574–21:36:00.325 (next calendar day in Moscow).
ZIP has events/manifest/summary only, no RX/TX WAV.

Seven turns reached exact finalized/TTS text but had RESOURCE_EXHAUSTED,
zero decoded PCM and zero frames, then generic `radio_rejected`:

| Turn | Text class / characters | TTS start→failure, monotonic seconds |
|---|---|---|
| f8dc1fac-b0b4-4bb3-80fb-8f00acece6af | coordinates /120 | 90093.531→90095.046 |
| 0ef22fd3-330f-4ead-8636-4a122ff32847 | coordinates /120 | 90104.203→90105.000 |
| a978a7e4-1672-4312-8a2c-13aaac7e5b67 | catalog /214 | 90153.359→90154.062 |
| 2e3004b8-e30e-4f6f-acea-a565e055d9a6 | catalog /214 | 90163.734→90165.234 |
| 0f66d932-92fd-46a8-a73e-1aba6a797d2f | help /276 | 90247.062→90247.796 |
| a4ea0263-f5ce-47d7-b9fb-62de8faa62e1 | coordinates /120 | 90262.343→90263.890 |
| 7b6a9dc5-bfd4-48b5-a4f8-bc9b924c4012 | catalog /214 | 90271.359→90272.187 |

The eighth failure was PARTIAL DELIVERY: turn
`cd7fbef5-abb5-415d-a569-19a979755384`, semantic operation
`d620205b-b90b-46f4-b328-e2def32a3336`, response
`resp_8eb0bde5e5cd48649d39d27ba68eeba8`, TTS RPC
`383f460d-5462-4e17-92f4-e72601038c5b`, TX
`p7c-cd7fbef5abb5415da56919a979755384`.
Dialogue about space: TTS start 21:34:26.239Z; first PCM 21:34:30.805Z;
first TX 21:34:30.811Z; 860438 PCM bytes produced, 89 frames sent;
abort 21:34:34.357Z, failed terminal 21:34:34.379Z. Not a completed response.

## C. Current call graph / ownership

Admitted `FinalizedGeneralText` → `GeneralPresentation.present/_run`
→ borrowed `StreamingProtectedPresentation._run` → `InformationalStreamingTts`
(`jane`; protected English path remains `john`) → `ProtectedStreamingTts.stream`
→ SpeechKit v3 gRPC `Synthesizer/StreamSynthesis` → PCM16 mono 48000 Hz
→ `StreamingPcm16Resampler` 44100 Hz → `BoundedPcmStream`
→ existing `RadioRouter` worker → `SrsRadioTransportAdapter.transmit`
→ `FullVoiceSrsEndpoint.transmit_srs_stream` → resample 16000 Hz / Opus /
40 ms `TxPacer` / existing SRS packetization / `radio.send_voice`.

Producer task owns TTS generator and resampler; generator owns call/channel;
router owns consumer thread/operation; each turn has fresh bounded stream.
Presentation owns neither the borrowed host nor the entire semantic session.
Radio admission precedes synthesis; consumer waits for prebuffer.
First PCM can transmit before TTS completion; no whole-clip playback barrier.

## D–E. Lost detail and RESOURCE_EXHAUSTED root cause

Old catch retained only gRPC status and replaced the exception with a short
RuntimeError. The ZIP cannot prove the remote/client origin for EACH historical
request. Do not retroactively claim quota/billing or exact historical packet sizes.

Current mechanism reproduced independently with one developer-created 118-char,
203-byte coordinate-shaped text. Safe gRPC detail:
`Received message larger than max (1267589 vs 1048576)`.
0 decoded messages/PCM. Classification **LOCAL CLIENT LIMIT**, not evidence of
billing/quota. RPC `cfa9955c-c9f7-41b1-8fcd-36efa862da94`, 1532 ms.
The post-fix same text returned exactly one 1267589-byte message successfully.
This proves the relevant zero-PCM failure class and its local repair, while
individual historical cases retain unavailable-details uncertainty.

Important: medium 233-char text produced 1584470 cumulative PCM bytes in TWO
messages, largest 835412, and already passed the old limit. The limit applies
to ONE protobuf message, not total audio. Text length alone is not a threshold:
the shorter single sentence exceeded the limit, the longer split text did not.

Official references: [gRPC channel argument definitions](https://github.com/grpc/grpc/blob/master/include/grpc/impl/channel_arg_names.h)
define per-message receive size and default unlimited send;
[SpeechKit StreamSynthesis](https://yandex.cloud/en/docs/speechkit/tts-v3/api-ref/grpc/Synthesizer/streamSynthesis)
defines streamed response envelopes. No assumption that audio chunk size is
under ORION's former 1 MiB. Service limits are distinct from local 30-second PCM policy.

## F. Partial-stream first failure — recovered from richer original log

`C:/Users/Алексей/AppData/Local/ORION/runtime/srs-radio/srs-radio-bac84a0a09fd47e38896e2483bed69e7.jsonl`
SHA-256 `c726c882222e0a806af03adfcd8eaf9a60dfd33ae3e5a1730d0348e45d176e07`.
Line340, **21:34:34.356Z: endpoint_error RuntimeError,
`srs_collision_or_unexpected_origin`**; line341 adapter transport error at
21:34:34.364Z. The preceding idle snapshots were fresh (~203/204 ms cadence,
last 21:34:34.042Z). Not evidence of snapshot staleness or TTS backpressure.

`FullVoiceSrsEndpoint._on_radio_datagram` rejects nonaccepted/wrong-origin
RX after excluding self/wrong-channel/duplicate/out-of-order packets;
`_abort_turn` aborts active stream then `_set_failure` stops the endpoint.
This first SRS RX guard failure predates producer RuntimeError/terminal collapse.
Original packet/GUID is unavailable: cannot distinguish collision from unexpected
origin, explain the sender or declare the external field condition fixed.
Do NOT relax this guard. No SRS algorithm/configuration change was made.

## G–H. Exact in-scope repair and safe observation

1. `orion/protected_streaming_tts.py`: finite **3145728-byte (3 MiB)** receive
   envelope; sufficient for existing maximum 2880000 PCM bytes plus envelope.
   Text/speed/voices, 15-second RPC deadline, force synthesis, retry=0 unchanged.
   Message sizes/counts, text SHA/chars/UTF-8 size, request UUID, safe failure
   category and call cleanup observations. Only closed gRPC size-error grammar
   exposes details; all arbitrary provider prose is withheld.
2. `orion/protected_streaming_presentation.py`: explicitly `aclose()` the TTS
   generator in producer finally. Offline backpressure test proved a generator
   could remain suspended with its owner active when feed failed outside it.
   Fix closes its gRPC call immediately instead of relying on GC. This is an
   independently reproduced cleanup defect, NOT a claimed historical first cause.
   Safe producer-phase/first-abort/admission/cleanup observations and partial PCM count.
3. `orion/bounded_radio_stream.py`: first-abort code observation only; later
   cleanup still clears buffer and preserves old operational failure semantics.
4. `orion/realtime_test_evidence.py`: four lines of additional bounded scalar
   fields in EXISTING opt-in conversation projection. Legacy record/export,
   lifecycle, paths and normal-operation privacy unchanged. No new recorder/WAV feature.

No hidden text transformation, truncation, retry, additional model, replacement
provider, new buffer policy or SRS workaround. Unknown causes remain UNKNOWN.
Lower-level cause is retained even when legacy product terminal is `radio_rejected`.

## I. Offline failure/recovery matrix

`tests/test_tts_delivery.py`: 19 tests. Real loopback gRPC/protobuf, fake cloud:
normal, cumulative >1 MiB, old-limit-size successful message, >new-limit rejection,
remote RESOURCE_EXHAUSTED with private details withheld, partial PCM then RPC error;
each failure followed by one fresh valid request on the same TTS owner.
Closed diagnostic grammar privacy proof.

Real presentation/RadioRouter/bounded stream, fake TTS/radio: normal,
before-first-PCM failure, partial producer failure, consumer failure,
real two-second backpressure timeout, admission rejection, cancellation before
and after PCM, presentation deadline. Each gets cleanup and a distinct later
successful turn, no replay/stale PCM/duplicate synthesis/remaining producer.
Separate unchanged endpoint collision guard replay preserves first abort through
cleanup; opt-in export preserves safe cause without arbitrary exception prose.

Stream capacity **176400 bytes (2 sec at 44100 Hz)**, total **2646000 (30 sec)**,
prebuffer10584, producer no-progress timeout2 sec, prebuffer wait10 sec unchanged.
Normal bounded waiting is not failure; progress refreshes producer wait deadline.

## J–K. Real provider + paced delivery gate

2026-09-14 22:55:02–22:55:42 Moscow. Three actual TTS RPCs after one controlled
local zero-PCM failure (no cloud operation for that fixture), all independent,
no retries, same TTS/presentation/router owner. API key via normal Windows
credential store; same `tts.api.cloud.yandex.net:443` v3 stream endpoint.
No semantic-provider request, microphone, DCS, live SRS connection or audio device.

Real TTS/PCM, actual 48→44.1→16 kHz resampling, production presentation/Router/
SRS adapter/endpoint/packetizer/pacer; fake physical state, codec and radio sink.
Gate invokes admitted-text delivery helper; typed admission itself is proved
by unchanged offline host/admission regressions, not a real semantic/DCS test.

| Text | chars / UTF-8 | messages / largest bytes | PCM bytes / seconds | first PCM / first fake-sink frame ms | frames / terminal |
|---|---:|---:|---:|---:|---|
| short | 30 /56 | 1 /222643 | 222480 /2.3175 | 2609 /2609 | 58 /completed |
| medium | 233 /428 | 2 /835412 | 1584470 /16.5049 | 2484 /2484 | 413 /completed |
| coordinate-shaped | 118 /203 | 1 /1267589 | 1266822 /13.1961 | 1906 /1922 | 330 /completed |

PCM nonempty/even, mono LINEAR16 48000 Hz; exact request-text SHA retained;
no WAV needed/produced. Each operation has one RPC and one radio admission/TX;
no underrun frames reported. Buffer high-water exactly176400, not enlarged.
All calls cleared, consumer locks released, streams cleared, shutdown clean,
pending asyncio tasks0. No packet was sent to a real SRS server.

## L. Latency

New channels per TTS call; these are not pure warm-only provider measurements.
Final text→first PCM **1906–2609 ms**, plus **0–16 ms** to first offline-sink
frame in this run. Total paced completions4969/19031/15140 ms include clip duration.
Step 2 warm semantic median ~1000 ms remains separate. Combined budget would
be roughly2.9–3.6 sec before real transport/acoustic costs; this is an estimate,
not a new end-to-end physical measurement. <1 second product target NOT achieved.
No semantic/TTS streaming redesign or latency optimization in this step.

## M–O. Preservation, scope, regression

Step 1 routing and Step 2 prompt/context/provider modules byte-unchanged.
Step 2 scope test now freezes its exact completed commit, then asserts its four
runtime files remain unchanged. Historical gRPC oracle compares all serialized
requests, auth metadata names, endpoint, retry/deadline, PCM/errors and cleanup;
only the explicitly asserted 1→3 MiB option is normalized for comparison.
Old fake response now uses actual protobuf (ByteSize), not incomplete namespace.
Complete-file fingerprints updated only for reviewed four production files.

Targeted232 PASS. Full suite **3325 PASS /5 pre-existing FAIL /1 SKIP** (83.90s).
The five are unchanged IA import inventory, three setup-wizard expectations and
stale Project Memory exact product phrase, previously reproduced on parent line
in [Step 1](2026-09-14-foundation-step1-routing.md), also in Step 2. No baseline fixes.
Initial Step 3 full run exposed outdated fake protobuf/limit expectations; corrected
tests retain the exact differential oracle, not a broad exemption.
Ruff whole repository PASS; changed-runtime Pyright with actual venv0 errors/0 warnings;
diff check PASS. No global type-check PASS claimed (legacy debt exists).
Full production Pyright reports199 errors, matching the recorded baseline debt;
all four changed production modules separately report0. Compileall PASS.

No canonical/prompt, Fact Registry, DCS Export semantics, Mixed, Planner, domain,
persistent context, Launcher, lifecycle, configuration or packaging changes.
User profile SHA `4975e243ee95fdf997ccc5ecc4537eaff87947265c1c9a7f876ecf3ccee15c1f`;
original101803-byte events prefix SHA
`001d663f44f468b21667383c9bff062b0e02b5eb7053347475c89677fa25d02c` unchanged.
Tests append generated events; retained, not staged/cleaned. User data staged0.

## P–T. Evidence level, commit, product boundary

OFFLINE TTS PASS; LIVE TTS PROVIDER PASS; REAL PCM STREAM/PACED OFFLINE SINK PASS.
Actual RADIO TX, acoustic, installed-build and USER BLIND FOUNDATION PASS:
NOT RUN / NOT CLAIMED. Historical product FIELD FAIL is not overwritten.
Decision **A — COMMIT STEP 3 AS-IS**, conditional final scope/index checks clean;
one authorized commit/push on current feature branch, no merge/rebase/main edit.
Exact commit/tree/remote receipt belongs to the closing response (this record
is included in that commit). Step 4 requires separate user authorization.
No build/install, DCS/SRS/PTT or new user action in this step.

External artifacts (not staged), directory
`C:/Users/Алексей/AppData/Local/Temp/orion-foundation-step3/`:

| File | SHA-256 |
|---|---|
| diagnostic.json | 35bd359439bf08cda725ec22f420c68453edb9aee23b8ac68f0b0c24f97b8039 |
| single-sentence-diagnostic.json | d14661c3331a98a5369417e317cc4b057888fd92284d6a7129853da7784e04fa |
| offline-delivery.json | 489dae6c4e0b8188fe10ca27dc6e5a5f4b8a4f7eef8f93e1d754bc20bdc8be94 |
| live-delivery.json | f3931ff61f68ffadff4e8b9ce1c6ac70f3fb5aa7520c1d32b899afb7db5fed91 |

The two diagnostic harnesses, original/final full-suite output, exact developer
texts, per-turn/RPC/TX IDs, safe events, hashes and timestamps are alongside.
Only hashes/counts/closed error categories were added to production diagnostics;
no credentials, headers, arbitrary provider bodies or user audio were recorded.
