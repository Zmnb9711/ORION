# Foundation Step 2 — context application proof and bounded adapter correction

ORION ARCHITECTURE GUARD: OFF

WORKTREE ONLY. No commit, installer, DCS, STT/TTS/SRS/PTT, provider switch or Step 3.
This record supplements, never overwrites, the earlier failed Step 2 gate and
context-wire diagnostic. The original reports and complete patch remain intact.

## A. Contract read

CONTRACT READ: ORION_NATURAL_LANGUAGE_FIRST_CONTRACT_V1.
Contract SHA-256 unchanged:
`de59126cb79efc010996f4f8357ab80b641109b7ed3cd60ccbc7856d53c2a128`.
No new language rules, roles, authority, catalog entries or architecture.
One General operation; explicit bounded ORION context, not hidden history.

## B. Starting Git state

Worktree `C:/Users/Алексей/Documents/GitHub/ORION-level0-conversation`;
branch `codex/general-natural-language-ingress-tranche1`;
HEAD `4b5a46959c241eec6ef8391ee52de4da93f3dc0f`;
tree `96ff342b844590d0d89db6a1df5d8873bb15fd28`.
Existing uncommitted Step 2 runtime/tests/docs and untracked data preserved.
The existing General contracts/core/voice files and provider instructions remain
byte-identical to task entry. No staged files.

## C. Synthetic context probe design

Fresh connection, one model operation. Newly generated harmless 64-bit hex label
for a made-up object Neralis. A synthetic local Core-admitted exchange populates
the normal InteractionContext.accept/project path; this is a fixture, not a
previous cloud response or authoritative real-world fact. A current question
asks its label but does not contain it. No personal context or DCS data.
No previous user/assistant cloud items contain the seed. No provider fallback.

## D. Actual outgoing wire evidence

Temporary isolated runner:
`C:/Users/Алексей/AppData/Local/Temp/orion-context-application-proof/probe.py`.
Wraps actual aiohttp ClientWebSocketResponse.send_json, preserving the exact
argument before delegating unchanged. Captures bounded session/input/response/
delete objects, JSON serialization SHA-256/bytes, IDs and high-resolution order.
Selected receive fields retain session/response ID, status and instructions echo
when present, never auth headers, credentials, audio or hidden reasoning.
Existing owner observer captures bounded RAW/normalized/parsed terminals.
These are actual function-boundary captures, not TLS packet captures.

## E. Hidden-history isolation

First probe has exactly three outgoing messages before generation:
base session.update (no nonce), current user item (no nonce), response.create
(nonce only in its explicit context instructions). Fresh provider session.
Repeat: still no seed conversation items. Same context string is bound through
session.update and exact session.updated echo BEFORE current item/generation.
Two generated items deleted and base instructions restored/ACKed before READY.
Session configuration is only a request-owned copy; authoritative memory remains
the explicit ORION projection. Failures close the dirty session, not reuse it.

## F. First probe result

Provider-level result: CONTEXT_NOT_APPLIED in this probe.
Nonce `4f82de1154de172b`; response was strict typed
`{"kind":"CLARIFICATION","slot":"reference"}`, not the label.
Actual response.create contained the correct instructions; initial session echo
matched only the base prompt. response.created/done did not echo instructions.
Operation `3692aa16-aff4-41e1-85ff-6f3ada6742c4`, session `5e9a85c8c421`,
response `resp_c5ba5a9fc82b415aa9c816ad5e0f5038`.
Outgoing response JSON: 6189 bytes, SHA-256
`6cd04d5aad382b30e700ddab2452d952798b747779cffbd7b2ccb12d5cf122a6`.

IMPORTANT harness limitation: first.json's top-level classification remains
INCONCLUSIVE because a subsequent Core admission raised ValueError. The first
runner created the request BEFORE cold handshake (1313 ms); the existing Core
non-Dialogue 1-second admission bound consequently rejected the result after
its 687 ms operation. This does NOT erase the saved provider CLARIFICATION or
the actual outgoing context. The exception was after parsed proposal. Corrected
only the temporary runner's request creation order (after prepare) for the
authorized new-value repeat. No Core timing/authority change; first.json intact.

## G. Root cause and evidential limits

The adapter relied solely on an unacknowledged per-response instructions override
for active context, while the effective session defaults held context=null.
That path did not yield nonce use in the captured first probe or correct RU/EN
continuity in the prior gate. This is an observed integration/application failure,
not proof of universal Yandex API non-support or intrinsic model incapability.

Official current response.create documentation advertises instructions overrides:
https://aistudio.yandex.ru/en/docs/ai-studio/clientEvents/realtimeResponseCreate
Official session.update documentation promises session.updated with effective
configuration:
https://aistudio.yandex.ru/en/docs/ai-studio/clientEvents/realtimeSessionUpdate
Both inspected in this task. The first probe itself confirms session instructions
echo support. Task section 10 authorizes using this supported alternative without
changing Foundation architecture. Controlled repeat and unchanged multi-turn
inputs then demonstrate operational application through the corrected binding.
No claim about internal backend implementation is made.

## H. In-scope fix

Only new runtime change: `orion/yandex_warm_aircraft_interpreter.py` (+33/-3).
General `_interpret` sends the identical provider_instructions through
session.update and awaits same-session, exact-instructions ACK before sending
current input and response.create. The existing response override remains equal
to the acknowledged session configuration; no prompt rewriting.
`_context_ack` rejects mismatched content/session/type and replay/invalid event ID.
`_isolate` sends the two existing item deletes plus base-instructions reset,
and accepts all three exact acknowledgements before READY. Operations remain
serialized; no new owner/model call. Legacy aircraft-only path unchanged.
Mismatch, timeout or cancellation closes dirty state through existing cleanup/
bounded recovery. Existing 1/12-second operation and 500-ms isolation budgets
are unchanged; the additional RTT consumes existing budget, not a hidden extension.
Only hash/timing ACK metadata is emitted by runtime, not raw private context.

## I. Authorized repeat — new synthetic value

CONTEXT_APPLIED. New nonce `8b5f8903e4ba43cc`.
Exact response: “We assigned the label 8b5f8903e4ba43cc to the made-up object Neralis.”
One operation/one connection, no retry, zero remaining owned tasks.
Actual send sequence includes context update and matching session.updated before
current input. After response, both item deletion ACKs and base prompt echo
were observed. No nonce in initial prompt/current user item. This establishes
application for this controlled operation, not universal field quality.

## J. One bounded multi-turn gate

Used the SAME ten developer inputs in scripts/foundation_conversation_gate.py
as the prior failed gate; no sentence/prompt tuning. Ten operations, two
connections (initial + controlled recovery), no same-turn retry. All ten context
updates have byte-equivalent echoed instructions in actual captured events.
Nine ordinary responses admitted/isolated; controlled malformed #9 rejected,
dirty session closed, fresh handshake, #10 successful. No capture failure/tasks.

| Turn | Scope | Observed result | First text / terminal / isolation ms |
|---|---|---|---|
| 1 RU | Ordinary conversation | Relevant unusual-airport topic, 155 chars | 625 / 1094 / 297 |
| 2 RU | Rainbow knowledge | Relevant but simplified explanation, 146 chars | 719 / 1031 / 282 |
| 3 RU | Rainbow continuation | Explicitly resolves rainbow centre/antisolar point, 184 chars; no lost referent | 656 / 984 / 281 |
| 4 RU | Different explanation | New rainbow analogy, 178 chars; simplified/inexact optics, not a physics-quality PASS | 703 / 1063 / 281 |
| 5 RU | Topic change | Discusses old libraries, 150 chars | 703 / 984 / 282 |
| 6 EN | Pendulum knowledge | Air resistance/pivot friction and heat, 150 chars | 718 / 1000 / 281 |
| 7 EN | Energy follow-up | Resolves pendulum energy without needless clarification, 136 chars | 703 / 969 / 312 |
| 8 EN | Different analogy | Hand-rubbing/friction analogy, 137 chars; energy wording imprecise | 703 / 969 / 281 |
| 9 EN | Controlled parser fault | Valid RAW retained; injected malformed input rejected; recovery 1063 ms | 703 / 1141 / n/a |
| 10 EN | After recovery | Relevant open-ended story discussion, 198 chars | 781 / 1093 / 282 |

Cold handshake 1078 ms, separate. Context bind/echo 258.57–311.19 ms, already
included in first-text/terminal times. First JSON text is not audible speech.
No identical responses within this gate; RU/EN referential continuity and
variation recovered on these cases. Scientific analogy precision remains
limited, not repaired by transport. No blanket Conversation/knowledge FIELD PASS.

## K. Provider comparison decision

No present basis to blame the provider for the former loss of context or to
switch to Qwen: same Yandex model, prompt, context policy and evaluation inputs
now preserve the relevant referents. No comparison performed. Broader quality
evaluation would be separate; this task does not authorize Step 3 automatically.

## L. Files / symbols added by this task

- Runtime: WarmYandexAircraftInterpreter._interpret/_context_ack/_isolate only.
- tests/test_yandex_warm_aircraft_interpreter.py: fake repeated session updates
  now echo effective instructions with unique event IDs.
- tests/test_general_context_binding.py: ten new ordering/ACK/clear/replay tests.
- tests/test_foundation_conversation.py: scope adds the one reviewed adapter.
- tests/general_ingress_hashes.json: only adapter fingerprint updated further.
- This report plus status links in Memory/history/field/contradictions.
- External temporary probe.py: actual-send observability and offline checks;
  not imported by production. Original Step 2 files/data remain preserved.

## M. Tests

Temporary capture offline: exact send/serialization, unchanged receive object,
exception propagation, privacy allowlist and bounds PASS.
Step 1/Step 2/provider/recovery targeted set: 133 PASS. New ACK suite: 10 PASS.
Full final runtime suite: 3306 passed, five pre-existing failures, one skipped,
81.69 seconds. Same baseline failures: import inventory; three setup-wizard
autodiscovery expectations; stale Project Memory packaging phrase expectation.
No new failures. Pyright changed runtime 0 errors/warnings; Ruff/compileall/
diff-check PASS. No phrase recognition added; prior Step 2 prompt hash unchanged.

## N. Evidence / diff / preservation

Directory: `C:/Users/Алексей/AppData/Local/Temp/orion-context-application-proof/`.
- first.json: `6dc1729016ff02b102a454e7be568e3932db0b62a02a7aafbf562f078b626437`.
- repeat.json: `a83cd5e14c0ceafebbd109d5993f91e6e2021dd91043313f419b35dafa8e3637`.
- multi.json: `5e93384bce8d2195b6cc440cd4e1284f5a98744d5250cf9c28a4ccf4f2093a36`.
- regression.xml; complete-Step-2.diff (includes prior preserved work).
Exact inputs, raw terminals, parsed/admitted output and IDs are in the JSONs.
Full normalized terminal retained by existing parser; no secret/provider body
logging, real personal facts or raw audio. tests may append existing events.jsonl;
appends preserved. User profile remains SHA-256
`4975e243ee95fdf997ccc5ecc4537eaff87947265c1c9a7f876ecf3ccee15c1f`.

## O. Commit / stop

NOT COMMITTED. HEAD unchanged. No push, build, install, physical test or Step 3.
Previous failed reports remain historical evidence. The current result is
component/provider proof for explicit context binding, not installed product
acceptance or acoustic validation. User review required.

STEP 2 LOCAL CONTEXT DEFECT FIXED + CONTEXT APPLICATION PROVEN —
USER REVIEW REQUIRED BEFORE COMMIT
