# First full bidirectional voice vertical — field validated

**FIRST FULL BIDIRECTIONAL VOICE VERTICAL — CLOSED / FIELD VALIDATED.**

Canonical preservation record: [2026-09-07 history](history/2026-09-07-full-voice-field-validation.md).
Input is `ru-RU`; current protected output is `en-US` / `john`.
The later documentation-preservation task authorizes a recovery-branch push;
pre-field pending statuses and no-push statements below describe earlier work.

2026-09-07. Architecture Guard: OFF, explicit historical recovery exemption.
This is the existing full-voice milestone, not a new stage. All three bounded
physical scenarios now have machine evidence and user acoustic confirmation.
The pre-field sections below retain their historical context; the appended
field evidence and final closure section supersede their pending-field status.

## 1. Baseline and preserved work

Implementation starts from recovery branch `recovery/a955d7c-radio-validated`,
commit `9362f18bd320da8e92daf6b680d68cfd08c6b8ad`, tree
`c6bba53a747fa667613d9bba460cefb711d5febf`. Existing uncommitted full-voice work
was extended, not reset/recreated. No merge or push. Old pacing probes, generated
data and coverage files remain untracked and unmodified by this implementation.
The Qwen experiments `orion/full_voice_qwen.py`,
`tests/test_full_voice_qwen.py`, and `tests/full_voice_provider_gate.py` are
preserved untracked as forensic work, not included in the production field path.

## 2–4. Historical MODEL C finding and its limits

See `model-c-rollback-forensic.md` for exact commits/files/symbols and search
limits. `6f6f2f1` introduces bounded takeoff routing; `b722350` documents its
physical success. `6dea803` extends deterministic status; `27e94bd` adds a
separate natural informational identity path. No exact remembered MODEL C
defective-state/revert commit was recovered.

The user's remembered MODEL C symptom is an emitted **telemetry set without
adequate intent-specific selection/interpretation**. It is separate from Stage
6A's ambiguous individual values (`5896c4d`). A rapidly reverted intermediate
uncommitted field build is plausible, not proven. The exact MODEL C root cause
remains unknown; no claim is made that the incident did not happen. The user
explicitly removed historical recoverability as a prerequisite and required
current tests against that symptom instead.

## 5–7. Selected middle: bounded deterministic ownship report

The dedicated field host opts into `InteractionRouter`'s
`bounded_ownship_gateway` mode. Only the complete authorized Russian heading +
coordinates query matches (case/whitespace and one terminal punctuation mark
may vary). Keyword-only, mixed, negated, extra-field, free-form and unsupported
requests do not match. There is no provider fallback in this field mode.

Default IA-6 Planner/Qwen routing elsewhere is unchanged. No Qwen provenance
validator, permission rule or accepted-source rule was weakened. No further
Qwen request was made after the semantic-middle decision.

The actual chain is:

`official local SRS PTT evidence + expected human SRS RX → one physical owner
→ native SpeechKit v3 External EOU → matching FINAL/EOU_UPDATE
→ immutable FinalizedUserUtterance → InteractionRequest → InteractionRouter
→ permissioned ToolGateway → authoritative WorldModel → explicit three-fact
Core projection → strict ownship-report OSU → PhraseologyRenderer
→ ResponseComposer → protected streaming presentation → RadioRouter
→ SrsRadioTransportAdapter → existing packet/Opus/40 ms pacing → SRS`.

The recognizer supplies no facts. The mapper supplies no wording. The renderer
accepts an explicit known/declarative typed OSU, never a telemetry object.

## 8–10. Implementation and semantic contract

- `ownship_report.py::ownship_semantics_from_tool_result` requires completed
  registered `orion.world.ownship.get` v1 output, handler-started receipt, exact
  call/tool/interaction identities and the registered `OwnshipOutput` schema.
- It selects exactly `ownship.heading_deg`, `ownship.position.latitude`, and
  `ownship.position.longitude`. Selected parent facts must be KNOWN,
  AUTHORITATIVE, DCS_EXPORT, correctly named/unit-tagged, fresh and from the
  retained generation. It preserves the original scalar values/signs/units.
- Extra *registered snapshot* fields may exist but cannot be selected. Unknown
  structural fields, missing/duplicate/conflicting selected leaves, invalid
  authority/source/generation, wrong units, unavailable/stale data, invalid
  numeric ranges and mismatched receipts fail closed.
- `map_ownship_report` reuses exact semantic-value binding and produces one
  `navigation.ownship_report` with meaning `navigation.current_ownship_state`.
  Three protected values and three corresponding provenance references only.
- `OwnshipReportRuleset` explicitly selects `RECOVERY_OWNSHIP_REPORT_V1`.
  Wording is declarative: `Current heading … degrees. Latitude … degrees.
  Longitude … degrees.` It never substitutes a heading command. Numeric
  rendering is lossless and synthetic, **not normative ICAO phraseology**.
- `FullVoiceCore` retains exact replay results, rejects identity conflicts and
  fails closed at 64 retained identities rather than evicting live dedupe state.
- `full_voice_field.py` uses this route without loading Qwen config or shim.
  The config-root CLI argument is retained for command compatibility; SpeechKit
  and SRS secrets still use the existing Windows credential store.

No `ToolResult → str/json dump → TTS` path was introduced. Only the validated,
recomposed finalized protected string reaches `ProtectedStreamingTts.stream`.
It is sent exactly, without `.strip()`, translation, SSML or generative rewrite.

## 11–12. Mandatory regression and automated integrated gate

`tests/test_ownship_semantic_middle.py` deliberately supplies large changing
speed/altitude values, fuel, aircraft/callsign and arbitrary diagnostic/navigation
fields. It proves the registered ToolResult contains additional facts while
the OSU keys/values, rendered fragment, finalized text and TTS request are
exactly the fixed three-fact report. Two distinct extra-value sets produce the
same permitted text. It uses real WorldModel, ToolGateway, InteractionRouter,
mapper, renderer, composer, streaming presentation and RadioRouter with a
controlled sink. Simulated physical START/PCM/END feeds the native final barrier.
It also proves a single response, repeated invocation without second TX,
negative coordinates, state changes and unsupported/no-output behavior.

Additional cases reject malformed/extra/duplicate data, wrong source/authority,
freshness, receipt and units. Existing Planner mismatch tests remain active;
the new path does not make invalid Qwen provenance acceptable.

## 13–14. Real provider and latency evidence

Existing implemented native STT gate: known Russian recording, one finalized
utterance, matching FINAL/EOU_UPDATE, 112824 bytes at 16 kHz, EOU-to-barrier
approximately 313 ms. This is not human physical-field evidence.

New live Core + exact john TTS + controlled packet-sink gate:
`C:/Users/Алексей/AppData/Local/Temp/orion-ownship-stream-gate-xx_1w5ag/report.json`.

- Real new DCS telemetry through the exclusive recovery owner, actual
  WorldModel/ToolGateway, deterministic semantics: PASS.
- Qwen calls: 0. SpeechKit v3 StreamSynthesis calls: 1, voice john, raw mono
  LINEAR16 PCM 48000 Hz. Exact finalized request text: true.
- PCM: 1,477,472 bytes, two chunks. Real Opus/resampling/40 ms scheduling and
  SrsRadioTransportAdapter/RadioRouter processed 385 local packets; all packets
  decoded to valid 640-sample PCM frames; zero underruns; shutdown clean.
- TTS start to first PCM and first **local sink** frame: approximately 2812 ms.
  First sink frame precedes TTS stream completion; bounded PCM high-water is
  176400 bytes. Provider audio duration is approximately 15.39 seconds.
- Core timestamp delta was 0 ms at the available clock resolution; this means
  below that measurement resolution, not physically zero execution time.
- No SRS network transmission or playback occurred in this gate. No physical
  end-to-audible latency is claimed. The earlier 313 ms STT sample and this
  separate output test must not be added into a claimed physical measurement.
- The 2.81 s output-start result misses the ideal <1 s objective. It is not a
  reason to discard the semantically correct first vertical. Physical field
  performance remains to be measured.

`tests/full_voice_speechkit_gate.py` is the explicit provider CLI used for this
gate; it is not an automatically live pytest test. Its radio sink has no sockets
and discards audio after validation. Exact live values/text remain only in the
opt-in Temp report, not copied into Git.

Dedicated field runner dry startup/shutdown also passed with zero turns/TX:
`C:/Users/Алексей/AppData/Local/Temp/orion-full-voice-778z_xjy/report.json`.

## 15–16. Protected areas and quality results

START LIVE, Launcher, general production provider selection and Realtime/VAD
path are not migrated. SRS protocol/RadioInfo/Opus/pacing/PTT mapping are not
replaced. Existing finalized-PCM callers keep their default path. Stage 7A
synthetic golden outputs, 7B composition and 7C protected ingress/fidelity
checks remain; new declarative wording is an explicit separate ruleset.
DCS and official SRS Client remain externally owned and were not restarted.

- Required focused/regression gate: **298 passed**, one existing warning.
- Broad working-tree suite (including preserved untracked forensic tests):
  **1768 passed, 3 known baseline Saved Games failures**. No
  unrelated Launcher/discovery fix or test suppression was introduced.
- Ruff, compileall, Pyright touched modules + existing CI targets, and
  `git diff --check`: PASS (LF/CRLF Git warnings only).
- Previous coverage aggregation error is recorded in the historical status;
  coverage percentage is not a gate pass claimed by this milestone.
- CI installs the optional SpeechKit v3 dependencies and checks the new runtime
  modules in its Pyright target list. Generated protobuf provenance is retained.

## 17. Commit policy

Two logical commits preserve transport/physical-turn infrastructure and then
the bounded Core semantic/output integration. Exact commit IDs are reported in
the handoff; the current HEAD containing this document is the second commit.
Transport/physical-turn commit: `ba627867fe92acab7d54297844c3f38339b38f61`.
No push or merge to dev. Qwen compatibility experiments are not selected.

## 18–19. Physical field setup and stop boundary

Physical/acoustic validation is still REQUIRED. Field runner:

```powershell
Set-Location 'C:\Users\Алексей\Documents\GitHub\ORION-recovery-a955d7c'
& 'C:\Users\Алексей\Documents\GitHub\ORION\.venv\Scripts\python.exe' -m orion.full_voice_field --field --config-root 'C:\Users\Алексей\AppData\Local\ORION\runtime' --duration 240 --turns 3
```

The assistant can launch this programmatically. The user need not start the
installed Launcher or press START LIVE. It requires the user's already-running
DCS aircraft/mission, local SRS Server, exactly one official human SRS client on
radio 1 / 251.000 AM, and no competing ORION voice/Core/UDP7082 owner. Binding,
fresh telemetry and readiness are checked programmatically. Do not press PTT
until the assistant reports the actual live runner READY, not an old dry report.

1. Hold ordinary SRS PTT and say `Какой мой текущий курс и координаты?`, then
   release. Wait for one complete declarative heading/latitude/longitude answer.
2. After a real aircraft heading/position change and the first terminal result,
   repeat the same query. Machine evidence must show fresh changed facts and a
   new correlation identity; the user confirms correct clear hearing.
3. After the second terminal result, say `Расскажи анекдот.`. Expected: no
   operational answer and no transmitted invented facts.

Do not overlap PTT with the response; this first vertical fails closed on busy
input instead of queueing another turn. Evidence is written to the newly printed
Temp `report.json`. Confirm the heard wording, no clipping/distortion/overlap,
and exactly one answer per supported turn. Unsupported silence needs machine
corroboration. First-SRS-frame timing is a response-start proxy, not human
audibility proof. Do not declare CLOSED before user hearing and machine evidence
are both reviewed.

## Physical field evidence update — 2026-09-07, first supported turn

The first supported physical user-spoken turn has passed machine review and
the user confirmed: `ответ услышал четко` (the answer was heard clearly).
This confirmation applies to this turn only; it does not close all field gates.

- Evidence: `C:/Users/Алексей/AppData/Local/Temp/orion-full-voice-_i1vaz55/report.json`.
- Original report SHA-256:
  `6CF3C5A2B79227D4CFA8F4B939F22AF656D1BB12B177805CB4D2F477E4231526`.
  The original report remains unchanged; its `human_review: REQUIRED` field
  predates the user's confirmation recorded here.
- Tested HEAD: `ba43a2c52f952a43cec0adde2bce99394a6c71d1`, with uncommitted
  safe input-evidence diagnostics in `full_voice_stt.py`, `full_voice_field.py`
  and their tests. Those diagnostics measure PCM counts/amplitude and terminal
  state, without changing STT segmentation, VAD, text or radio behavior.
- Interaction: `c7a0aa8d-b807-4e0a-b371-97e44fc75a2b`; completed.
  Physical input: 154880 bytes of 16 kHz PCM, 4840 ms; one finalized utterance
  and matching FINAL/EOU barrier. Actual completed ownship ToolGateway receipt
  and three authoritative selected facts share the interaction/call identity.
- One SRS transmission started and completed: 385 frames, matching TX identity.
  No failures recorded; presentation shutdown clean; Qwen calls: zero.
- Physical turn end to final barrier: 422 ms; EOU to barrier: 328 ms.
  TTS start to first PCM: 2828 ms; first PCM to first SRS frame: 16 ms.
  Physical turn end to first SRS frame: **3266 ms**. This is a transmission-start
  proxy, not measured acoustic onset, and misses the ideal below-1000-ms target.
  Functional success is not rejected solely because of that latency.
- Exact live values and protected wording remain in the private Temp evidence;
  they are not duplicated here. No clipping/overlap-specific assertions beyond
  the user's actual clear-hearing confirmation are inferred.
- Diagnostic regression checks: 57 tests passed; touched-module Pyright,
  scoped Ruff and diff whitespace checks passed.

Earlier `orion-full-voice-wl_tkg6i` evidence had two empty-final turns and no TX.
Its missing input-amplitude diagnostics do not retrospectively establish why
recognition was empty. This successful turn does not prove that earlier cause.

Still required: a second supported physical query after a real aircraft
heading/position change, with fresh changed facts and clear hearing, followed
by the unsupported-query physical gate with machine-confirmed no operational
TX. The dedicated host has closed after this first turn; re-arm only that host
when the user is ready. Do not declare the milestone CLOSED yet.

### Second supported physical turn — changed aircraft state

The second supported turn passed machine review. The user confirmed:
`ответ четко услышал` (the answer was heard clearly).

- Evidence: `C:/Users/Алексей/AppData/Local/Temp/orion-full-voice-wde0cf7t/report.json`.
- Original report SHA-256:
  `5A02672E8F03450C5371752526CFFF3C29707618A7ABE901D4AC6E56DF482055`.
  The original report is unchanged; human confirmation is recorded here.
- New interaction: `9cb1f23f-302c-48ef-8dcf-88292a10601c`; completed. The
  recognized-query hash matches the first successful query. All three selected
  values (heading, latitude, longitude) differ from the first turn; new actual
  completed ToolGateway receipt, matching new call/interaction and authoritative
  provenance are present. Generation is local to each restarted host and is
  not compared numerically across processes as a freshness test.
- Input: 145920 bytes at 16 kHz, 4560 ms; matching FINAL/EOU barrier closed.
  Exactly one SRS TX started/completed, 373 frames, no recorded failures,
  zero Qwen calls, clean presentation shutdown and host exit code zero.
- Physical end to final barrier: 422 ms. TTS start to first PCM: 2500 ms;
  first PCM to first SRS frame: 16 ms. Physical end to first SRS frame:
  **3000 ms**, again a transmission-start proxy rather than acoustic onset.
- Same implementation HEAD plus the previously recorded diagnostic changes;
  no runtime code changes between these two successful turns.

The unsupported physical query/no-operational-TX gate is still pending.
The full milestone is not yet CLOSED.

### Unsupported-query attempt — inconclusive transport failure

The user reported silence, but
`C:/Users/Алексей/AppData/Local/Temp/orion-full-voice-h2_3zaz3/report.json`
contains zero completed turn records, `provider_transport_failure`, no transport
events, and clean presentation shutdown. Host exit code: 1.
Original report SHA-256:
`43455B2D23051E8D34E5FB5483012DDB04887357B227F82540A3FD822E827A75`.

This is NOT a passed unsupported-query gate: recognition and an explicit
unsupported routing result were not established. The normalized error alone
does not establish idle timeout, billing, authentication or another precise
provider root cause. Preserve the evidence unchanged. A new bounded physical
attempt is required; no semantic/STT/VAD/radio behavior is changed to obtain it.

### Unsupported-query retry — PASS

The user spoke the requested unsupported-query test and reported `тишина`
(silence). The new report establishes an actual nonempty recognized utterance,
matching FINAL/EOU barrier and Core result `unsupported`, not transport failure
or empty recognition:

- Evidence: `C:/Users/Алексей/AppData/Local/Temp/orion-full-voice-h9p79h8n/report.json`.
- Original SHA-256:
  `7441A8A2D2266F9AC1E88891E71237C73A7B03B087607043290DC956B517D541`.
- Interaction: `c9c3b462-e679-4b61-80b2-19c9d579318b`; 125440 bytes at 16 kHz,
  3920 ms, 16 final characters; physical end to final barrier: 422 ms.
- Transcript SHA-256:
  `1c7329d38a21b94b9a7eadd042cb8980a1b677ffcc9de95e9faab0478b8c4ba9`.
  Exact recognized spelling is not stored and is not claimed to be
  byte-identical to the displayed test instruction. The nonempty final and
  explicit unsupported result are evidenced independently of user silence.
- No protected text, TTS/presentation marks or transport events. In the tested
  field code, presentation is invoked only when Core supplies a finalized
  response; this unsupported result did not do so. No failures; zero Qwen
  calls; clean shutdown; host exited with code zero.

## Final bounded milestone closure

The two supported physical turns produced exactly one completed SRS response
each, both heard clearly by the user. The second used changed heading and both
coordinates with a new authoritative ToolGateway result. The unsupported
physical turn produced a nonempty final, explicit rejection and no output,
corroborated by user silence. All original Temp reports remain unchanged.

Final diagnostic regression rerun: **57 passed**, one existing Starlette warning;
scoped Ruff PASS, touched runtime Pyright 0 errors/0 warnings, diff check PASS.
Earlier broad results remain 1768 passed / 3 documented unrelated Saved Games
baseline failures; no claim is made that the whole repository suite is green.

Two implementation commits remain unchanged:
`ba627867fe92acab7d54297844c3f38339b38f61` and
`ba43a2c52f952a43cec0adde2bce99394a6c71d1`.
The final evidence commit includes this document plus the small scalar-only
input diagnostics in `orion/full_voice_stt.py`, their report attachment in
`orion/full_voice_field.py`, and `tests/test_full_voice.py`. Unlike the preferred
docs-only third commit, these already field-tested diagnostics are retained
to make the tested tree reproducible; no new transport/semantic behavior is
introduced at closure. Unrelated untracked artifacts are not staged.

Limits remain explicit: 3.266 s / 3.000 s physical-end-to-first-frame proxies
miss the ideal <1 s objective. Earlier failed sessions remain recorded and
their precise transport cause unresolved; successful bounded gates are not
proof of long-running reliability. This is the controlled ownship vertical,
not general conversational coverage, a Launcher migration or production rollout.

After the last turn, no dedicated field host remains and UDP7082/45100 are
free. DCS, SRS Server and the official SRS Client remain running and externally
owned. No further provider/audio requests, implementation stage, merge or push
is started as part of closure.

FIRST FULL BIDIRECTIONAL VOICE VERTICAL — CLOSED / FIELD VALIDATED
