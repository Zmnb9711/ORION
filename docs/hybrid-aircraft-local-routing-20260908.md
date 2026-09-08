# Bounded local Hybrid Aircraft routing — 2026-09-08

ORION ARCHITECTURE GUARD: OFF (explicit historical recovery exemption).

## Status and exact source identity

IMPLEMENTED + OFFLINE/BUILD VALIDATED. FIELD RETEST PENDING.

Parent: `013a36a956cb67565290c506c0e7bda0a89fdf24`.
Required ancestry verified: `333ca5e` -> `7b041d6` (truthful STOP) ->
`474d11b` (bounded cleanup) -> `4ca5eff` -> `013a36a`.
Dedicated branch: `codex/hybrid-aircraft-local-routing`.
Worktree: `C:\Users\Алексей\Documents\GitHub\ORION-hybrid-aircraft-local-routing`.

Implementation/build commit: `f0c9e364ed653e9497d7e2ef8ef8f35dc97157d4`.
Exact built tree: `cb167c0c15425e94739b712196836f60071bb686`.
The staged tree was archived and built once BEFORE creating its commit, as
required. The implementation commit has that exact tree. This documentation
checkpoint is recorded separately AFTER successful build/smoke validation;
it is not an additional product build or implementation change.

## Historical rationale, without rewriting history

Qwen mixed interpretation was historically allowed and experimentally useful,
but was not required for a known closed fast path. The saved physical attempts
recorded 13.953/10.531-second decomposition intervals INCLUDING cleanup; they
demonstrated an unnecessary network dependency for this closed grammar, not a
general prohibition on Qwen NLU. No new provider measurements were performed.
The historical architecture audit confirmed Core selection of known fast paths
before Planner. Planner/reasoning remains available independently.

## Exact production surface

Only two production files differ from `013a36a`:

| File / symbol | Change |
| --- | --- |
| `orion/hybrid_aircraft_core.py:recognize_local_decomposition` | Partition the complete bounded input into the existing typed acts and exact source offsets. No direct route assignment. |
| `orion/hybrid_aircraft_core.py:HybridAircraftCore._run` | Use the local candidate, then the unchanged validator and Core route mapper. Never call the retained provider factory or fall back to Qwen. |
| `orion/realtime_test_evidence.py:record_aircraft_slice` | Admit `decomposition_completed` and strictly bounded `decomposition_source=LOCAL/PROVIDER`; preserve legacy events. |

`validate_decomposition`, `derive_route`, pure classifier, aircraft validation,
and informational rendering are AST-identical to the parent. Everything else
under production, packaging and DCS export is unchanged, including the Planner
adapter, its cleanup, truthful STOP, Launcher, FullVoiceService, ToolGateway,
WorldModel, STT, SRS, RadioRouter and all presentation/TTS code.

The constructor retains its unused provider-factory parameter solely to keep
the normal host handoff unchanged. Tests fail if that factory is invoked.

## Closed language and source fidelity

Existing aircraft forms only:

- `в каком самолете я нахожусь`
- `на каком самолете я нахожусь`
- `на каком самолете я сейчас нахожусь`
- `какой у меня самолет`

Existing social forms only:

- GREETING: `добрый день`, `здравствуйте`, `и добрый день`
- THANKS_ACKNOWLEDGEMENT: `спасибо`
- SOCIAL_WELLBEING_QUERY: `как дела`

Existing case, ё/е, whitespace and punctuation policy is retained. Words are
never corrected. Tokens retain Python Unicode source offsets. Internal phrase
punctuation cannot be erased to manufacture a valid phrase. Up to two DISTINCT
social acts and at most one aircraft act are permitted in the already-approved
orders. Reversed order was already supported by the parent contract/tests.

The parser enumerates no more than three complete acts from these literal
forms. It is not substring routing, prefix stripping, fuzzy matching, generic
NLP or a free conversation engine. Unknown language/residue/negation/quotation/
hypothetical/repetition fails closed; no provider fallback, read, TTS or TX.
The existing frozen ownship path remains first and never enters Hybrid.

## CASE A / CASE B

Exact recorded FINAL: `добрый день в каком самолете я нахожусь`.
Local output equals CASE A structure: GREETING [0,11), AIRCRAFT [12,39).
Unchanged validation passes; Core derives FREE_PLUS_AIRCRAFT_IDENTITY;
one authoritative aircraft read, zero provider calls.

Real CASE B stays NEGATIVE: GREETING [0,10), AIRCRAFT [11,39), with `ь`
uncovered. The unchanged validator rejects `добрый ден`. The historical fixture
and original ZIPs are not changed. Fault-injected bad local candidates also
cannot bypass validation or reach the read/presentation path.

## Offline gate results

751 PASS, 4 non-applicable skips. No live network/provider/audio/PTT calls.
External network was blocked with the existing truthful-STOP test guard.
The four skips are local-decomposition STOP injection on pure/frozen/unsupported
routes that do not enter that helper; independent STOP/cleanup tests pass.

- 231 combinations exhaustively cover the existing form/act matrix, exact
  offsets, zero provider FACTORY calls, authoritative read count and replay.
- Additional full-source negatives, Unicode/punctuation offsets, real A/B,
  mandatory validate-before-derive, cancellation before/after local/read.
- Normal FullVoiceService replay checks actual Core/Gateway/presentation/request
  builder/RadioRouter with fake external endpoints, including unchanged ownship,
  corrupted FINAL, evidence active/inactive/broken and STOP during local work.
- Existing authority/provenance/freshness, extra-telemetry exclusion, raw/tampered
  presentation rejection, exact TTS request, crossing protected boundaries,
  replay and cancellation regressions pass.
- PlannerTaskRunner, Yandex Qwen adapter, bounded cleanup and truthful STOP pass
  independently. Provider-specific decomposition tests remain as backend tests,
  not as the bounded slice's runtime dependency.
- Golden/fallback, native STT terminal boundary, SRS, Launcher and source guards
  pass. Full production/test Ruff PASS; changed production Pyright: zero errors
  and warnings. Git diff/check PASS.

Warnings: existing Starlette deprecation and pytest record_property/xunit2
compatibility warnings; no test failures. Properties are present in the XML.

## Evidence and timing

Explicit Test Session records LOCAL source, exact candidate spans, validation
checking/accepted, Core route, zero provider count, aircraft-only result and
receipt/provenance, exact finalized/TTS text, response status/frame count and
existing TX/TTS marks/failure stage. Exact FINAL is preserved at the existing
STT/Core boundary. No recorder runs for ordinary inactive evidence mode.
Legacy provider events remain readable/exportable without new-schema rewriting.

Existing UTC/monotonic marks cover routing -> local completion -> validation ->
authoritative read -> composition. The saved Windows offline sample reports
0/0/0/15 ms from routing respectively; clock quantization is not zero work and
these are NOT physical latency claims. The proven improvement is removal of
the provider call/wait. TTS TTFA and the end-to-end <1 s target are untouched.

## One normal package, no installation

Build directory:
`C:\Users\Алексей\Documents\ORION-Builds\hybrid-local-routing-20260908`.
Unchanged PyInstaller/Core/Launcher and `packaging/orion-alpha.iss` build path.
Layout: `Core/ORION-Core.exe`, `Launcher/ORION-Launcher.exe`,
`Integration/DCS/Export`. Product version remains `0.2.0-alpha`.

Core SHA-256:
`8cc56898dac154df3c9f445b73d806da0b02671fe9dabdff0461ee32beb75162`

Launcher SHA-256:
`002a8039388efb5a64ab979446c345f8ecd2e85343c3c8a62f0b881a216787f6`

Installer `installer/ORION-Alpha-0.2-Setup.exe`, 84,151,828 bytes, SHA-256:
`86e32dd9719ba76621eb68b479a61f8aeecb99d1c7f9931750282c8fa9f4592f`

718 archived source files verified; module source origins checked (328 Core,
320 Launcher), Core archived bytecode matches the exact source. Native Opus
identity retained. No SRS configs, secrets, test WAVs or evidence packages ship.

Native, control and integrated product smoke: PASS. Isolated runtime paths and
ephemeral ports; no DCS/SRS process, external provider or audio device used.
Integrated smoke uses loopback only, verifies Core start/health/shutdown and
credential lifecycle, leaves no credential or orphan Core. Installer not run.
Existing Inno admin/per-user-area warning remains unchanged.

External `artifact-identity.json`, `build-source.json`, `offline-regression.xml`,
`production.diff`, build logs and three smoke JSONs retain machine evidence.
No merge or push.

## Next field gate — separately authorized, NOT performed

After separate installation/authorization, first turn only:
`Добрый день! В каком самолете я нахожусь?`

Require correct FINAL, LOCAL spans/validation, Core-derived mixed route, zero
provider calls, one authoritative aircraft read, correct RU informational text,
one completed response TX and the user's acoustic confirmation. On failure,
stop and inspect automatic evidence; do not request repeated attempts.
Only after PASS, separately check frozen ownship heading/coordinates.

LOCAL HYBRID ROUTING PASSED — READY FOR ONE MIXED FIELD RETEST
