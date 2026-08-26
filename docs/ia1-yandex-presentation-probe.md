# IA-1 Yandex Presentation Contract Probe

Implementation checkpoint: IA-0 commit `2d90e4f5c88c60ed27c840f967e5675f71d1721a`.
IA-1 field status: **CLOSED — FIELD-VALIDATED 2026-08-26**.

The final IA-1.1 evidence closes this probe. Realtime presentation is approved
for conversational/noncritical speech, but not as the sole renderer of critical
aviation semantics. Critical/radio speech uses deterministic SpeechKit TTS. Both
paths terminate at the same SRS transport; future Planner reasoning remains
upstream and independent of presentation.

## Official Yandex Realtime findings

The audit used the current Yandex AI Studio documentation after the May 2026
Realtime format migration:

- [Voice agents and sessions](https://aistudio.yandex.ru/docs/en/ai-studio/concepts/agents/realtime.html)
- [`conversation.item.create`](https://aistudio.yandex.ru/docs/en/ai-studio/clientEvents/realtimeConversationItemCreate.html)
- [`response.create`](https://aistudio.yandex.ru/docs/en/ai-studio/clientEvents/realtimeResponseCreate.html)
- [`response.cancel`](https://aistudio.yandex.ru/docs/en/ai-studio/clientEvents/realtimeResponseCancel.html)
- [`session.update`](https://aistudio.yandex.ru/docs/ru/ai-studio/clientEvents/realtimeSessionUpdate.html)
- [`session.updated`](https://aistudio.yandex.ru/docs/en/ai-studio/serverEvents/realtimeServerSessionUpdated.html)
- [Realtime format migration](https://aistudio.yandex.ru/docs/en/ai-studio/concepts/agents/realtime-changes.html)
- [SpeechKit voices and roles](https://aistudio.yandex.ru/docs/en/speechkit/tts/voices.html)

| Finding | Classification | Consequence for IA-1 |
|---|---|---|
| Text messages can be injected with `conversation.item.create`; current message content uses `input_text`. | VERIFIED | The probe supplies an already-decided `SemanticResponse` as a bounded text item. |
| Message roles include `user`, `assistant`, and `system`; item types also cover function/tool results. | VERIFIED | IA-1 uses only a `user` message. Tool results remain future architecture input, not IA-1 implementation. |
| `response.create` explicitly starts generation from current context. | VERIFIED | Every probe case sends one explicit response request. |
| `response.create.response` is documented as an optional per-response override for instructions/modalities/tools. | VERIFIED | IA-1 uses bounded presentation-only instructions and audio modality without replacing the global session prompt. |
| A response can be requested without changing global session instructions. | VERIFIED | FlightContext and ordinary session instructions are not replaced for semantic presentation. |
| Voice and supported SpeechKit role can be changed by `session.update` while the WebSocket session remains active. | VERIFIED | Voice/style probes use acknowledged session patches and restore `dasha/neutral`. |
| `session.updated` returns the effective session configuration and session ID. | VERIFIED | The probe records requested/effective voice/role, update latency, and before/after session IDs. |
| Voice can be overridden per response. | NOT DOCUMENTED | IA-1 does not invent a per-response voice field. |
| Realtime exposes pitch or explicit emotion controls. | NOT DOCUMENTED | IA-1 does not send pitch/emotion parameters. |
| Realtime exposes a speech-rate field. | NOT DOCUMENTED | IA-1 does not send a rate parameter. |
| `dasha` supports `neutral`, `good`, `friendly`; `julia` supports `neutral`, `strict`. | VERIFIED | Voice probe uses `dasha -> alexander -> dasha`; style probe uses one `julia` voice with `neutral -> strict -> neutral`. |
| A configured voice/role proves what the user acoustically heard. | REQUIRES LIVE PROBE | Evidence marks acoustic identity as user review, never inferred from configuration alone. |
| Updating voice/role preserves provider session identity and conversation state in this deployed model. | REQUIRES LIVE PROBE | The driver rejects a changed session ID, while the field ZIP supplies the final evidence. |
| Exact character-for-character spoken VERBATIM rendering is guaranteed. | NOT DOCUMENTED | IA-1 measures exact and punctuation/case/whitespace-normalized transcript fidelity; it does not claim provider determinism. |
| `response.cancel` stops an in-progress response and ends with `response.done`. | VERIFIED | Existing VAD/PTT interruption remains authoritative; the probe records interruption and completion status. |
| Exact behavior for multiple concurrent response requests is defined. | NOT DOCUMENTED | IA-1 serializes cases and rejects duplicate probe starts. |

This was the Phase A **GO**. Those live acceptance questions were resolved by
the final IA-1.1 controlled run described in
`docs/ia-1-1-hybrid-presentation-probe.md`.

## Test Evidence audit

| Event/value | Before IA-1 | IA-1 requirement | Action |
|---|---|---|---|
| Test session/provider/transport/timestamps/build | Recorded | Required | Reused unchanged. |
| Final user and assistant transcripts | Recorded in explicit test mode | Required | Reused; no streaming deltas or audio added. |
| Turn, response, provider item/event, context version | Partially recorded where exposed | Required | Reused and correlated with probe case/response IDs. |
| DCS connection/freshness/aircraft/context version | Recorded by bounded FlightContext diagnostics | Required | Reused; no exact coordinates added. |
| SRS ready/RX/TX events and first TX response ID | Recorded | Required | Reused; TX completion receives only the existing safe response ID marker. |
| Probe run/case/interaction/SemanticResponse IDs | Not recorded | Required | Added as bounded identifiers. |
| Structured expected synthetic semantics | Not recorded | Required | Added to `ia1-summary.json`; no World Model or FlightContext dump. |
| Presentation method and client event IDs | Not recorded | Required | Added without complete provider payloads or prompts. |
| Session update request/ack/effective voice/role/session IDs/latency | Not recorded | Required | Added as bounded scalars. |
| Request, response-created, first-audio, first-SRS-TX, completion timing | Partially recorded | Required | Added/correlated where observable; missing values remain `NOT OBSERVABLE`. |
| VERBATIM exact/normalized fidelity | Not recorded | Required | Added. Normalization ignores only case, punctuation, and whitespace. |
| NATURALIZE semantic equivalence | Not recorded | Required | Exact corruption-sensitive value tokens are checked; otherwise result is `REVIEW_REQUIRED`, never an invented PASS. |
| Acoustic voice/style identity | Not machine observable | Required | `USER_REVIEW_REQUIRED` in field interpretation; configured IDs alone are insufficient. |
| Raw audio, PCM, Opus, Base64, authorization, keys, system prompt | Excluded | Must remain excluded | Exclusion preserved. |

## Implemented seam and bounded probe

`SemanticResponse -> YandexPresentationAdapter -> existing active
YandexRealtimeSession -> existing PCM endpoint -> existing Direct/SRS output`.

The adapter never mutates IA-0 objects. Yandex JSON remains in
`orion/yandex_presentation.py`. NATURALIZE sends separated authoritative facts,
derived results, recommendation, and unavailable inputs with presentation-only
instructions. VERBATIM sends the finalized `verbatim_text` with a strict
render-only instruction and records both transcript comparators.

Synthetic cases use `fact_origin=synthetic_probe` and cover heading 256, TAS
241 knots, Colt 1-1, 251.000 MHz AM, TACAN 31Y, laser 1688, Texaco 1-1 at 47
NM versus divert 72 NM, unavailable TACAN, and the exact VERBATIM sentence:

> Colt 1-1, heading 256, true airspeed 241 knots, laser code 1688.

The probe serializes responses, requires an idle compatible Yandex session,
rejects duplicate starts, defers FlightContext refresh while active, and
restores baseline voice/style after voice-related runs. It does not add another
application, WebSocket, recorder, audio path, SRS implementation, World Model,
Planner, Tool Gateway, RadioContext, or RadioRouter.

## Provisional architecture status

- NATURALIZE: implemented; field fidelity pending.
- VERBATIM: implemented with honest transcript comparison; provider guarantee
  not documented and field fidelity pending.
- VOICE_DYNAMIC: documented session-level mechanism; live result pending.
- STYLE_DYNAMIC: documented voice-role mechanism; live result pending.
- Presentation Architecture: provisional **A/B decision pending field data**.
- Voice Model: provisional **A/B/C decision pending field data**.
- SRS/DCS protected baseline: implementation unchanged except a bounded
  response-ID correlation marker on the existing TX-complete diagnostic.
- Next approved stage after IA-1 acceptance: IA-2 — World Model Query Facade.
  IA-2 and Stage 6B are not started.
