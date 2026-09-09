# Yandex Support DT403405 — reply and recovery update, 2026-09-09

ORION ARCHITECTURE GUARD: OFF

## Provenance

Official Yandex Support reply as supplied by the user on 2026-09-09 in
conversation `6aa004f2-ba20-83eb-b399-889bfe57ea89`, user message
`15b1b281-0534-41c8-9307-eaa245db7fe2`. The full message was recovered with
read_thread, not reconstructed from the truncated preview or the assistant's
interpretation. This task did not independently reopen/poll the support portal.
The verbatim supplied reply is preserved below; the date is the user-supplied
reply date, not a newly verified support-system timestamp.

Ticket: [DT403405](https://center.yandex.cloud/support/tickets/DT403405).
[Original submitted ticket](2026-09-08/reports/support-ticket-DT403405.md).
[Prior protocol audit](2026-09-08/reports/yandex-audio-envelope-contract-audit.md).
[Original probe result](2026-09-08/evidence/yandex-realtime-text-protocol-probe-20260908/provider-protocol-result.json).

Model `speech-realtime-260528`; endpoint
`wss://ai.api.cloud.yandex.net/v1/realtime`.
Original session `4a11ff2e5d7a`; response
`resp_3d259f4f9f4d4806b03c0792a9b64fbb`.

## Confirmed contract and remaining clarification

- Support reproduced the reported text-only behavior: after requesting
  `output_modalities=["text"]` via `session.update`, `session.updated`
  still showed `["text","audio"]`, but only text was generated.
- The requested modality limits generation. The session remains multimodal;
  support's answer 7 describes both modalities as potentially available in
  `session.updated`. This does not imply generated audio.
- Audio-related structural/terminal events with `audio: null` do not mean
  audio generation. Actual audio chunks arrive only through
  `response.output_audio.delta`; other content-part/item audio fields are
  not independent audio sources. Support explicitly confirms that absence of
  `response.output_audio.delta` is a reliable indicator of no audio payload.
- Authoritative final text: `response.output_text.done`. Compare terminal
  representations as appropriate, but do not use `response.done.output` as
  the sole text source: it can retain an `output_audio` wrapper and
  `transcript` with `audio: null`. Support describes inheritance of the
  transcript from the text response as a supposition, not a proven mechanism.
- **Question 2 remains escalated to the next support line: non-blocking pending
  clarification.** The exact reason acknowledgements retain
  `["text","audio"]` (including the original `response.created` question)
  is still awaiting an answer. Answer 7 gives the operational explanation;
  it must not be represented as a final engineering resolution of question 2.
- Support could not inspect the original session/response IDs because it has
  no access to user information. Its reproduction and contract clarification
  are distinct from a server-side forensic verification of our original run.

## Comparison with preserved evidence and decision

The original probe requested text at both session and response levels, sent
only `input_text`, produced text delta/done, and recorded zero audio-delta
events despite multimodal acknowledgements and audio terminal metadata.
Support's contract explains that observation and closes the architectural
uncertainty about text-only generation. The archived harness
`FAIL_UNEXPECTED_OUTPUT` and incomplete projection of content audio fields
remain historical facts; no missing observations or fresh test results are
invented. The no-payload interpretation now rests on support's explicit
contract plus the recorded absence of audio deltas.

**ORION_EOD_20260908_AWAIT_DT403405 is CLOSED AS A BLOCKER.**
The ticket itself is not declared closed. Question 2 remains
**non-blocking pending clarification**.

Recovery / next-step marker:
**ORION_20260909_LEVEL0_CONVERSATIONAL_HANDSHAKE_EVENT_CONTRACT_CORRECTION**.

Next step: **Level-0 Conversational Handshake/Event Contract Correction** as a
separate bounded task. Distinguish multimodal session/content envelopes from
actual generated audio; use the authoritative text terminal while preserving
correlation, admission and cleanup requirements. This record does not implement
or validate that correction and does not authorize provider gates, production
integration or a build. Level-0 remains PARTIALLY VALIDATED / NOT INTEGRATED /
NOT BUILT / NOT FIELD READY.

**Approved policy unchanged: authoritative source labels silent by default.**
Source, authority, provenance, receipt, freshness and exact value binding remain
internal and mandatory; speak the source only when explicitly requested.
The historical spoken `По данным DCS` remains evidence of the old runtime,
not a policy reversal.

## Recovery anchors and scope

- Docs branch: `codex/eod-20260908-checkpoint`.
- Verified parent / pre-update HEAD:
  `8dc2f215e8680f81d76c5bb192d22ed18179ae5c`, equal to the fetched and
  directly checked GitHub branch ref before editing. No newer correct
  checkpoint was found among current local/remote refs.
- This update's commit SHA is resolved from Git history:
  `git log -1 --format=%H -- docs/history/2026-09-09-yandex-support-DT403405.md`.
- Preserved Level-0 branch: `codex/level0-conversational-voice`,
  `9ccab967dfe018f29302fb87e8105a4bb11a89de`.
- Frozen Hybrid runtime: `f0c9e364ed653e9497d7e2ef8ef8f35dc97157d4`;
  documentation freeze: `dca668d530dc6cbc4de05064400b22c2216ada3f`.
- GitHub main before this update:
  `a7757a3e430f5dfb50cbd81ca7427b12c7bc58ed`;
  broader development ref: `42520a57b01cd314978bcb51bdf4bbc75b38c156`.
- Current Git worktree inventory contains 13 registered trees, not the previous
  receipt's 14: 9 clean, 4 with existing untracked files. The dirty trees are
  ORION, ORION-qwen-cleanup-333ca5e, ORION-recovery-2026-08-27 and
  ORION-recovery-a955d7c. They are preserved without cleaning or moving files.

Docs-only update to Project Memory, the EOD recovery entry and this reply record.
Original 2026-09-08 reports/evidence/manifests remain unchanged.
No production or Level-0 runtime, Launcher/SRS/STT/TTS/ToolGateway/Planner edits.
No provider calls, DCS/SRS/PTT, build/install, workflow dispatch, release tags,
or merge into production. Verification is limited to documentation diff,
scope/whitespace/link checks and Git branch/remote/worktree checks.

For recovery, read Project Memory, the dated EOD checkpoint and this update;
verify current refs and worktrees again before starting the next task.

## Verbatim support reply supplied by the user

Возвращаемся к вам.

Воспроизвели описанное поведение: после указания в `session.update` `output_modalities=["text"]` вернулось событие `session.updated` с `"output_modalities": ["text","audio"]`. При этом итоговый ответ не содержал delta с аудиочастями. Иными словами, сессия обновилась, и был получен только текстовый ответ.

На вопросы ответим в том же порядке:

1. Указание модальности работает как ожидается: текст приходит, аудио не генерируется.
2. На этот вопрос пока не можем дать точный ответ. Для этого нам понадобится помощь коллег из следующей линии поддержки. Уточним детали и вернёмся к вам позже. Подождите, пожалуйста.
3. Нет, не означают. Эти события приходят как структурные с пустым содержимым аудио `audio: null`.
4. Чанки с аудио приходят только в событие `response.output_audio.delta`. Поле `audio` внутри `content part` или `item` в других событиях самостоятельным источником аудио не является: если `output_audio.delta` не приходил, байты не передавались.
5. Да, это надёжный индикатор.
6. Отправляйте `output_modalities=["text"]` через `session.update` — этого достаточно, настройка применяется к генерации. Это применимо ко всем мультимодальным моделям в Realtime API.
7. Сессия остаётся мультимодальной, а ограничение применяется на уровне генерации и не меняет тип сессии. Поэтому в `session.updated` вы всегда будете видеть оба режима как потенциально доступные, независимо от того, что реально ограничено для генерации.

   Если вам нужен только текстовый режим, советуем рассмотреть [текстовых агентов](https://aistudio.yandex.ru/ru/docs/ai-studio/concepts/agents/text-agents) и [Responses API](https://aistudio.yandex.ru/ru/docs/ai-studio/api/Responses/).
8. Здесь наиболее приоритетным будет `response.output_text.done`. Именно он даёт финальный текст напрямую. `response.done.output` может содержать унаследованную audio-обёртку контента (см. пункт 9), поэтому использовать его как единственный источник для текста не стоит. Советуем сверять оба, но текст брать из события `output_text.done`.
9. В этом событии формируется общий ответ из двух частей: из аудио-ответа и текстового. При этом внутри `content` сохраняется тип `output_audio` с полем `transcript`, даже когда аудиобайты не генерировались `audio: null`. Предполагаем, что `transcript` наследуется с текстовой части ответа агента.
10. Советуем опираться на спецификацию [Realtime API](https://aistudio.yandex.ru/ru/docs/ai-studio/concepts/agents/realtime) и нашу [документацию](https://aistudio.yandex.ru/ru/docs/ai-studio/concepts/agents/realtime).

По поводу просмотра информации по идентификаторам: у технической поддержки нет доступа к пользовательской информации, поэтому изучить детали по ним не получится.
