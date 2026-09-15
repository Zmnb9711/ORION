ORION ARCHITECTURE GUARD: OFF

# Индекс источников checkpoint 15–16 сентября 2026

## 1. Уровни доказательств и приватность

A: прямые подтверждения пользователя и загруженные evidence. B: переданные локальные отчёты Astra. C: исторические цитаты/node pointers из DCS Changelog Watch, извлечённые Astra. D: сегодняшний анализ и предлагаемое продолжение. C нельзя заменять D. Код не равен intent; TX completion не отдельное human acoustic confirmation.

Публичный индекс не содержит API keys/passwords/credential identifiers, голосовых записей и полного приватного account export. Исходные attachments собраны отдельно в пользовательском recovery archive. Их SHA-256 ниже пересчитаны по доступным bytes при EOD save; installers и старый Data Export в этот сеанс не загружались, их hashes происходят из forensic reports.

## 2. Прикреплённые материалы и точные хеши

| File | SHA-256 | Назначение |
|---|---|---|
| STAGE-6B2-EXECUTIVE-CONCLUSION.md | F5EC7355D6AFA801093558EA680A7D4382F562B733C8499B1B71B1B4DDC59C9F | Первое краткое заключение; подробные отчёты уточняют его |
| DCS-CHANGELOG-WATCH-THEMATIC-ARCHITECTURE-RECOVERY.md | 32745D0DB4DA0E9177764593AEBF8DC6F21DFF4F0BBF18074C32BB34B8C470A4 | 452 строки; E01–E40 в §22, K1–K6 в §21, source gaps |
| DCS-CHANGELOG-WATCH-DECISION-LEDGER.md | 0E8E8EDAF7C4C666C78C3499A9A2FC4F57864D37582D06DA0AD87DB86C028EE6 | 63 строки; последние доступные решения |
| ORION-AS-INTENDED-AT-STAGE6B2-CUTOFF.md | 7FB54D6708E807D1BDCCE1024437CE8B2F5FB57215D447F792E78CD08DE79C5C | 246 строк; intended architecture, не implemented |
| ORION-Test-Evidence-20260915-194026.zip | D05E613FF797AEA2D5EF1D906BB3D5360E3274B29402CED6734A2BF016A2E37E | Новый Test A: 20 TX/WAV, terminal RuntimeError |
| ORION-Test-Evidence-20260915-200113.zip | 88F2044CF1DC67BAE24259B4D95DFAF89CBF7674D732DC84A1400105757BC3A4 | Новый Test B: 3501 events, 40 TX, без WAV |
| YANDEX-260528-NATIVE-TOOLS-VERIFICATION.md | A93C0BE6BC9ECAB23C934CC8F2004DA61D7BD34F76FDE5630FBD512797BB08C0 | Exact-code/API анализ и первое задание |
| YANDEX-260528-NATIVE-TOOLS-PROBE-EVIDENCE.zip | CB171921D7287912034DD80AFCB6A3AA54B8E253BBAC0B233E06CC14F631902D | Первый реальный tools probe: 20 файлов, 19 manifest entries |
| YANDEX-260528-INDEPENDENT-REVIEW-AND-NEXT-PROBE.md | 8C3B7F14251939D2826B7318391637F31A6744775C21DEB5800F4D893282DC83 | Offline review; следующий раздел 9 НЕ ВЫПОЛНЕН |

`yandex_native_tools_review/verification.json` — generated offline integrity/counter report, не новый provider test. Включён в отдельный source bundle. Не выполнять probe.py для чтения checkpoint.

## 3. Внутренние источники native-tools ZIP

Report, configuration.json, events.jsonl, probe.py, finalize_evidence.py, summary.json, summary-observed.json, audio-manifest.json, file-manifest.json и 11 generated OUTPUT WAV. Input/microphone WAV отсутствуют.

- Events SHA-256: `5E45C6825DDC5B4FA5F02709C71E9533FA26E4B52BAAB61A4A832F3CC0B0EDB9`.
- Config hash: `71a720c834b861cc296df4133dcbf2a1a34e74012d547ce2700df0b7bcaa44d6`.
- Prompt hash: `c1e3c3d83e6100110e3c843a074dce81afe61d32414443dcf0e665e964f0852c`.
- Schema hash: `ba8ff2984ccc525f6d51d14a2a3c3bb5a2c3605949df74a8af5e6b06be4ba6ba`.

Key sequences: 81–119 MIXED; 231–264 ambiguous и последующая смена fixture; 264–302 direct fresh 223; 399–401 external receipt и тишина; 432 FREE complete; 434 close1006; 435 audio NOT_RUN; 436 finished16attempts.

## 4. Локальные отчёты, упомянутые, но не полностью загруженные

Относительно `%USERPROFILE%/Documents/ORION-Restoration/`:

- STAGE6B2-FORENSIC-20260915/STAGE-6B2-WHAT-WAS-ACTUALLY-TESTED.md;
- STAGE6B2-FORENSIC-20260915/STAGE-6B2-HISTORICAL-FIELD-TEST.md;
- STAGE6B2-FORENSIC-20260915/STAGE-6B2-HISTORICAL-YANDEX-AUTH.md — держать приватным;
- STAGE6B2-RESTORE-20260915/STAGE6B2-RESTORATION-RESULT.md;
- STAGE6B2-ARCHITECTURE-AUDIT-20260915/STAGE-6B2-A955D7C-ACTUAL-ARCHITECTURE.md;
- там же ORION-ORIGINAL-INTENT-THROUGH-STAGE-6B2.md и STAGE-6B2-RECOVERED-LIVE-FIELD-VALIDATION.md;
- DCS-CHANGELOG-WATCH-THEMATIC-RECOVERY-20260916/POST-6B2-MINIMAL-PROTECTED-HEADING-INTEGRATION-PREFLIGHT.md — получена только сводка.

Три тематических отчёта лежат в DCS-CHANGELOG-WATCH-THEMATIC-RECOVERY-20260916.
Native workspace отдельно: Documents/ORION-Probes/YANDEX-260528-NATIVE-TOOLS-20260916-01.

Backups: HISTORICAL-IA6-RETEST-20260915-16/CURRENT-BACKUP; STAGE6B2-RESTORE-20260915/IA6-BACKUP; ORION-CURRENT-HOLD-20260915-16. Целостность подтверждалась локальной Astra, не перепроверялась удалённо при EOD save.

## 5. Первичный исторический источник по отчётам

Conversation DCS Changelog Watch, ID `6a84d8f8-77b8-83eb-ae57-869cd8c0ebfe`.
Data Export SHA-256 `EDD800F61210C6C682414E960C1A54D62DBBCC6DEED27B7FDF741DC5499937DB`; filename suffix `2026-08-28-13-02-09-2d3aca73e120442a869eecc0aec68752.zip`; содержит conversations.json. Для intent использовался только этот разговор.

HTML SHA-256 `AEEF61CDEB42A58A1A4803BFE055891A3873AA5BB80BA6D1D529D05DC65CB718`.
Конец доступного периода: 27 августа 22:34:09 UTC = 28 августа 01:34 МСК. Final 6B2 PASS отсутствует. Graph: 2072 nodes / 2071 messages, без visible branches. HTML ID match 2043/2072 не доказывает полную побайтовую эквивалентность.

## 6. Exact-code references

Читать только `a955d7c39f20c020e15de6bc2be272755928cc98`, не подставлять текущую ветку:

- orion/yandex_realtime_provider.py, blob `f94569e142a4ea9d88c887bed8a136d7d6bb57a1`;
- orion/yandex_realtime_session.py, blob `5b1cddc1a1ede5d3e1c01fea23426fd46a645979`;
- orion/yandex_srs_live_core.py, blob `f24356955fa44aded63615184ff014c5f55f451c`;
- docs/stage-6b2-srs-radio-transport-adapter.md, orion/srs_radio_adapter.py;
- orion/yandex_hybrid_probe.py: hybrid_probe_cases, speechkit_request, evaluate_semantics;
- orion/flight_context.py, models.py, world_model_contracts.py;
- docs/ia-6-interaction-router.md, interaction_router.py, communication_contracts.py;
- world_model.py, tool_gateway.py, planner.py, radio_router.py.

## 7. Точка возобновления

Latest review — YANDEX-260528-INDEPENDENT-REVIEW-AND-NEXT-PROBE.md, раздел 9. Follow-up NOT_RUN. Publication сохраняет контекст, не запускает работу. Resume instruction — `docs/ORION_CONTINUATION_CHECKPOINT_20260916.md`.
