# Level-0 conversation — prerequisite stop, no product integration

ORION ARCHITECTURE GUARD: OFF — historical recovery exemption in the task.

## A. BASELINE / HYBRID FIELD FREEZE

Runtime source: `f0c9e364ed653e9497d7e2ef8ef8f35dc97157d4`; docs parent:
`8f8009c5e7e00eb3c59eb0247156b005dd932729`. Docs-only freeze:
`dca668d530dc6cbc4de05064400b22c2216ada3f`.
See `docs/hybrid-aircraft-field-freeze-20260908.md`: verified evidence hash,
exact FINAL/finalized text, local/provider-zero Hybrid, 143 TX frames,
ownship 385 frames and explicit acoustic confirmation. The original field ZIP
has `orion_build_sha=unknown`; later artifact matching does not repair that field.

Worktree: `C:\Users\Алексей\Documents\GitHub\ORION-level0-conversation`.
Branch: `codex/level0-conversational-voice`. Installed product not changed.

## B. HISTORICAL TEXT TRANSPORT EXTRACTION

| Historical symbol / source (`8182e892`) | Classification | Disposition |
|---|---|---|
| `build_yandex_url`, `yandex_authorization_headers` | COPY/reuse current symbols | Existing endpoint/model/auth, no new settings |
| `yandex_text_session_update`, `yandex_text_request_events` | ADAPT | Text-only session/item/response events; exact source text, no old `.strip()` |
| `AiohttpRealtimeTextTransport` | ADAPT | One connection per operation, bounded frames/close, no warm owner |
| Text assembler response/item correlation | ADAPT | Bounded chunks, terminal consistency, fail closed on unrecognized protocol |
| Persistent presenter / same-session formulation + semantic judge | DO NOT USE | Hidden history and additional probabilistic stage excluded |
| Realtime audio, VAD, FlightContext, broad D75 fact scope, Launcher selector | DO NOT USE | Outside Level-0 |

Historical performance was a warm D75 path, not evidence of current cold Level-0 latency.

## C. CONVERSATIONAL CONTRACT

Isolated, NOT host-connected draft: `ConversationalRequest` (UUID, exact source,
SHA-256, RU, deadline), `SocialDraft` (social_support + bounded text),
`ConversationalCandidate` (request, draft, terminal/provider identity),
`FinalizedConversationalText` (Core ledger-authorized exact text).
Pydantic extra fields forbidden. Candidate is not TTS permission.

## D. AUTHORITY BOUNDARY

No facts/actions/tools fields; no gateway, world, Planner or DCS input to the new
core/provider. RadioContext is attached locally only after admission. Provider
receives fixed social instructions plus exact eligible input, never radio state.

## E. TURN-SCOPED LIFECYCLE

Each operation creates and closes its own aiohttp session/WebSocket. No reused
provider history, worker thread or warm-up owner. One active request; up to 64
lifetime identities without eviction/replay reset. Bounded events/output/deadline.

## F. STOP / CANCELLATION PROOF

Offline connect/request/receive/first-token cancellation, response/connect stall,
close stall, top-level task cancellation and owned-task termination pass.
Noncooperative fake cleanup returns bounded cleanup ERROR while explicitly
retaining the task reference; harness rescue is not reported as production success.
Existing FullVoiceService exception/STOP handling preserves ERROR in the isolated test.
The new presentation waits at most 0.4 s for the existing borrowed radio abort's
terminal acknowledgement; no radio algorithm or global STOP timeout was changed.
This is prerequisite harness evidence, not installed-host field proof.

## G. PROVIDER CONFIGURATION / FAILURE ISOLATION

Existing Windows Credential Manager Yandex API key and CloudVoiceConfig Folder ID
were present. Endpoint: `wss://ai.api.cloud.yandex.net/v1/realtime`; model URI uses
existing `speech-realtime-260528`; Api-Key auth. No credential/header/body retained.
New owner is lazy and unwired. Ordinary provider failure is turn-local silence;
cleanup failure propagates truthful ERROR. No global readiness/settings changes.

## H. ADMISSION STRATEGY

A lexical blacklist/prompt alone cannot exclude oblique facts/advice: rejected.
B unrestricted prose + deterministic semantic checking lacks a complete proof:
not claimed. C a second LLM judge adds probabilistic latency and is not imported.
D selected for this prerequisite: structured social act plus a **positive closed
language** of empathy/acknowledgement/invitation clauses, no free prose slots.
Core validates the whole text and preserves it exactly, not partial substrings.
Advice including "Главное — не торопитесь" is rejected.

The provider would compose the complete reply; Core does not select one canned
final response. Offline varied fake candidates prove mechanism only. **Genuine
live generation, naturalness and variation remain UNPROVEN** because handshake
failed before response.create. The positive grammar deliberately does not admit
general conversation or prove a general-purpose semantic classifier.

## I. ROUTING CONTRACT

Existing ownship → existing Hybrid/local social → explicit Level-0 eligibility
→ unsupported, demonstrated in an isolated composition harness. No actual host
route was added. Complete subjective RU forms only; hidden advice/residue,
weather, diagnosis, actions and "Как дела? И какой у меня самолёт?" stay excluded.

## J. EXACT PRODUCTION DIFF

No tracked existing runtime file changed. Uncommitted, unwired prerequisites:

| New file | Lines | Purpose |
|---|---:|---|
| `orion/conversational_contracts.py` | 44 | New strict no-authority types |
| `orion/conversational_core.py` | 127 | Eligibility / positive admission / binding ledger |
| `orion/yandex_realtime_text_conversation.py` | 253 | Request-scoped text adapter |
| `orion/conversational_presentation.py` | 136 | Separate typed admission / isolated owner borrowing streaming mechanics |

Also two new offline test files (288 and 183 lines). `full_voice_service.py`,
Test Evidence, Launcher and all frozen subsystems are unchanged.

## K. OFFLINE TRANSPORT RESULTS

Text events/chunks/correlation, malformed/wrong/duplicate events, early close,
timeouts, cancellation, repeated operation, no hidden session history, rejected
audio/VAD/tool output: PASS. Fake actual aiohttp wrapper verifies secure endpoint,
auth shape, response-size bound and repeated close without network.
Prerequisite file final run: **179 PASS** (includes three supplementary tests).

## L. OFFLINE ADMISSION ADVERSARIAL RESULTS

Positive safe compositions pass unchanged; injected explicit and subtle damage,
fuel, weather, tactical, clearance, action, news, reassurance and advice fail,
including appended unsafe text after safe clauses. Wrong ingress, forged source,
UUID/hash/language/deadline, extra authority/tool field, modified final text fail.
These results concern the closed grammar, not arbitrary natural-language safety.

## M. ROUTING / REGRESSION RESULTS

Actual frozen ownship and Hybrid cores were composed with the prospective
eligibility in a provider-free harness. Known routes remain first; new requests
do not invoke Gateway. Normal installed host integration was deliberately NOT done.

## N. PLANNER / TOOLGATEWAY ISOLATION

New provider/core have no Planner/Gateway APIs. Harness counters: 0 for Level-0.
Existing local social/Hybrid remain provider-free. Live probe: 0 Planner and
Gateway calls, 0 DCS data. Existing Planner and its cleanup were not edited.

## O. LIVE PROVIDER TEXT PROBE

At `2026-09-08T19:01:02.236089+00:00` (22:01:02 Moscow), one connection:
turn `4ef75b7d-6774-459d-b535-fd0360e567a1`.
Planned text: "Что-то сегодня полёт тяжело идёт." — **NOT SENT**.
Sequence: connect → session.update requesting output_modalities=[text] →
session.created → session.updated → `nontext_session` → close.

The strict adapter rejected `session.updated.session.output_modalities`, because
it was neither absent/None nor exactly `["text"]`. **The exact returned value was
not retained.** This proves a handshake-contract mismatch, NOT that Yandex lacks
text-only generation. Auth permitted establishing a WebSocket and session events;
generation/billing availability was not exercised.

0 user items, 0 response.create, no candidate, no TTS/audio. Session/WebSocket
closed=true; owned_tasks=0. Remaining benign and live cancellation probes were
NOT run. No retry, workaround, relaxation or second provider experiment.

Preserved machine record:
`C:\Users\Алексей\Documents\ORION-Builds\level0-conversation-20260908\provider-probe-result.json`.
Probe script is in the same directory; it was run exactly once.

## P. LATENCY BREAKDOWN

1594.0 ms total failed handshake + cleanup. Distinct connect duration, first-token,
completion, admission, TTS TTFA and SRS response-start are unavailable. No field
latency or <1-second claim. No generative completion happened.

## Q. TTS / SRS NON-REGRESSION

Existing jane request builder reused in isolated tests; finalized text stays byte
exact. Protected john, streaming implementation and SRS algorithms unchanged.
Fake streaming radio sees at most one TX; unsafe/failed provider candidates see
no TTS/TX. No actual audio/provider-TTS/SRS call.

## R. LIFECYCLE REGRESSION

Existing truthful STOP/Qwen cleanup/full-voice lifecycle regressions pass in the
broader offline set. No new START gate, STOP state/timer or frozen owner change.
Live successful close confirmed only for the rejected handshake, not generation.

## S. BROADER OFFLINE REGRESSION

Before live probe: **957 PASS, 4 SKIP**, 41.34 s. Prior 751-test regression plus
206 new tests. Four skips are pre-existing stop-local/pure-route inapplicable cases.
Three supplementary transport/lifecycle tests subsequently passed in the
179-test prerequisite-file run; do not add that repeated file as 179 new cases.
Evidence: `C:\Users\Алексей\Documents\ORION-Builds\level0-conversation-20260908\prerequisite-regression.xml`.

## T. STATIC / QUALITY

New runtime files: pyright with actual venv — 0 errors/warnings. Ruff correctness
check passed before the final supplementary tests. No broad cleanup/refactoring.
Frozen subsystem source comparison against f0c9e364 passes.

## U. CHANGE AUDIT

Only docs freeze committed plus isolated new prerequisite modules/tests retained
uncommitted. No existing runtime or settings edits; no integration after failed
probe. No DCS/SRS/PTT, install, push or audio collection. Existing user work preserved.

## V. BUILD / PACKAGE

NOT BUILT: live-provider prerequisite failed. No installer/source-artifact hash
or packaged smoke claim for Level-0. Installed successful Hybrid build unchanged.

## W. FIELD EVIDENCE READINESS

NOT READY. No conversational Test Evidence method or host wiring was added.
Standalone observer/fake measurements are not equivalent to installed Test Session
coverage. No physical test requested or authorized by this stop report.

## X. COMMIT(S)

`dca668d530dc6cbc4de05064400b22c2216ada3f` — docs-only Hybrid freeze.
No Level-0 runtime commit. This stop record and prerequisite files remain in the
separate worktree for review; they are not a new production baseline.

## Y. CURRENT STATUS

PREREQUISITES PARTIALLY VALIDATED; LIVE HANDSHAKE GATE FAILED.
NOT INTEGRATED / NOT BUILT / NOT FIELD READY. Stop before any further provider
experiment or adaptation. Exact unresolved issue: why current session.updated
does not satisfy the requested text-only acknowledgement contract.

## Z. FINAL VERDICT

LEVEL-0 CONVERSATIONAL SLICE FAILED — DO NOT FIELD TEST
