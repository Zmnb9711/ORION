# Bounded hybrid aircraft identity — offline/build checkpoint

ORION ARCHITECTURE GUARD: OFF (historical recovery exemption).

Status: IMPLEMENTED + OFFLINE/BUILD VALIDATED; FIELD VALIDATION PENDING.
This is a new integration, not an already field-proven historical complete route.

## Source and scope

Branch: `codex/hybrid-aircraft-identity-after-cleanup`.
Worktree: `C:/Users/Алексей/Documents/GitHub/ORION-hybrid-aircraft-after-cleanup`.
Clean starting chain:
`333ca5e481c89b8294e0f491fbd2d2e6d6e87319`
→ `7b041d64b663fad1862c14d960c2b9c52cab0c99`
→ `474d11bc349ce70986524faf9b53ed7968e25c24`.
Implementation/build source: `4ca5effe2c5772a3268ba1f131bbad77a095c7ea`;
parent `474d11bc349ce70986524faf9b53ed7968e25c24`.
Subsequent documentation-only checkpoint does not change packaged production code.

Five existing production files changed: `full_voice_service.py`,
`yandex_qwen_planner.py`, `protected_presentation.py`,
`protected_streaming_tts.py`, `realtime_test_evidence.py`.
Three new modules: `hybrid_aircraft_contracts.py`, `hybrid_aircraft_core.py`,
`informational_presentation.py`. All are under `orion/`.
No changes to Launcher, STT, full_voice_core, InteractionRouter, WorldModel,
ToolGateway, phraseology/ResponseComposer, SRS algorithms/configuration,
RadioRouter, protected_streaming_presentation, truthful STOP or Qwen cleanup.

## Historical reuse

| Source | Concept | Treatment |
|---|---|---|
| `27e94bdbf843a3f1895db2756eed49e42fe07989`, aircraft_identity_query.py | Whole-utterance recognizer, typed aircraft projection/exact binding | ADAPT; narrow Russian grammar, stricter quote handling, CURRENT ToolGateway instead of direct WorldModel |
| `9f38d449cf94fb0d8c5534488a59e4031b73dad4`, mixed_conversation.py | Bounded decomposition and local composition | REIMPLEMENT SMALL CONCEPT; no provider wording, no emitter/tool call, no ATC implementation |
| Isolated 333ca5e prerequisite seams | Accepted-operation helper and TTS builder hook | COPY the proven mechanical seams; 67 before/after tests repeated against 474d11bc |
| Historical formulation / ATC / D75 presenter / historical SRS | Broader implementations | DO NOT USE |

## Runtime contract

FINAL → unchanged FullVoiceCore first. Only its `unsupported` result opens the
new slice; failures/cancellation never fall through. Frozen ownship uses zero
Qwen calls and unchanged protected presentation/TTS.

Pure recognizer accepts whole Russian utterances:
`в каком самолете я нахожусь`, `на каком самолете я нахожусь`,
`на каком самолете я сейчас нахожусь`, `какой у меня самолет`.
Case, ё/е, whitespace and terminal punctuation are recognition-only; FINAL itself
is never replaced. `Какой это самолёт?` is AMBIGUOUS and silent. Corrupted,
quoted, negated, hypothetical and extra-question/command inputs fail closed.

Eligible mixed/social inputs use exactly one existing Qwen Responses transport
request (max_attempts=1, store=false, no tools). Strict output is ONLY
`classification`, `language=ru-RU`, `spans[{start,end,act}]`; extra fields forbidden.
Core verifies source bounds, ordering, no overlap, complete meaningful coverage,
exact bounded social/aircraft grammar, ≤2 distinct social acts, ≤1 aircraft query.
Reverse ordering is supported through spans, not prefix removal.
Classes: AIRCRAFT_IDENTITY, FREE_PLUS_AIRCRAFT_IDENTITY, FREE_ONLY,
UNSUPPORTED, AMBIGUOUS. Rejected decomposition produces no read/response.

Aircraft: actual `orion.world.ownship.get@1.0`, input
`orion.tool.arguments.none.v1`, output `orion.tool.output.ownship.v1`, snapshot
`ia2.world.v1 / ownship.current_state`, selected field `ownship.aircraft` only.
The provider never receives ToolResult or aircraft facts. Core checks receipt
call/actor/interaction/session/turn/tool/version, completed handler, capability,
schema, snapshot generated-at/read interval, DCS_EXPORT/AUTHORITATIVE,
field status, generation membership and age consistency. Callsign/position/
heading/fuel/other telemetry are not projected.

Known current aircraft expires at the minimum of the 15-second hybrid deadline,
receipt accepted-at + (5 seconds − original fact age), and observed-at + 5 seconds.
No TTL reset. The current SRS first-frame expiry guard is reused unchanged.
Stale/unknown/unavailable/unsafe identity yields the local unavailable sentence,
not a current-aircraft claim. Unknown safe compact DCS identifiers use the existing
registry normalization; unknown prose-like identifiers are unavailable.

Local social rendering: GREETING → `Добрый день!`; THANKS_ACKNOWLEDGEMENT →
`Пожалуйста.`; SOCIAL_WELLBEING_QUERY → `Всё нормально, я на связи.`
Aircraft template: `По данным DCS, вы находитесь в {display_name}.`
Unavailable: `Сейчас не удалось определить тип вашего самолёта.`
No provider-generated response text survives.

Informational admission requires FinalizedInformationalText, the exact cached
Core execution result (not a forged plausible receipt), a valid typed plan,
fresh provenance, exact independent local re-render equality and matching radio
interaction/turn/session/domain/priority. Protected admission is not relaxed.
The operation helper and existing streaming execution are borrowed unchanged.
RU informational changes only voice to `jane`; protected remains `john`.
The finalized string equals the actual protobuf synthesis_input.text exactly.
No strip/translation/SSML/rewriting/retry/resampling/pacing changes.

One existing workflow serializes responses. Hybrid STOP propagates to its
planner token, without changing frozen ownship cancellation/lifecycle behavior.
No authoritative read after failed/cancelled decomposition. Existing 0.5-second
cleanup owner is reused; cleanup failure reaches truthful ERROR. No new worker
or long-lived provider session. Core and presentation replay caches are bounded
to 64 identities, without eviction/re-execution; conflicting replay is rejected.

## Evidence

Existing explicit Test Session recorder only; unchanged START/STOP/export and
no new WAV recorder. Fields: test/runtime/turn IDs, exact existing STT FINAL,
route/pure match, decomposition requested/result/validation, call count/category,
read start/return/tool/version/call reference, aircraft-only projection and real
receipt/provenance/freshness, plan, exact finalized text, admission/rejection,
exact protobuf TTS input, existing TTS start/first PCM/completion/byte marks,
response terminal/failure category/stage, SRS first-frame/completion marks.
`frames` is admitted through the existing SRS recorder; host terminal observation
also uses the existing packet_id delta, including partial successful sends.
No stale previous-turn TX marks are reused. No secrets, provider bodies, hidden
reasoning or unrestricted ToolResult; recorder failures remain non-fatal.
Normal operation does not retain these informational texts.

## Offline proof

Focused gates: 241 passed, four N/A skips (provider STOP on provider-free routes).
Final broader regression: 414 passed, same four N/A skips; 38.99 seconds.
One existing Starlette/httpx deprecation warning; no unrelated fixes.
Pyright: zero errors/warnings for eight touched production files.
Ruff: all touched production/test files PASS. compileall and git diff --check PASS.
Before/after seams: 67 tests. Seams + cleanup/truthful STOP set: 118 tests.
Golden differential compares exact `57a563a` field-host fixtures with the current
normal service path; STT options, PCM, exact protected TTS requests, response and
control trace remain equal for the frozen query matrix.

Reports:
`C:/Users/Алексей/Documents/ORION-Restoration/hybrid-aircraft-focused-20260908.xml`
and `C:/Users/Алексей/Documents/ORION-Restoration/hybrid-aircraft-regression-20260908.xml`.

All commands ran from this worktree with
`PYTHONPATH=<worktree>/tests;<worktree>` and
`C:/Users/Алексей/Documents/GitHub/ORION/.venv/Scripts/python.exe`.
The broader command was:

```text
python -m pytest -p test_truthful_voice_stop tests/test_hybrid_aircraft.py tests/test_hybrid_host.py tests/test_hybrid_seams.py tests/test_full_voice.py tests/test_full_voice_srs.py tests/test_yandex_srs_live_core.py tests/test_yandex_qwen_planner.py tests/test_qwen_cleanup_bound.py tests/test_qwen_cleanup_full_voice_stop.py tests/test_truthful_voice_stop.py tests/test_voice_stop_lifecycle.py tests/test_tool_gateway.py tests/test_world_model.py tests/test_protected_presentation.py tests/test_realtime_live_core.py tests/test_realtime_session_control.py tests/test_fallback_baseline.py tests/test_fallback_voice_equivalence.py tests/test_stt_core_observation.py tests/test_realtime_test_evidence.py tests/test_interaction_router.py -q --tb=short -o junit_family=xunit1 --junitxml=C:/Users/Алексей/Documents/ORION-Restoration/hybrid-aircraft-regression-20260908.xml
```

Required matrix coverage (`test_hybrid_aircraft.py` unless specified):

| Requirement numbers | Proof |
|---|---|
| 1, 2 | test_hybrid_host, fallback_voice_equivalence, qwen_cleanup_full_voice_stop; gate02_routing |
| 3–16 | gate02_routing: pure/mixed/alternate/reversed/FREE/greeting/thanks/ambiguous/quoted/negated/hypothetical/fuel/operational residue |
| 17–20 | gate03_span_safety; gate08_invalid_decomposition_never_reads |
| 21–24 | gate01_strict_schema; gate08_real_qwen_io_extension_one_request_cleanup |
| 25–27 | gate08_cancellation_and_provider_failures; actual host stop_provider cases; existing cleanup tests |
| 28–30 | gate04_missing_stale_unknown; gate04_real_no_dcs_read_stays_unavailable |
| 31 | gate04_bad_receipt_provenance; gate06 fake_receipt rejection via actual Core execution binding |
| 32–35 | gate05_extra_telemetry_cannot_leak_any_boundary; strict schema and gate06 fake/tampered output |
| 36–39 | gate06_typed_admission |
| 40–42 | gate07_ru_builder_exact_and_john_unchanged; gate08_ru_actual_stream_rpc_exact_text_and_closed; test_hybrid_seams |
| 43 | gate06 expired; unchanged test_full_voice_srs stream_tx_fails_closed[expired] |
| 44,45 | gate08_cancellation_and_provider_failures[before_read,after_read] |
| 46–48 | gate08_stream_failure_cancel_and_conflicting_replay; existing protected/streamed SRS tests |
| 49,50 | gate08_replay_and_pure_provider_independence; gate06 replay; gate08 stream conflict |
| 51,52 | test_qwen_cleanup_bound, test_qwen_cleanup_full_voice_stop, test_truthful_voice_stop, test_voice_stop_lifecycle |
| 53,54 | test_fallback_baseline; test_hybrid_host gate11 source guard |
| 55 | test_hybrid_host actual normal service; real local Router + streaming fake adapter; replay tests |

## Product build/package

One normal build, same build commands as preserved 333ca5e packaging; no installer
architecture modifications. Build root:
`C:/Users/Алексей/Documents/ORION-Builds/hybrid-aircraft-4ca5eff-20260908`.
`build.ps1` runs PyInstaller once for ORION-Core and once for ORION-Launcher and
assembles `product/Core`, `product/Launcher`, `product/Integration/DCS/Export`.
Existing `source/packaging/orion-alpha.iss` compiled once by Inno Setup with only
ProductSourceDir/InstallerOutputDir command-line path overrides.

`verify_package.py` verifies 714 archived files unchanged, origins of 328 Core /
320 Launcher ORION modules, and actual Core executable PYZ bytecode equivalence
to every archived ORION module. Only three module additions versus the preserved
333ca5e build; no new third-party modules. Existing smoke/probe modules remain
as in the old collect-submodules packaging; new tests are not packaged. Opus DLL
hash unchanged. No SRS executable/config, evidence JSONL/WAV, test-evidence or
new test files enter the product. Per-file hashes are in `artifact-identity.json`.

All three existing `smoke.ps1` checks PASS: native, Launcher control, integrated
Launcher → exact Core → shutdown. Integrated smoke used per-process temporary
runtime and ephemeral telemetry ports, loopback-only HTTP, no audio devices,
no external SRS process, no retained credential, no orphan Core. Installed files
were NOT modified. No DCS/SRS/provider/PTT calls or physical field test.

| Artifact | SHA-256 |
|---|---|
| source.zip | `0a8d825b05644a983f1e34b5cc2cab3fadba7c88d3dbd5b3bf1d8d67f439d9c7` |
| product/Core/ORION-Core.exe | `1158be50b9f3f20ccf7e640ff2486a5cda02246ccb49bc388e00db6a06ef33c3` |
| product/Launcher/ORION-Launcher.exe | `af5caa43540bbf365dc3160695c6473c04edc0e3fc4a2ea8f45a79eb74b90fb9` |
| installer/ORION-Alpha-0.2-Setup.exe (84,148,043 bytes) | `51d4865cf07170e2bcf9cacc94e8f3794fb8d28505b135e55506a9c9db76f023` |

Version remains 0.2.0-alpha; source SHA is recorded in the archive/identity manifest,
not a new runtime identity feature. Installer is NOT installed. No merge/push.

## Future physical gate — separately authorized, not executed

After authorized installation/identity verification and a normal explicit Test
Session, one controlled installed-product session:

1. `Добрый день! В каком самолете я нахожусь?` — one RU aircraft answer.
2. `Какой мой текущий курс и координаты?` — unchanged protected ownship answer.
3. `Добрый день! Как дела?` — bounded social answer, zero DCS reads.
4. `Какой это самолёт?` — AMBIGUOUS, silence, zero DCS reads/TTS/TX.
5. Optional `какой мой текущий вкус или оригинал` — unsupported, silence.

Physical PTT/speech/acoustic confirmation remain PENDING. No open-ended chat,
ATC/domain migration, STT robustness, latency optimization or new capability is
authorized by this checkpoint. Freeze only after a separately executed field PASS.
