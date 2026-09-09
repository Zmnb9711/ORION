# Free Conversation host integration — 2026-09-09

ORION ARCHITECTURE GUARD: OFF — user-approved recovery implementation.

## Exact implementation surface relative to preserved f346e13

| File / symbol | Required change |
|---|---|
| `orion/conversational_core.py`: `_INPUT`, `admit_social_text` | Whole-source first RU social slice; replace clause whitelist with text-shape finalization. Ledger, exact binding and expiry unchanged. |
| `orion/yandex_realtime_text_conversation.py`: `INSTRUCTIONS` | Natural text instruction, no prescribed clauses. Still tool-less, no telemetry, no operational authority. |
| Same file: `TextConversationProvider._observe_terminal` + one call | Observe exact terminal text and mechanically normalized JSON, best effort. Parser, auth, event/audio checks, request counts and cleanup remain literal. |
| `orion/conversational_presentation.py`: `ConversationVoice.run/emit` | Route name CONVERSATION, monotonic events, normalized turn-local failures/cancellation. Existing typed admission, stream/TTS/radio and cleanup reused. |
| `orion/full_voice_service.py`: `_voice.answer` | After FullVoiceCore and Hybrid both decline, explicit eligibility invokes the existing ConversationVoice owner. No gateway/WorldModel/Planner passed. Per-turn shutdown before release. |
| Same file: local observer + END observation | Correlate existing Test Session with physical END and Conversation events. No new timing/control decisions. |
| `orion/realtime_test_evidence.py`: `record_conversation_slice` | One bounded opt-in projection into existing ring/export. Other methods unchanged. |
| `orion/hybrid_aircraft_core.py`: `render_informational` | Sole line change: silent source label; `Вы находитесь в {display}.` Provenance and validation unchanged. |

Six production files changed; no new production module or dependency. The four
existing Conversation modules were already preserved in the baseline.

## Routing / lifecycle

`NativeSpeechKitTurns FINAL -> FullVoiceCore -> existing Hybrid -> explicit
eligible Conversation -> TextConversationProvider -> SocialDraft -> bound
FinalizedConversationalText -> existing RU jane TTS -> RadioRouter -> SRS`.

A known Core result always wins. Hybrid failure/ambiguity does not fall through.
Unknown facts, operational-like phrases, quoted/suffixed input and unsupported
mixed “Как дела? И какой у меня самолёт?” do not become Conversation. Existing
operational router code remains frozen; this slice does not add missing domain
voice integrations. Conversation has no tool bridge or Planner fallback.

The normal inherited owner retains START/STOP and six-second shutdown contract.
No new thread/state/readiness/EAM rules. One per-turn provider connection, no
persistent history, one operation, no retry/reconnect. Ordinary provider/schema/
TTS failures are turn-local; unclean resource ownership remains a hard error.
Existing streaming radio can admit a stream before first PCM; a TTS failure
before PCM leaves zero audio in that stream, not a fabricated response.

## Evidence / privacy / latency

Only explicit Test Session retains exact STT FINAL, eligibility source, raw
terminal **text slot** (not provider body), normalized JSON, candidate/finalized/
TTS text. Bounds: 500 source, 4096 terminal/envelope, 300 generated speech,
200 scalar strings, existing 5000-event ring. Session/turn/response/TX IDs,
route, separate Conversation/Planner/ToolGateway counters, physical END,
connect/first-token/terminal/TTS/first-radio-frame/completion marks and failures
are projected. Unknown fields, headers, provider body, tools and audio ignored.
No raw audio retention added. Outside Test Session the projection is a no-op.
Existing export and privacy behavior unchanged. Evidence exceptions cannot
change accepted turn behavior.

Existing `ORION_BUILD_SHA` environment mechanism can be set in a build-only
runtime hook with the exact commit; this requires no product API/UI change.
Build manifest identifies hook/source/product hashes. No latency optimization,
new latency recorder or claimed physical latency result in this task.

## Offline proof and build gate

- Policy gate: 1436 PASS / 4 pre-existing intentional SKIP; Ruff PASS; policy
  Pyright 0 errors. Exact fourth/fifth candidates finalized without rewriting.
- Normal host tests: two independent conversations followed by Core aircraft;
  failure modes provider/invalid candidate/TTS/observer, inactive privacy and
  STOP-provider. Real Core, real existing presentations and RadioRouter;
  fake external I/O only. No provider/PTT/DCS/SRS calls.
- Host known/unsupported negatives assert Conversation constructor is never
  entered; full-source eligibility cannot steal operational/Hybrid queries.
- Differential tests restore only the handoff AST nodes and compare the whole
  host with f346e13. Old evidence class is exact after removing the new method.
  Provider protocol AST hashes unchanged after removing only observer code.
  Whole frozen files compare with golden checkpoints; Hybrid has exactly the
  approved one-line source-label exception. Historical test budgets remain
  separate from current permissions.
- Existing test-only assumptions updated: phrase censorship, default source
  prefix, new observation event order and narrowly expanded approved scope.
  No frozen algorithm test disabled.
- Pyright on changed integration modules: 0 errors. Full changed-file scope
  additionally exposes the **pre-existing** Hybrid line 95 str-to-Literal error,
  reproduced on saved `hybrid-local-routing-20260908/source` unchanged source.
  It is not fixed here; no new type error introduced.
- Final relevant-suite JUnit, build command/logs, source archive and bytecode
  verification, hashes and three isolated package smokes must accompany the
  final artifact. A failed build/smoke is not field readiness.
- Final relevant-suite gate: **1461 PASS / 4 intentional SKIP**, 46.75 s;
  `level0-event-contract-20260909/free-host-full-pass.xml`. The three first-run
  failures were obsolete exact-scope expectations for the explicitly added
  observer and source-prefix change, corrected with exact differential checks.

## Readiness boundary

This is a bounded first RU social conversation, NOT universal dialogue, factual
QA, mission advice, persistent memory or Conversation+Core composition. No new
provider call was needed; the fifth saved result establishes the same text
transport, not naturalness of every future response. User acceptance of
probabilistic non-authoritative output remains explicit.

Installer must come from clean committed source. Do not install silently or
merge to production. First physical gate after installation is exactly:
“Что-то сегодня полёт тяжело идёт.” One PTT, one reply, acoustic confirmation.
Test Session captures evidence automatically. Stop on failure; no repeated
physical attempts without a specific evidence-backed reason.
