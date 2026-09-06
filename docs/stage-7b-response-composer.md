# Stage 7B — Core Deterministic ResponseComposer MVP (offline)

Baseline: `aac36933517bbaac21e4085604eb9a24b973ae1c`, branch
`recovery/a955d7c-radio-validated`. Sources are this exact tree, its docs/tests,
the completed post-7A audit and explicit historical implementation authorization.
Architecture Guard is OFF by explicit authorization for this recovery line.
No later architecture or implementation is a source.

## Purpose and ownership

`ResponseComposer().compose(plan: ResponseCompositionPlan)` returns
`FinalizedCommunicationText`. Core owns composition, ordering, suppression and
fail-closed validation; it does not establish operational truth, decide domain
actions or render new phraseology. Stage 7A remains unchanged.

The input is the existing plan, not a parallel plan or a SemanticResponse mapper.
At least one protected fragment is required. An envelope-only plan fails with
`UNSUPPORTED_COMBINATION`; a plan with neither envelope nor fragments fails with
`EMPTY_OUTPUT`. Nonempty advisory always fails with `UNSUPPORTED_ADVISORY`;
it is never ignored, rendered, or reclassified.

## Structured finality and trust

The new frozen, extra-forbid Pydantic result has:

- `text`: strict string, with no stripping/normalization;
- `context`: the original CommunicationContext;
- `priority` and `interaction_id`: original plan values;
- `envelope`: original optional frozen, untrusted envelope;
- `protected_fragments`: tuple containing original fragments and their OSUs;
- `suppress_conversational_envelope`: the original suppression flag;
- `composer_version`: literal `stage7b.composer.v1`.

Renderer versions and operational provenance stay in their original fragments.
The read-only `provenance` property derives a tuple of original provenance objects
in fragment order, without deduplication or authority upgrades. It is not a second
serialized provenance store: serialized fragments contain all original sources.
No session/turn IDs are invented: the current plan/context exposes neither.

Suppressed envelopes remain in the structured object for faithful source retention,
but are absent from `text`. Consumers must use the finalized text and suppression
flag, not independently concatenate source fields. Retention does not authorize
logging: the object contains operational/provenance data, including suppressed
untrusted text. No persistence or logging is introduced.

The result is completed Core composition, not a draft, SemanticResponse, input
plan, isolated fragment, or synthetic TestSemanticCase string. Its constructor
checks that text exactly matches the structured parts and suppression. It is not
a security attestation: construct/copy bypasses and forged Core-origin assertions
are not an authenticity system. Production callers must use the composer boundary.

The whole response is not marked operationally authoritative. Envelope proximity
never changes its `authoritative=False`, `droppable=True` contract. Frozen/bounded
envelope text may still contain incorrect operational claims; semantic analysis or
generation of the envelope is explicitly absent. Protected wording must never be
returned to Qwen or any generative provider for rewriting.

## Ordering, preservation and suppression

Order is optional unsuppressed envelope, then fragments in the exact supplied
tuple order. Separator is one ASCII space (`COMPOSITION_SEPARATOR`). There is no
sorting, punctuation insertion within fragments, Unicode normalization, stripping,
case conversion, numeric formatting, unit conversion, localization or translation.
Preservation refers to each already-created fragment's stored `text`; upstream
SemanticText validation may already have stripped outer whitespace.

`CommunicationPriority` is reused without a new enum or mapping:

- ROUTINE / IMPORTANT / URGENT: explicit suppression omits envelope text;
  otherwise include the envelope when present.
- IMMEDIATE: the existing plan contract requires suppression true and envelope
  absent. An unchecked malformed plan is rejected, not silently repaired.

All fragment domains must exactly equal the plan CommunicationDomain, with no
GENERAL wildcard; all fragment OSU priorities must equal plan priority. Mixed
priorities are rejected, not promoted or aggregated. Source provenance domains
are preserved, not mistaken for the output domain.

Fragments expose no render profile/language/context witness. Therefore the composer
cannot verify a profile/language mismatch against the original render context.
It preserves the supplied context but does not infer metadata from wording or
renderer_version, re-render, or claim presentation readiness for such a pairing.

## Exact structural duplicates

Two fragments are duplicates only under existing Pydantic structural equality:
text, `semantic_unit` (the actual field name, including all protected values,
status, polarity, priority and provenance), renderer version and Core-origin flag.
Identity is not required. A repeated equal fragment causes `DUPLICATE_FRAGMENT`;
there is no silent deduplication. Same wording with structurally different OSUs or
renderer versions is allowed. No fuzzy/semantic comparison, normalized comparison,
cross-plan replay detection or actual transmission guarantee is claimed.

## Bounds

| Constant | Value |
|---|---:|
| MAX_ENVELOPE_CHARS | 512 |
| MAX_PROTECTED_FRAGMENTS | 8 |
| MAX_FRAGMENT_CHARS | 1024 |
| MAX_FINAL_TEXT_CHARS | 4096 |

These are the authorized Stage 7B safety defaults, not permanent product policy.
Character bounds use Python string length, not UTF-8 byte length. Separators and
included envelope count toward final length. Suppressed envelopes still undergo
input validity and envelope-size checks, but do not count toward final text.
Overflow fails closed without truncation. The result uses a dedicated strict
string instead of SemanticText because SemanticText strips and is capped at 4000.
The existing SemanticText contract is unchanged.

## Failures and ingress validation

`ResponseCompositionError.code` is a bounded `CompositionFailureCode`:
INVALID_PLAN, UNSUPPORTED_ADVISORY, EMPTY_OUTPUT, UNSUPPORTED_COMBINATION,
ENVELOPE_TOO_LARGE, TOO_MANY_FRAGMENTS, FRAGMENT_TOO_LARGE,
FINAL_TEXT_TOO_LARGE, DUPLICATE_FRAGMENT, DOMAIN_MISMATCH, PRIORITY_MISMATCH.
Exception text is the code only, not caller text or Pydantic error payloads.
No fictitious LANGUAGE_MISMATCH check is advertised without a contract witness.

Composer first validates a Python snapshot of the plan strictly, including nested
models. This catches unchecked model_copy/model_construct invalid states rather
than trusting Pydantic's default instance-revalidation behavior. A changed snapshot
after validation is rejected, never used to rewrite originals. Validated copies
are discarded: output retains the original objects. Ordinary contract construction
outside compose still uses Pydantic ValidationError; the composer does not log it.

Deterministic rejection order: ingress validity; advisory; protected-fragment
presence; envelope size (even suppressed); fragment count; then for each fragment
size, domain, priority and prior structural duplicates; final text size; finalized
result validity. No partial output, fallback, I/O or mutable runtime state exists.

## Offline gate

`tests/test_response_composer.py` uses independent exact expectations and existing
non-normative Stage 7A fixtures. It covers basic/mixed ordering, Unicode/UTF-8,
values/sign/leading zeros/units, source identity and provenance, every priority,
suppression, structural duplicates and distinct same-text OSUs, all bounds,
advisory rejection, domain/priority mismatch, unsupported render-context checks,
empty cases, unchecked malformed nested inputs, immutable structured finality,
repeatability, failure isolation and an AST import/call boundary.

Run focused composer + communication + renderer tests, relevant historical IA
regressions, the practical broader historical suite, Ruff, touched-file and
historical CI Pyright targets, and git diff --check. Test outcomes are recorded
below only after execution. No live provider/DCS/SRS/acoustic gate is required.

### Recorded validation

- Stage 7B: 35 deterministic tests passed; unchanged communication contracts:
  5 passed; unchanged Stage 7A: 30 passed (70 combined).
- Expanded interaction/planner/ToolGateway/semantic binding/radio regression:
  248 passed, including the Stage 7B/communication/Stage 7A tests.
- Full isolated historical suite: 1543 passed (1508 baseline + 35 Stage 7B).
- Focused branch-inclusive coverage for communication_contracts + composer:
  99.15% combined; contracts 100%, composer 98% (defensive output-error handler
  is not exercised). This is focused coverage, not a new whole-repository metric.
- Ruff across orion/tests and formatting checks for the three Python files: PASS.
- Pyright for the three Python files plus all ten historical CI hardening targets:
  zero errors/warnings, with the dependency interpreter explicitly selected.
- git diff --check: PASS. Existing test expectations and consumer allowlists are
  unchanged; composer imports communication contracts, not IA-0 directly.

The installed dependency environment was reused only as an interpreter/library
source. ORION imports were checked to resolve to the recovery worktree; full-suite
subprocesses received an explicit recovery PYTHONPATH. No later source was loaded.
The full suite used an external test-only plugin to make Windows Known Folder
discovery return None and a fresh temporary USERPROFILE/LOCALAPPDATA, following
the environmental isolation documented in Stage 7A. Dedicated discovery tests
still apply their own fixtures. No repository discovery code or expectations were
changed. This is an isolated-suite result, not a real-account DCS discovery gate.
The only full/regression warning is the existing Starlette/httpx deprecation.
The external harness and generated test evidence are retained outside the commit.

## Explicit stop boundary

There is no provider, presentation, TTS, PCM/audio or radio integration. In
particular no Qwen round-trip, Production PresentationRouter, SpeechKit/Realtime
wiring, RadioRouter submission, SRS change, social-envelope generation/semantic
analysis, advisory rendering, phraseology expansion, normative KB/source work,
domain migration, SemanticResponse-to-OSU mapper, STT/PTT, RadioEntity resolver,
Launcher, Internet updater, Source Registry, DCS Voice Chat, WorldModel,
ToolGateway or Planner/IA-6 change. Production mixed conversation is NOT complete.
Next-stage selection/implementation requires separate authorization.
