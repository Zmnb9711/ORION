# First full bidirectional voice vertical — automated gates pass, physical test required

2026-09-07. Architecture Guard: OFF, explicit historical recovery exemption.
This is the existing full-voice milestone, not a new stage. No field closure yet.

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
