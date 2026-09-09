# ORION end-of-day checkpoint — 2026-09-10 (Europe/Moscow)

**FIRST MODERN FREE-CONVERSATION VOICE VERTICAL FIELD PASS.**
**Golden ownship regression not established. General AI interpretation of DCS requests remains missing.**

Recovery marker: **ORION_EOD_20260910_FREE_CONVERSATION_FIELD_PASS_AI_INTERPRETATION_NEXT**.
This is a docs-only checkpoint, not a release, blanket baseline acceptance or implementation authorization.
Architecture Guard remains OFF in the explicitly scoped recovery line.

## Recovered repository and precedence

- Runtime/source worktree: `C:/Users/Алексей/Documents/GitHub/ORION-level0-conversation`.
- Runtime branch: `codex/level0-yandex-event-contract`; clean when inspected.
- Build/source HEAD: `d3245292c176d6dc51b2a9adcb71b2e238e0b234`.
- Build parent: `c444860dcfc8c735aa2a2dd4d4edc094b24236b0`.
- Build tree: `9018c0a253f39c5d849082f81b0c5f33f4948e22`.
- Isolated documentation worktree: `C:/Users/Алексей/Documents/GitHub/ORION-eod-20260910`.
- Documentation branch: `codex/eod-20260910-checkpoint`, parent exactly the build SHA above.
- Origin: `https://github.com/Zmnb9711/ORION.git`.

Repository + Project Memory + canonical history/evidence take precedence over conversational recollection. The source worktree was left on its original branch; no existing work was reset, stashed, cleaned, merged or included from another tree. Resolve this checkpoint's SHA from Git history for this file; final commit/parent/push verification is in the local recovery receipt.

This dated record and [product decision](../natural-language-core-product-direction-20260910.md) supersede older pending-field/next-step text without deleting the old reports. Prior canonical history is preserved at [September 8 checkpoint](https://github.com/Zmnb9711/ORION/blob/d0f58b5693e4a5f7467e32566be88674e24d4001/docs/history/2026-09-08-end-of-day-checkpoint.md) and [September 9 DT403405 reply](https://github.com/Zmnb9711/ORION/blob/d0f58b5693e4a5f7467e32566be88674e24d4001/docs/history/2026-09-09-yandex-support-DT403405.md). Their archived broader development memory/decision/policy snapshots remain there; no unrelated architecture branch was merged.

## Successful physical Conversation and Core evidence

Archive: `ORION-Test-Evidence-20260909-214800.zip`, at
`C:/Users/Алексей/AppData/Local/ORION/runtime/test-evidence/ORION-Test-Evidence-20260909-214800.zip`.
SHA-256 (reverified for this checkpoint): `5de53b6f224134592755f6770796e21966f8fca52b76fc0b00e53ccbbccceef2`.
Both successful and preceding failed field ZIPs are additionally preserved under `C:/Users/Алексей/Documents/ORION-Restoration/eod-20260910-checkpoint/evidence/`; originals remain in place. The UTC-named archive records September 10 in Moscow. It contains `events.jsonl`, `manifest.txt`, `session-summary.txt`: 287 events, zero dropped, eight finalized utterances; no WAV or report.json.
Test session `95d8d892d19a46df93bb301e8f9b9e69`; runtime `4a2cd09ff4524f91babaea2c33d5bfe1`; build attestation d3245292.

Conversation turn `956e58a6-ecc0-418a-b32e-7e17958578dd`:

- Actual STT FINAL: `что то сегодня полет идет тяжело`.
- Route `CONVERSATION`, route source `LOCAL`; one Yandex call, Planner=0, ToolGateway=0, DCS reads=0 in the recorded turn. This zero-read statement is scoped to the turn, not background telemetry ingestion.
- Provider response `resp_282a45e4901448bea244f8089cef4c20`: raw fenced `social_support` JSON, normalized by removing the fence; generated finalized text exactly equals TTS input: `Сочувствую, бывает такое… надеюсь, скоро ситуация наладится!`.
- One response, 131 frames, `tx_completed`, `srs_adapter_tx_completed`, terminal `completed`; failure stage/category null; provider `closed` recorded. Separate complete-cleanup flags are absent from the archive, so no stronger cleanup claim is made.
- User acoustic confirmation: **«звук есть, нормальный, с небольшой задержкой»**, recovered from conversation `6aa004f2-ba20-83eb-b399-889bfe57ea89`, user message `b79ce08e-57b0-4bfa-9e0f-154fbb9ce8ee`.
- Classification: FIRST MODERN FREE-CONVERSATION VOICE VERTICAL FIELD PASS. It is genuine generated language inside the bounded admitted social input class, not proof of universal input understanding. The generated sentence is evidence, not a required future exact response.

The same archive already proves Core aircraft identity. Turn `dfe5ca6c-6b74-4188-9cd8-eb594328c242`, FINAL `какой у меня самолет`, route `AIRCRAFT_IDENTITY`, one authoritative ownship read (`dcs_export`, `FA-18C_hornet`, generation 12786), response `Вы находитесь в F/A-18C Hornet.`, Conversation provider=0, 91 frames completed. A second aircraft wording also completed at turn `e402a61e-57ea-4cec-9a70-f9428981f11c`, generation 17322, 91 frames. Machine completion and the supplied Conversation acoustic confirmation remain distinct evidence; no separate aircraft acoustic quote is invented. No repeat aircraft field test is required to rediscover these saved machine results.

## Initial failure and SRS/EAM finding

Previous archive `ORION-Test-Evidence-20260909-203741.zip`, test session `370c46abd5414d30baf4a31ba2a02dff`, turn `8ac426ab-a25d-489d-b825-2731bf7d680f`, on c444860: FINAL `чтото полет сегодня тяжело идет` was rejected by overly narrow input eligibility. Conversation provider, Planner, ToolGateway, response TTS and TX were zero. [The bounded STT fix](../conversation-input-routing-20260910.md) is d3245292; this was an input-routing failure, not proof of broken radio transport.

The prior read-only SRS/EAM audit found ORION headless SRS registration actually succeeded during that failed turn: BLUE coalition=2, 251 MHz AM, UDP READY. The official-client coalition sequence 0 → 2 → 0 is a separate unresolved observation; cause is not established. An EAM UI indication alone must not be equated with authoritative server/headless registration or used to infer causation. There is no evidence that Conversation broke SRS/EAM. Preserve this observation; do not change SRS. These are retained audit findings, not a new live radio inspection tonight.

## Corrected routing-preservation conclusion

The [original A–YY audit](2026-09-10/routing-preservation-audit.md) and [saved offline results](2026-09-10/offline-results.json) are preserved as historical artifacts. Their stop/no-commit statements describe that earlier audit, not this later checkpoint.

| Request/capability | Evidence classification and current result |
|---|---|
| `Какой мой текущий курс и координаты?` | Historical modern golden FIELD VALIDATED at `57a563a067c980c3ff8057172aa6f5fefb33a5b0`; current production host reaches authoritative ownship and fake TTS/TX offline. |
| `Какой у меня курс и координаты` | Rejected in bounded mode since `ba43a2c52f952a43cec0adde2bce99394a6c71d1`, before golden; no accepted modern field contract established. |
| `Какие у меня координаты?` / heading-only | Accepted modern recovery subset contracts not confirmed; current rejection is a language-coverage gap, not proven loss of a field-validated capability. |
| Conversation / Aircraft / Hybrid | Preserved and reachable through the current host; evidence levels remain separately recorded. |
| Takeoff / ATC status | Historical physical proof in a separate branch with a controlled golden ATC session; not proof of current live-DCS session/clearance authority. |

The audit compared eight checkpoints and ran 12 host scenarios with zero assertion failures. Negative scenario PASS means rejection was reproduced, not capability support. This checkpoint does not rerun or upgrade those tests to new physical proof.

Core is called first in `FullVoiceService`; the bounded ownship matcher in `InteractionRouter.route` explains the observed silence. No Conversation shadowing of the proven golden route was established. Early reports that ORION spoke coordinates do not prove a correctly protected modern coordinates-only contract. Earlier conversational claims of “lost coordinates regression” and “build rejected because of that regression” are superseded by this evidence classification. No blanket acceptance of every historical feature or arbitrary language coverage follows. Do not substitute a full heading+coordinates report for a subset request and silently add unrequested facts.

## Product decision and next architectural stage

The user's goal is not a library of predefined voice templates. Natural/free AI understanding must interpret the request and, when needed, request only permitted DCS facts through Core/ToolGateway. Core retains fact truth and action authority; Planner handles reasoning; Conversation remains natural language. Models must not invent DCS values or receive uncontrolled raw telemetry as a substitute for a permissioned fact boundary.

The current modern build has genuine free Conversation and authoritative Core facts separately. It does **not** yet provide general natural conversation that understands arbitrary DCS-data requests and obtains the required DCS facts. The missing AI interpretation/tool-mediated layer is the key next architectural stage. Today's decision records the direction; it does not implement an interpreter, expand routes, expose tools/actions or authorize a new build. See the linked product decision for continuation criteria.

## Standing policy, process debt and latency

Authoritative source labels remain **silent by default**; provenance, authority, freshness and receipts stay internal. Speak source labels only when explicitly requested. The current aircraft response demonstrates this policy.

Capability reachability is different from source invariance. A Capability Preservation Matrix and a permanent gate through the actual production host were proposed; **NOT IMPLEMENTED** because the historical audit stopped on evidence classification. Its saved matrix is evidence input, not an installed executable gate or completed canonical development-policy change. Recommended next-process work: register exact proven contracts and evidence levels; require preservation of host reachability, owner/call counts, fact boundaries and unsupported negatives before future builds; make deliberate removals explicit. Keep language-coverage expectations separate from historical field proof.

Latency target remains ideally <1 s. Current Conversation provider first token ~349 ms after request; connection/setup ~1.534 s; SpeechKit TTS TTFA ~2.656 s; PTT END → first TX ~5.3 s (recorded monotonic difference 5.375 s). Provider-token latency is not end-to-end latency. TTS TTFA is a major measured contributor. Optimization is deferred until architecture/correctness; no latency changes tonight.

DT403405 remains **resolved as a blocker**, not declared a closed support ticket: question 2 was escalated and non-blocking pending clarification in the last canonical reply. Structural audio events with `audio:null` are not payload; `response.output_audio.delta` is the payload indicator; `response.output_text.done` is authoritative final text. Older stop/probe reports remain intact historical records. Do not reopen the resolved blocker from their stale waiting language.

## Verification and tomorrow's recovery

Docs-only work: scope/diff/whitespace checks, artifact hash verification, preserved-history references, branch and remote verification. No new production tests, runtime execution, build/install, provider, DCS, SRS, PTT, workflow dispatch, release tag or production merge. Prior 1565 PASS / 4 intentional skips belong to d324's development tranche, not this checkpoint.

Tomorrow: recover actual refs/worktree state; read Project Memory, this checkpoint and the product-direction decision; retain runtime build d3245292 and all field evidence. Start with design of the missing AI interpretation/Core-tool boundary and the recommended preservation gate. Do not begin by “restoring” unproven subset contracts, reopening DT403405 or repeating a field test. Implementation remains a separate task.
