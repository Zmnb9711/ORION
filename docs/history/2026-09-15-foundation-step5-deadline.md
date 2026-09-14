# Step 5 — semantic binding/generation deadline domains

ORION ARCHITECTURE GUARD: OFF. Pre-field work, not Foundation acceptance.

CONTRACT READ: `ORION_NATURAL_LANGUAGE_FIRST_CONTRACT_V1`, canonical architecture
file unchanged. Worktree `C:/Users/Алексей/Documents/GitHub/ORION-level0-conversation`,
branch `codex/general-natural-language-ingress-tranche1`, parent
`31546f9f191b060571cba32998c8cf232b345506` / tree
`7ea6f05fb2b6ce5a8507d83400496cf30d907424`. Earlier Step5 changes/data preserved.
Explicit current prompt authorizes bounded policy correction and referent gate;
after successful clean integration it authorizes the existing commit/build/install
workflow. Not a provider/context redesign or permission to relax truth/schema.

Relevant contract: §§1–3/6/12–13 open language, unchanged semantic entry/no phrase
grammar; §§4–5/7 Core current truth; §8 Mixed retained; §9 same explicit context
and binding/reset; §§10–11 one operation and visible latency debt; §§14–15 preserve
old paths and require independent blind physical acceptance; §§17–20 unchanged
contract and scoped recovery. No conflict identified within this authorized fix.

## Origin and original semantics

First reachable committed implementation of this adapter:
`2c58b3752ad79a639db6e406e2eeb1927b21086d`,2026-09-10 19:01:20 Moscow.
`docs/ia-warm-deadline-isolation-20260910.md` records a preceding uncommitted
implementation on parent d3245292 that shared one second with deletion ACKs.
An869ms terminal then failed while awaiting cleanup. The committed fix separated
500ms isolation from the one-second input/response/parse bound. Do not invent an
earlier committed adapter when Git first adds it at2c58b37.

The hard one second was a latency gate enforced as an operation/admission deadline,
not a provider protocol correctness requirement. It measured a tiny aircraft-only
typed interpretation after warm-up: current input → response.create → terminal →
strict proposal, with Core also bounding admission. No per-turn session.update ACK
existed. Initial session configuration was part of separate3s warm-up.
Historical provider gate: A523.181ms/B377.631ms, generation519.304/374.563ms;
separate cleanup263ms. Field aircraft602.224ms including Core is recorded in the
canonical contract. Do not equate either with audible response latency.

General ingress7b6981a and stabilization5c9ab24 inherited the short fact limit,
with a separate12s Dialogue ceiling. Foundation Step2 commit152a2f22 added
mandatory session.update → exact session.updated before current input. Its
`docs/history/2026-09-14-context-application-proof.md` explicitly says the extra
RTT consumes the unchanged1/12s budget. Binding measured258.57–311.19ms;
nine ordinary Dialogue terminals969–1094ms, median1000ms (the controlled parser
failure1141ms is separate). Dialogue's12s allowance made those results possible.

## Exact failed-operation timeline and unknowns

Source `C:/Users/Алексей/AppData/Local/Temp/orion-foundation-step5-referent-live-20260915/report.json`.
Interaction63ae1d6d-1545-4562-bd0a-366db0f979da;
operation81705ef9-01bf-4529-9bb7-d9e0204bcf6d.

| Event | Saved monotonic seconds | From operation start |
|---|---:|---:|
| operation start |435220.187|0ms|
| context ACK verified |435220.484|297ms|
| first text |435220.968|781ms|
| timeout / failure |435221.187|1000ms|

Exact session.update send, current input send and response.create timestamps were
NOT captured in that report. Code fixes their order: update after start/before ACK;
input and response.create after ACK/before first text. No fabricated timestamps.
Close/reset completion timestamps also absent; source closes the dirty transport
with a300ms bound and gate shutdown leaves zero owned tasks. No successful
isolation/reset or recovery handshake is claimed from missing events.

Total semantic path reaches timeout1000ms. Generation-path proxy measured AFTER
ACK: first text484ms; remaining terminal window703ms. True response.create →
terminal cannot be measured because send/terminal events are missing. ACK and
other local work reduced the original1000ms generation allowance by at least
297ms (29.7%). Historical258.57–311.19ms bind cost leaves688.81–741.43ms.
No completed semantic output exists; this is neither referent nor provider-quality
failure evidence.

## Decision C — DEADLINE_SEMANTICS_WRONG / MIXED_DOMAINS

The original no-bind generation budget was reused as a total containing mandatory
binding. A product latency target became a hard correctness timeout for a changed
path. It is justified to restore the original bounded generation allowance, not
to invent an unbounded timeout or claim a faster product.

New GENERAL policy (legacy aircraft-only path unchanged):

- Context binding ≤500ms, also capped by the request deadline. Reuses the existing
  bounded control-ACK policy, originally chosen around twice239ms RTT; observed
  current exact context ACK259–311ms fits it. Not an arbitrary multi-second buffer.
- Generation/input submission/strict terminal ≤1000ms AFTER the ACK, and total
  ordinary semantic path ≤1500ms; Core ordinary admission uses the same1500ms
  elapsed-from-request ceiling. Request deadline always remains authoritative.
- Dialogue/Mixed keep their existing12s total ceiling; the wire-kind switch must
  occur within the bounded initial generation window and strict parsing must
  confirm its kind. No extra time for an untyped/mismatched result.
- Successful isolation remains separate500ms. Failed-transport close300ms and
  existing single background recovery handshake3s remain; no same-turn replay.
- Total first-text/terminal/user-path metrics remain measured from original start.
  Generation timing after ACK and SLO-exceeded flag are additional measurements,
  not replacement clocks. Desired <1s audible start remains unproven latency debt.

Runtime edits in this continuation: policy constants in general_semantic_contracts;
WarmYandexAircraftInterpreter._interpret budgets/normalized timeout category and
separate generation metrics; InteractionRouter.admit_general short elapsed limit.
No schema weakening, value/provenance changes, TTS/SRS, registry or context change.
General timeout names distinguish SEMANTIC_CONTEXT_BIND_TIMEOUT from
SEMANTIC_OPERATION_TIMEOUT, not successful latency target attainment.

## Tests and gate observability

New `tests/test_general_deadline_policy.py`: fake-clock300ms ACK +850ms terminal
is accepted with total1150ms, generation850ms and SLO exceeded. Hard timeout for
no terminal, partial-only terminal, no ACK; cancellation; no replay; subsequent
turn after bounded recovery; Core acceptance1200/1490ms and rejection1510ms.
Legacy deadline/isolation and context binding/replay suites retained.

Developer gate optional wire-timeline wrapper records only event type and monotonic
send/receive/close timestamps, not headers/secrets/provider bodies. It forwards
unchanged objects and never retries. Existing bounded RAW/normalized/parsed text
capture remains. Exact instructions/context and OFFLINE accepted seed plans are
already included. No production transport instrumentation redesign.

First full regression exposed one old timeout-label assertion and CRLF-vs-normalized
fingerprint calculation. Updated only that assertion and reviewed normalized hash;
no production change to satisfy those checks. Final regression/provider/build
results are appended below after execution. No current field PASS.

## Final offline and live gate

Full final regression **3486 PASS / five baseline FAIL / one skipped**,90.14sec:
`C:/Users/Алексей/AppData/Local/Temp/orion-foundation-step5-deadline-final.xml`.
Same IA inventory, three setup wizard assumptions and Project Memory wording
failure as parent. Scoped Pyright0 errors/warnings, Ruff, compileall, diff checks
PASS. No new test failures; no xfail/skip added to hide a failure.

One bounded live session, four ordinary follow-ups, one connection, zero retries,
zero owned tasks after shutdown. Real Yandex, offline Core-accepted preceding
plans and fixture values; no STT, DCS, TTS, SRS or acoustic evidence.
Report (contains raw/normalized/parsed, instructions, context and wire timing):
`C:/Users/Алексей/AppData/Local/Temp/orion-foundation-step5-referent-deadline-live-20260915/report.json`.

| Case | Latest requested/selected fact | Bind ms | After-ACK generation ms | Total semantic ms |
|---|---|---:|---:|---:|
| RU Fact A→Fact B→follow-up | ownship.altitude_msl |282|750|1032|
| RU Mixed A→Fact B→follow-up | ownship.vertical_speed |281|469|750|
| EN Fact A→Fact B→follow-up | ownship.altitude_msl |281|531|812|
| EN Mixed A→Fact B→follow-up | ownship.vertical_speed |296|516|812|

All four correct typed selections, strict admission, one fresh fixture read and
completed isolation. RU/EN REFERENT MECHANISM PASS for this bounded gate. The first
valid1032ms result would fail the old1000ms total ceiling; its generation750ms is
within the original budget. This is additional direct evidence for the split,
not a speed improvement. Median total812ms; maximum1032ms. First audio remains
unmeasured here; Step3 TTS latency debt and blind physical acceptance remain.

## Pre-field decision and continuation

**A. PRE-FIELD CANDIDATE READY** after combined Step5 scope review. Three earlier
failed/inconclusive reports are preserved, not overwritten. The representation
and deadline fixes now have bounded live proof; no claim of universal model
quality or Foundation FIELD PASS. One semantic entry/owner, no production phrase
rules or new recognizers, no provider replacement or fact-surface expansion.

Proceed under the user's explicit Step5 authorization: one candidate commit/push,
exact archive build, three packaged smoke checks, compiled-source/embedded SHA
verification, normal installation/readiness. Build/installation are NOT yet
claimed by this pre-commit document; receipts will be in
`C:/Users/Алексей/Documents/ORION-Builds/foundation-step5-20260915/`.
Stop before the user's blind physical test; no prepared utterances.

## Explicit user acceptance-policy update

For current Foundation, correctness → reliability → recovery → user blind
usability take precedence over optimization. Preserve the separated bounded
deadlines and measurements. The <1s response-start goal is not itself a Foundation
failure gate. Latency is independently classified as LATENCY TARGET MET,
LATENCY DEBT — USABLE, or LATENCY DEBT — MATERIAL PRODUCT PROBLEM. It blocks only
when functionally unacceptable (repeated timeout/continuity failure, stuck waits
or user-judged unusability), not from an invented millisecond threshold.
No context/authority/cleanup/TTS ownership tradeoff and no optimization in Step5.
If blind Foundation acceptance passes with debt, record a separate future
ORION LATENCY OPTIMIZATION / PERFORMANCE PASS in the backlog, not an automatic
provider run or architecture change now.
