# Stage 7A — Pilot Core Phraseology Renderer MVP (offline)

Baseline: `a955d7c39f20c020e15de6bc2be272755928cc98` on
`recovery/a955d7c-radio-validated`. Sources: that exact tree and its read-only
post-6B audit. No later architecture or implementation was consulted.

## Purpose and ownership

**NON-NORMATIVE: PILOT_SYNTHETIC_V1 is a synthetic mechanics test, not aviation
phraseology approved for operational use. It claims no ICAO, FAA, NATO or FAP
compliance.** Even the laser-code digit range below is a synthetic formatting
exercise, not validation of an operational laser code.

`PhraseologyRenderer(ruleset).render(unit, context)` implements:

```text
OperationalSemanticUnit + CommunicationContext
  -> deterministic Core rule selection and value formatting
  -> ProtectedOperationalFragment
```

The existing communication contracts are reused unchanged. Core supplies an
already-decided OSU. The renderer cannot establish truth, grant a clearance,
select a heading, query WorldModel or execute a tool. It returns a fragment
without provider, presentation, audio, radio, domain or Launcher integration.
The fragment must never be returned to Qwen for rewriting.

## Rules and selection

The caller explicitly injects `synthetic_pilot_ruleset()`, a fresh immutable
`PilotRuleset` containing ten immutable rules. There is no mutable global rule
registry, active KB, updater or production profile switching.

Selection uses exactly profile, domain, explicit operational language, OSU unit
type and semantic meaning. This pilot uses the existing `ICAO` identifier only
as a selection axis, `en-US`, nine NAVIGATION rules and one JTAC laser-information
rule. This does not establish real profile coverage or migrate either domain.
Input language and conversational `FOLLOW_USER` policy do not select wording.
An absent operational language is rejected; there is no English default.

OSU status/polarity must exactly match the selected rule. Instructions require
`issued/positive`; information requires `available/positive`; altitude correction
requires `issued/negative`; heading unavailable requires `unavailable/negative`.
These are validation constraints, not domain decision logic.

Only version `PILOT_SYNTHETIC_V1` is accepted. Optional context version/snapshot
fields may be null (the explicitly injected ruleset still applies) or exactly
`PILOT_SYNTHETIC_V1`. Other identifiers fail closed. The snapshot token here is
a synthetic fixture identity, not an active normative KB snapshot. Reordered
rules produce identical output. Missing/changed rules or changed wording under
the same version are rejected. Rule count is bounded to 12, prefixes to 120
characters, scalar text to 32; each pilot rule consumes exactly one value,
except unavailable heading, which consumes none. No general template language
or extensible production KB schema is introduced.

## Formatting matrix

| Synthetic case | Protected kind / input | Output example |
|---|---|---|
| Heading assignment | HEADING, integer 0–359, `deg` | `Fly heading one three seven deg.` |
| Altitude instruction | ALTITUDE, integer 0–999999, `ft` | `Maintain altitude 12450 ft.` |
| Speed instruction | SPEED, integer 0–9999, `kn` | `Maintain speed 286 kn.` |
| Frequency information | FREQUENCY, string with 1–3 integer digits and exactly 3 decimal digits, `MHz` | `Frequency 264.500 MHz.` |
| TACAN information | TACAN, canonical string 1–126 plus X/Y, no unit | `TACAN 44X.` |
| Laser information | LASER_CODE, four ASCII digits as a string, no unit | `Laser code zero one five seven.` |
| Callsign information | CALLSIGN, bounded ASCII letters/digits separated by single space or hyphen, no unit | `Callsign Viper 2-1.` |
| Distance information | GENERIC, explicit distance key, canonical nonnegative decimal string, `NM` | `Distance 63.0 NM.` |
| Negative altitude correction | ALTITUDE, integer -999999 to -1, `ft` | `Altitude correction -850 ft.` |
| Heading unavailable | No protected values | `Heading unavailable.` |

Heading uses three digit words with explicit zero padding. Laser text preserves
all four digits including leading zeros. Other strings retain their literal
spelling; altitude/speed retain the exact integer and sign. Unit tokens are
preserved literally. No rounding, numeric string coercion, implicit unit
conversion, localization, abbreviation expansion or provider naturalization
occurs. Integral floats are deliberately unsupported. Distance has at most six
integer and three decimal digits. Frequency disallows a leading zero. Runway,
coordinates and BRAA formatters are outside this pilot.

## Provenance, priority and failures

The returned fragment embeds the original OSU object, preserving its values,
priority and entire provenance tuple. Empty provenance remains empty; this
renderer does not invent or verify fact authority. Synthetic probe provenance
is explicitly labelled `synthetic_probe`. `rendered_by_core=True` identifies
wording origin, not world-truth origin. `renderer_version` records
`stage7a.renderer.v1/PILOT_SYNTHETIC_V1`; no parallel fragment type is added.

`PhraseologyRenderError.code` is a bounded enum for unsupported profile, domain,
language, semantics, kind or ruleset, missing/conflicting values, malformed
value/unit and invalid ruleset. Error messages contain only that code, never
caller values. Pydantic contract construction failures remain ValidationError.
Extra or duplicate protected values are rejected rather than silently dropped.
Status/polarity mismatches are rejected rather than reinterpreted. Failure order
is deterministic: version, profile, domain, language, semantics, value shape,
key, kind, unit, formatter.

The existing `CommunicationPriority` is preserved in the OSU. The renderer does
not reorder queues, preempt transmissions or compose/suppress an envelope.

## Offline probe and gate

`python -m orion.phraseology_probe` evaluates a fixed 14-case matrix: ten exact
text/fragment expectations and four expected typed rejections. Expected text is
independently authored, not calculated from renderer templates. The immutable
report has no timestamps, random IDs, persistence or network operations. CLI
output is deterministic JSON, exit 0 for complete PASS and 1 for any mismatch.

Stage 7A has 30 deterministic tests, including malformed scalar/unit boundaries,
sign/leading zeros, extra/duplicate values, input immutability, provenance,
priority, rule ordering, version identity, failure isolation and probe mutation
detection. An AST gate limits imports to offline contracts and standard helpers.
The existing IA-0 consumer allowlist adds only the two new modules; its boundary
assertion remains otherwise unchanged.

Validation includes focused and existing communication tests, historical IA
regressions, the broader isolated historical suite, Ruff, touched-file Pyright
and `git diff --check`. No live provider, DCS, SRS or acoustic validation is needed
to establish this offline wording boundary.

### Recorded validation

- 30 focused Stage 7A tests and 5 unchanged communication tests passed.
- 164 combined Stage 7A/communication/IA-0/IA-2/IA-3/IA-4/IA-5/IA-6 regression
  tests passed.
- Full isolated historical suite: 1508 passed (1478 historical + 30 Stage 7A).
- Ruff across `orion` and `tests`: PASS. Pyright for new/touched Python files
  plus all ten historical CI hardening targets: zero errors/warnings.
- Offline CLI probe: 14/14 expected outcomes, exit 0. Renderer branch-inclusive
  coverage: 99%; probe: 93%; combined: 98%.
- Historical repository coverage scope: 81.98%, above the unchanged 80% gate.

Environment findings are not source fixes. The first full run exposed three
pre-existing `test_setup_wizard_model.py` failures (`manual_dcs_and_saved_games`,
`changing_dcs`, `auto_detect_candidate`) because Windows Known Folder discovery
found the real account's Saved Games despite a temporary USERPROFILE. The same
three failures were reproduced on an untouched `git archive a955d7c`. An
external pytest shim made `_windows_saved_games_root()` return None, allowing
the existing USERPROFILE fallback to use an empty temporary account; dedicated
discovery tests still supplied their own fixtures. No repository test or
runtime discovery logic was changed for this isolation.

Coverage subprocess collection initially mixed branch and statement data.
An explicit absolute COVERAGE_RCFILE and a fresh COVERAGE_FILE resolved the
combine error. The initial combined report also included the four UI files
already excluded by `[tool.coverage.run].omit`, giving 78.07%. Applying those
same four exclusions at report time with `*/orion/...` path patterns produced
81.98%; no new file exclusion or threshold reduction was introduced. The
external harness and generated evidence were retained outside the worktree.
One dependency warning concerns Starlette's deprecated httpx TestClient path;
it is unrelated to Stage 7A and was not changed.

## Stop boundary

No normative data/source registry/acquisition/update/rollback lifecycle, generic
SemanticResponse-to-OSU mapper, social-envelope producer, ResponseComposer,
PresentationRouter, TTS, Realtime, RadioRouter/SRS wiring, STT/PTT, domain
migration, WorldModel/ToolGateway/IA-6 expansion, Launcher changes or unrelated
cleanup. Future production content, integration and any next development stage
require separate authorization.
