# IA-1.1 Hybrid Presentation / SpeechKit feasibility probe

Status: **IA-1.1 IMPLEMENTED — FIELD VALIDATION PENDING**.

This tranche adds a bounded diagnostic A/B probe. It does not select a production
presentation architecture and does not route normal ORION responses through
SpeechKit.

## Provider decision and evidence levels

The SpeechKit arm uses the documented direct REST v1 endpoint
`POST https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize` with an
`application/x-www-form-urlencoded` body. It supplies finalized text, `ru-RU`,
voice, emotion/role, speed `1.0`, LPCM, and 48 kHz. The existing in-memory
service-account API key is sent as `Authorization: Api-Key`; no Folder ID is sent.
The result is normalized once from 48 kHz mono PCM16 to ORION's existing 44.1 kHz
provider boundary before the unchanged SRS 16 kHz TX path.

Official sources checked on 2026-08-26:

- [SpeechKit v1 synthesis request](https://aistudio.yandex.ru/docs/en/speechkit/tts/request.html)
- [SpeechKit authentication](https://aistudio.yandex.ru/docs/en/speechkit/concepts/auth.html)
- [SpeechKit access roles](https://aistudio.yandex.ru/docs/en/speechkit/security/index.html)
- [SpeechKit voices and roles](https://aistudio.yandex.ru/en/docs/speechkit/tts/voices)
- [SpeechKit TTS overview](https://aistudio.yandex.ru/docs/en/speechkit/tts/)
- [SpeechKit v3 streaming API](https://aistudio.yandex.ru/docs/en/speechkit/tts/api/tts-streaming.html)

DOCUMENTED: v1 REST supports direct synthesis, API-key authorization, LPCM at
48/16/8 kHz, per-request voice, role (`emotion`) and speed. `dasha/neutral`,
`alexander/neutral`, and `julia/neutral|strict` are listed combinations. The v1
request has a 5,000-character text limit and a 15 KB request limit.

NOT AVAILABLE IN THIS PROBE: pitch control. It is not a documented v1 request
parameter. The heavier v3 streaming/protobuf surface is intentionally not added
only to obtain another control.

NOT OBSERVABLE until the controlled field test: whether the configured service
account currently has `ai.speechkit-tts.user`, real latency, perceived voice/style
differences, radio intelligibility, and provider behavior for this account.

## Probe invariants

- The operator must first start Test Evidence and a Yandex + SRS live session.
- Ten synthetic, one-concept `TestSemanticCase` values are evaluated in strict
  order. Every case is rendered by Realtime and then by SpeechKit from the same
  finalized semantic phrase. Realtime output never becomes SpeechKit input.
- Realtime uses a disposable provider session, separate from the main conversation.
  The evidence bundle records both IDs and the before/after observable
  FlightContext version.
- Voice sequence is `dasha → alexander → dasha`; style sequence is
  `julia/neutral → julia/strict → julia/neutral`. Every observed stale
  `session.updated` configuration is retained, and execution continues only after
  the requested effective voice/role is observed.
- Provider completion precedes SRS queue acceptance. A matching `srs_tx_started`
  and `tx_completed` is required before the 250 ms guard and next case. The
  existing single-slot queue, Opus, resampler boundary, TX pacing, PTT behavior,
  400 ms receive boundary, and radio protocol are not changed.
- Automatic text checks cover sign, value, unit, identifier, frequency, TACAN,
  laser, and unavailable semantics. Acoustic quality remains an explicit human
  review and cannot be manufactured by automation.
- A final disposable-session, noncritical response is cancelled after first audio,
  followed by a recovery response. Critical A/B phrases are never intentionally
  interrupted.
- WAV evidence is disabled by default. When explicitly selected, only the bounded
  synthetic provider PCM entering SRS is stored (mono PCM16, 44.1 kHz, maximum
  20 seconds per artifact and 40 MiB per test session). Microphone, received radio,
  and unrelated SRS audio are never captured.

## Decision matrix (pending field evidence)

| Criterion | A: Realtime only | B: Hybrid Realtime + deterministic TTS | C: TTS for all finalized semantics |
|---|---|---|---|
| Semantic fidelity | Field evidence pending; generative rendering risk | Expected strongest for critical finalized text; field evidence pending | Deterministic for all finalized text but loses conversational rendering |
| Numeric/unit safety | Automatic IA-1/IA-1.1 gates required | Critical path can be deterministic | Deterministic when upstream text is correct |
| Voice/style control | Session-scoped; stale acknowledgements must be filtered | Per-session Realtime plus per-request TTS | Per-request TTS |
| Latency | One provider path | Two implementations; selected path still one synthesis | One synthesis, REST v1 currently buffered |
| SRS compatibility | Existing 44.1 kHz boundary | Both normalize to the same boundary | Same normalization required |
| PTT/interruption | Existing behavior | Existing behavior; probe validates noncritical recovery | Requires a future policy design |
| Session continuity | Main session | Disposable probe proves isolation; production design undecided | Less dependent on conversation session |
| Complexity | Lowest | Highest | Moderate |
| RadioEntity scalability | Not evaluated in IA-1.1 | Not evaluated in IA-1.1 | Not evaluated in IA-1.1 |

No option is selected before exported A/B evidence and human acoustic review.

## Controlled field test (no DCS)

1. Start the official SRS Server 2.4.0 and official SRS Client; connect EAM blue.
2. Set Radio 1 to **251.000 AM** and confirm ordinary Common PTT audio works.
3. In ORION Settings → Voice, start **Yandex + SRS**, then **START TEST SESSION**.
4. Leave ordinary PTT idle during the critical sequence. Optionally enable bounded
   synthetic WAV capture, then select **RUN HYBRID PRESENTATION PROBE**.
5. Listen to every Realtime/SpeechKit pair. Check numbers, sign, units, identifiers,
   `264.500 MHz AM`, `44X`, `1577`, and the unavailable phrase; also compare the
   requested voice and style sequences.
6. Wait for **REVIEW**. Record the acoustic disposition through the probe API/UI
   when available, then stop and export Test Evidence.
7. PASS requires 20 correlated completed SRS transmissions, no
   `response_queue_full`, no critical interruption, successful noncritical
   cancel/recovery, distinct main/probe session IDs, no observable FlightContext
   mutation, all automatic text gates PASS, and acceptable human acoustic review.
8. Stop on any semantic corruption, timeout, provider/SRS error, credential leak,
   unexpected radio input capture, or main-session/history change. Mark provider
   facts that are absent from evidence as **NOT OBSERVABLE**.

Do not run DCS for this test. The exported `ia11-summary.json`, optional correlated
WAVs, and human observations are the inputs to the later architecture decision.
