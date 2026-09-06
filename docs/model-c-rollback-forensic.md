# MODEL C rollback forensic — historical condition unresolved

**Superseded selection condition:** the user subsequently explicitly authorized
Option B based on current implementation/tests without the missing historical
rollback proof. The bounded deterministic route and regression tests now pass;
see `full-voice-field-ready.md`. The earlier bounded-stop reasoning below is
retained as chronology, not the current decision. No more archaeology is needed.

The user distinctly remembers a later MODEL C field incident in which a *set*
of received telemetry was audibly emitted, separate from the Stage 6A individual-
value defects. That field observation is the mandatory current regression
constraint. A defective intermediate uncommitted/field state followed by an
immediate rollback is a plausible explanation for missing Git evidence, **not**
a repository-proven fact. Neither non-occurrence nor a specific cause is claimed.

Date: 2026-09-07. Architecture Guard: OFF by the explicit recovery exemption.
Later Git is evidence only, not imported architecture or a Guard decision.

## 1. Recovery state preserved

Branch `recovery/a955d7c-radio-validated`, HEAD
`9362f18bd320da8e92daf6b680d68cfd08c6b8ad`, tree
`c6bba53a747fa667613d9bba460cefb711d5febf` are unchanged.
The index is empty. Existing tracked changes remain nine files, 74 insertions,
15 deletions. No implementation file was changed during this forensic.
No reset, clean, stash, checkout, merge, commit or push was performed.

Tracked changes retained:
`.github/workflows/ci.yml`, `pyproject.toml`,
`orion/phraseology_renderer.py`, `orion/radio_contracts.py`,
`orion/radio_router.py`, `orion/srs_radio_adapter.py`,
`orion/srs_transmission.py`, `tests/test_interaction_contracts.py`,
`tests/test_phraseology_renderer.py`.

Untracked implementation retained: `bounded_radio_stream.py`,
`full_voice_capture.py`, `full_voice_core.py`, `full_voice_field.py`,
`full_voice_live_world.py`, `full_voice_qwen.py`, `full_voice_srs.py`,
`full_voice_stt.py`, `ownship_phraseology.py`, `ownship_report.py`,
`protected_streaming_presentation.py`, `protected_streaming_tts.py`,
`speechkit_v3_stt_transport.py`, `srs_tx_state.py`, and
`yandex_speechkit_v3_proto/` under `orion/`; the full_voice test/probe files,
listener tests, readiness/status documents, older pacing probes/docs, generated
data and coverage artifacts are also retained.

Relevant preserved evidence remains:
`C:/Users/Алексей/AppData/Local/Temp/orion-full-voice-provider-g8m2osgb/report.json`
(HTTP 200 twice, completed ToolResult, three correct values/units but three
incorrect source references), and
`C:/Users/Алексей/AppData/Local/Temp/orion-full-voice-provider-a7pi1z3w/report.json`
(Core deadline). The full previous status is
`docs/full-voice-implementation-status.md`, unchanged.

Preservation SHA-256:

| File | SHA-256 |
|---|---|
| `orion/full_voice_core.py` | `4B80680779EE1943AF056760B80C676A36E3DF8546631A17EEB224FF4D48B217` |
| `orion/full_voice_qwen.py` | `0235192B5F251075AC2BF903441B0AA10D64E4306D18F12CC079D2C5EB4A0519` |
| `orion/ownship_report.py` | `29B19EE96C3282C6F40D77C236905807FBA1C52C34AA05D4AE4EAB678184A5BD` |
| `orion/ownship_phraseology.py` | `F468AAC12AEA90006385FD78AA8B01BEE15EF3C0288DC5615C3EDF09E0551ED9` |
| `docs/full-voice-implementation-status.md` | `ED4BF68A1E0CD875E14F414A914771FDCB72F939D1A83FE52B6A9DC1D2238412` |
| `data/fa18c_value_profiles.json` | `4975E243EE95FDF997CCC5ECC4537EAFF87947265C1C9A7F876ECF3CCEE15C1F` |

## 2. Search boundary and chronology

Read-only Git log/grep/show/blame covered the later repository, including
`dev/adr004-post-389` at `42520a57b01cd314978bcb51bdf4bbc75b38c156`, all local
refs for relevant changes, the branch reflog, and surviving unreachable objects.
The two unreachable commits, `21c6cbb8048376c628e5d80be0d3d2f7e9ea42db` and
`8260536b65ea142d671394301448f06b3aa49cc8`, are communication-profile-pack
infrastructure versions, not a MODEL C rollback. No matching rollback was
established. This does not prove that an uncommitted experiment or external
conversation never existed. No external conversations/private logs were searched.

1. `f5c5d474e63261a16812cb0dfe23fb83f10ea180` introduced live FlightContext
   injection into realtime AI, before the later MODEL C routing change.
2. `5896c4d961f502a4a59cbb31de3d533de8dfebe6` corrected this Stage 6A path.
   `docs/ORION_PROJECT_MEMORY.md` at `42520a5`, section 17, lines 833 onward,
   records ambiguous negative-speed wording, raw coordinates, approximate
   location, off-context answers and provider first-audio latency outliers.
3. `6f6f2f1aebbbde36aa0f0860df265c1e6013fd7b` introduced the explicit bounded
   MODEL C pre-Qwen route: `InteractionRouter.route_known_contract`,
   `KnownContractRoutingDecision`, and `LiveGoldenCaseRunner.run`.
   The decision contains intent, not operational truth. It routes a pure
   takeoff request to the existing Core ATC/OSU/phraseology path.
4. `b7223505b063b4d13a9b24303872113e54e901dc` records its physical field pass
   in `docs/field-pure-takeoff-model-c-2026-09-01.md`: zero Qwen calls, one
   Core result/OSU/protected fragment/SRS response; approximately 462–509 ms
   physical end to first SRS frame without VPN. This is historical evidence,
   not a current recovery field pass.
5. `6dea803e9deac09d0ed9e59d7b60cb6368a7a83e` extends the known-contract
   route with persistent ATC status; it retains the takeoff route.
6. `27e94bdbf843a3f1895db2756eed49e42fe07989` adds
   `AircraftIdentityQueryService.resolve`, `_core_semantic_response`, and a
   Qwen natural-formulation/validated-marker binding path. Its initial
   committed version already uses Qwen for wording. It is not a Git diff
   reverting a committed telemetry-dump implementation. The accompanying
   history section 14, lines 437–464, explicitly retains zero-Qwen takeoff and
   status routes while describing this informational ownership correction.
7. `f64d8424d0cfd00543d18a2f0c1fa5a6f81b6b05` extracts provider-neutral
   identity-shell validation and adds a non-default Realtime candidate.
   `5bd29cc04d73986c79a5448e5cee10ee2c1746b3` corrects observed shell-validator
   false positives; neither removes MODEL C.
8. `77d562d7b50aabc19a33aaf856e96aa113e0b402` separates
   `validate_aircraft_identity_structure` from the legacy shell validator and
   introduces semantic-conformance validation. `f2df3713fd84ef5bfeb2d8d1f650044384b6f3d8`
   permits additional Core-confirmed informational facts; `9ed45bbd820e60784d83c357a248d3b95dae765a`
   connects the explicit non-default candidate. These later mechanisms were
   inspected as historical evidence, not imported into recovery.

## 3. Failure-chain classification

The specific remembered **MODEL C telemetry-speaking failure/rollback is UNKNOWN**
in the inspected Git evidence. Its exact cause cannot honestly be assigned to
A/B/C/D/E/F/G from the task merely because another symptom sounds similar.

The separate Stage 6A episode is partially causally established:
`LiveTelemetryStore → FlightContextService._compose_instructions → realtime AI
session → provider language/audio → SRS`. This is not literal telemetry → TTS,
and it is not ToolResult → OSU. AI was present, but the context inadequately
distinguished flight quantities and location certainty. The correction makes
those distinctions explicit. The exact mechanism of every bad heard utterance
is not established by retained raw audio here.

- A: direct raw telemetry speech — not proven for MODEL C, nor literal in the
  Stage 6A code path.
- B: insufficient ToolResult-to-OSU mapper — no failing historical mapper found.
- C: phrasing/semantic-context problem — documented for Stage 6A, not proven as
  the remembered MODEL C event.
- D: provider audio latency was measured; it does not explain wrong semantics.
  No corresponding codec/pacing corruption is established as the semantic cause.
- E/F: wrong intent or competing/stale owner — not established for this event.
- G: precise other cause — unknown. Do not fabricate it.

## 4. What actually changed, not an invented rollback

`5896c4d` replaced generic identity/context composition, clarified DCS heading
without inventing magnetic semantics, differentiated non-negative TAS from
signed vertical speed, supplied explicit units and hemisphere coordinates,
forbade guessed airfields/countries, and deferred/coalesced context updates at
safe turn boundaries. It retained live telemetry ownership, AI formulation and
the SRS transport. Tests added in `tests/test_flight_context.py` include
`test_ai_presentation_has_verified_aviation_units_and_signed_vertical_rate`,
`test_canonical_identity_and_single_context_block_survive_many_updates`, and
`test_active_turn_defers_and_latest_context_coalesces_until_safe_boundary`.

The MODEL C tests at `6f6f2f1` include
`test_pure_ru_and_en_takeoff_route_before_qwen_without_provider_calls` and
`test_mixed_free_unknown_and_ambiguous_inputs_preserve_qwen_fallback`.
The identity tests at `27e94bd` enforce live authority, stale/no-player
unavailability, exact Core binding, and rejection of added/invented facts.
Repository evidence therefore does not establish rejection of MODEL C as a
concept. It establishes retention of bounded deterministic domain semantics
alongside a distinct informational-formulation path.

## 5. Comparison with current recovery

The current recovery `FullVoiceCore.run` uses the real InteractionRouter and
Planner, then `map_ownship_report`, `PhraseologyRenderer`, `ResponseComposer`,
and protected streaming presentation. The mapper requires precisely heading,
latitude and longitude, exact completed-result source binding and values,
authority/provenance/freshness, numeric units/ranges, and no derived or
unavailable facts. The renderer accepts only `navigation.ownship_report` with
meaning `navigation.current_ownship_state`, known/declarative state, and its
ordered three protected keys. Its text begins `Current heading`, not `Fly heading`.
It consumes an OSU, not a generic telemetry object. Stage 7C structured-text
validation remains between composition and TTS.

These are materially stronger controls against arbitrary telemetry becoming
speech than the historical context-to-AI path. They do not prove the absence of
the *unknown* remembered root cause. There is currently no implemented
deterministic ToolResult-to-ownship route: InteractionRouter still selects the
controlled Planner for the ownship query. Selecting a new path requires the
task's explicit Option B condition to be satisfied or amended, not merely
asserting that an existing Qwen experiment worked.

## 6. Semantic-middle decision and bounded stop

**STOP — selection condition unresolved, not a conclusion that deterministic
semantics are intrinsically unsafe.**

Option A: existing live evidence provides no accepted bounded Qwen provenance
fix. No additional Qwen call is authorized by this forensic strategy, and none
was made. Validation was not weakened.

Option B: the task says to choose it only if historical evidence establishes
that the previous MODEL C failure arose from bypassed/insufficient semantic
interpretation. The exact episode and that causal condition were not found.
Stage 6A cannot silently be substituted for MODEL C to satisfy this condition.

The missing decision is narrowly bounded: either supply the exact source of
the remembered rollback, or explicitly permit B on the current typed-pipeline
and historical successful bounded-route evidence despite the unknown rollback
root cause. This is not a request for another general preflight or a new stage.
No third architecture or repeated provenance-persuasion experiment is proposed.

## 7. Tests, provider, latency, commits and field state

This turn changed no runtime or test code and performed no live provider,
audio, telemetry or SRS test. It adds only this forensic report. Earlier results
remain historical results for the unchanged draft: 1739 passed / three known
Saved Games test failures, targeted 87 passed; Ruff/Pyright/compileall passed;
coverage aggregation failed. They are not a new deterministic-route gate.

The mandatory new raw-extra-telemetry regression and deterministic end-to-end
gate have **not** been added or claimed passed, because B has not been selected.
They remain required before any field-ready declaration if B is authorized.

Earlier component latency remains STT barrier ~313 ms, invalid-source Qwen/Core
9516 ms, separate short john TTS first chunk 2359 ms. No current deterministic
Core latency, first SRS frame or physical total has been measured. No latency
benefit is claimed from unimplemented routing.

No commit or push. No process was terminated/restarted or launched in this
forensic. START LIVE, Launcher, Stage 7A/7B/7C and all existing uncommitted work
remain unchanged. Physical field instructions are deliberately not activated:
do not press PTT for a full-voice test yet. The current provider semantic gate
remains unclosed while the alternative's selection condition is unresolved.
