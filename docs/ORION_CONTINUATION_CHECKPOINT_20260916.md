ORION ARCHITECTURE GUARD: OFF

# ORION — checkpoint завершения сеанса 15–16 сентября 2026

**PAUSED AT USER REQUEST. DOCUMENTATION SAVE ONLY.**

Пользователь: «давай на сегодня закончим. сохрани весь контекст текущего чата, запиши историю github».

Это запись рабочего контекста и источников, не дословный экспорт всех сообщений и не разрешение на дальнейшее исполнение. Новый API-probe, интеграционный patch, установка или изменение настроек после этой команды не запускаются автоматически.

## Сначала прочитать

1. [Полная история сеанса, решения, исправления прежних выводов и границы evidence](session-checkpoints/2026-09-16-stage6b2-native-tools/SESSION-HISTORY.md).
2. [Индекс исходных материалов и SHA-256](session-checkpoints/2026-09-16-stage6b2-native-tools/ARTIFACT-INDEX.md).
3. [Точная незавершённая задача: ограниченный изолированный probe](session-checkpoints/2026-09-16-stage6b2-native-tools/NEXT-ISOLATED-PROBE.md).

## Не перепутать три разных состояния

| Объект | Состояние на остановке |
|---|---|
| Рабочая историческая база пользователя | **Stage 6B.2 `a955d7c` — RECOVERED AND LIVE FIELD VALIDATED AS A HISTORICAL CHECKPOINT** |
| Установленный ORION | Оригинальный Stage 6B.2 installer восстановлен и протестирован. Позднейшие probes изолированы; интеграционных правок нет. Текущие запущенные процессы при сохранении checkpoint не проверялись. |
| Репозиторий для записи документации | Перед записью `dev/adr004-post-389` указывала на `42520a57b01cd314978bcb51bdf4bbc75b38c156`, tree `1519d4c2b7a03ff457a39dd2cf3199b4695ac667`. Это НЕ source установленного `a955d7c`. |

Существующая `docs/ORION_PROJECT_MEMORY.md` в этой dev-ветке начинается старой D74/C3/C4 записью от 4 сентября. Она не описывает точку остановки данного historical-recovery сеанса. Не запускать C4, не выбирать CURRENT_QWEN и не продолжать позднюю разработку автоматически. Эта запись фиксирует отдельный актуальный пользовательский recovery track; она не переписывает старую историю и не объявляет весь поздний код отменённым.

## Immutable historical baseline

- Commit: `a955d7c39f20c020e15de6bc2be272755928cc98`.
- Tree: `7c010efadc2a8c0b6b892b49354a4019e4fdb3b2`.
- Original installer: `ORION-Alpha-0.2-Setup.exe`.
- SHA-256: `CBC83918BE631A48E50D27A3F93D97091BB1DAF44AB546C2A17CA026F06F6F46`.
- Выдан 28 августа 2026, 01:31:52 МСК, согласно восстановительному отчёту.
- Установка без rebuild: 3189 product files совпали; два дополнительных файла — штатный uninstaller.
- Исходный modern `17ddfd12…` и промежуточная IA-6 сохранены для rollback. Не запускать деинсталляторы: восстановительный анализ выявил очистку runtime/credentials.

IA-6 `5c5c831` была первоначальным кандидатом, но пользователь затем прямо выбрал Stage 6B.2 как свою последнюю реально протестированную рабочую сборку. Не возвращаться к IA-6 как основной цели.

## Что уже доказано и чего не доказано

**Test A, 15 сентября:** пользователь лично подтвердил, что все 20 передач слышал нормально и разборчиво. 10 synthetic cases × Realtime/SpeechKit; RadioRouter → SRS. В evidence после всех 20 completion есть `ia11_probe_failed/RuntimeError`: нельзя объявлять полностью пройденным post-probe recovery. Это не live telemetry normalization test.

**Test B, 15 сентября:** обычный Yandex/SRS разговор, свободные вопросы, DCS-context queries; 3501 events, 69 user transcripts, 69 response_done, 40 TX starts/completions, 8850 frames, без WAV. Присутствуют 3 response_buffer_limit и 1 response_queue_full. После отправки F-5E-3 context модель ещё отвечала Hornet. Не считать 69 responses 69 услышанными передачами. Не считать этот путь проходящим через RadioRouter/IA-6.

**Нынешнее «минус 137»:** пользовательское акустическое наблюдение. Exact source/transcript/WAV для этой фразы не установлены. Не исправлять знак по догадке. Исторический «минус 241» связывался с добавленным моделью тире с HIGH CONFIDENCE, не CONFIRMED.

## Архитектура, которую восстановили

AS-BUILT `a955d7c` содержит три раздельных пути:

1. SRS RX → Yandex Realtime `speech-realtime-260528` + FlightContext → generated text/audio → полный PCM → legacy TX queue → SRS. Qwen и Interaction Router в обычном разговоре не участвуют.
2. Text/API IA-6 → Qwen planner → ToolGateway/WorldModel → exact semantic binding, bounded ownship slice.
3. Prepared synthetic text → Realtime/SpeechKit → RadioRouter/SrsRadioTransportAdapter → существующий SRS worker.

AS-INTENDED из `DCS Changelog Watch`: AI понимает естественную речь и рассуждает; Core владеет фактами, вычислениями, состоянием, разрешениями, operational decisions. Core детерминированно оформляет защищённый смысл и соединяет его с допустимой социальной частью. Готовый protected fragment не возвращается LLM для переписывания. Phraseology Engine — renderer, не NLP и не диспетчерская логика.

Исторический следующий roadmap: Stage 6B → Phraseology contracts/Core Engine+KB MVP → ICAO ATC controlled vertical → NATO AWACS controlled vertical. Полная итоговая схема FREE routing Yandex vs Qwen и точный следующий prompt после 6B.2 не восстановлены. Не заполнять пробелы поздними MODEL C/C1–C4/Pilot KB материалами.

## Последний фактически выполненный новый эксперимент

**Native tools probe Yandex 260528:** 3 isolated sessions, 12 TEXT-input cases, 16 generations, 5 tools, 11 output WAV, 436 events. ZIP SHA-256 `CB171921D7287912034DD80AFCB6A3AA54B8E253BBAC0B233E06CC14F631902D`.

Подтверждено по переданному evidence:

- native function calling и 5/5 call_id ↔ function_call_output;
- все 5 function-call responses без PCM;
- прямые heading queries читают fixture 137, затем 223; unavailable обработан;
- один EXTERNAL receipt без числа + без response.create: 0 responses/audio за 5.016 s;
- следующий FREE работает в той же сессии.

Ограничения и важные исправления:

- MIXED потерял приветствие в CONTROL, где число пересказывал Yandex. Пустая schema не имела social cue, Core Composer не испытывался.
- «Куда я сейчас лечу?» дало current heading 137 без fresh tool, но fixture в этот момент ЕЩЁ 137; смена на 223 была позже. Доказано нарушение fresh-read boundary, не ошибочное устаревшее число.
- no-tool response НЕ эквивалентен безопасному FREE.
- EXTERNAL не проверен на MIXED/ambiguous/audio input и не выдавал реальный внешний SpeechKit ответ.
- audio input NOT RUN, физическое воспроизведение/SRS/DCS NOT TESTED.
- input→response association только последовательная; exact PTT correlation/overlap не доказаны.
- session.updated kirill→dasha, response metadata kirill, rate=null; WAV header не доказывает серверную частоту.
- external session close code=1006 после successful FREE; причина не установлена.
- receipt-only и отсутствие response.create изменены одновременно: тишину нельзя причинно приписать лишь одному фактору.

Итог: **TEXT-INPUT NATIVE TOOL PROTOCOL VERIFIED IN SUPPLIED EVIDENCE; EXTERNAL-RESPONSE CANDIDATE PARTIALLY SUPPORTED; PROTECTED MIXED/AUDIO/LIVE INTEGRATION NOT PROVEN.**

## Ровно где продолжать

Подготовлен, но **не выполнен**, раздел 9 `YANDEX-260528-INDEPENDENT-REVIEW-AND-NEXT-PROBE.md`. Его исполнимая постановка сохранена в [NEXT-ISOLATED-PROBE.md](session-checkpoints/2026-09-16-stage6b2-native-tools/NEXT-ISOLATED-PROBE.md).

После возобновления: сначала узнать, появился ли у пользователя результат этого задания. Если нет, не выдавать ещё один общий preflight; при отдельном разрешении выполнить через локальную Astra ограниченный внешний ответ с social cue, реальной сменой fixture ДО ambiguous query и audio input. Установленный ORION оставить неизменным.

Прежний changeset 8 runtime + 8 tests НЕ разрешён. Не заменять Yandex; не вводить regex/новый классификатор для понимания речи по умолчанию; не запускать новый probe автоматически. Для будущей разрешённой интеграции — новая ветка от exact `a955d7c`, один ограниченный tranche и немедленный field test.

## Фраза восстановления для следующего чата

> Продолжаем ORION с `docs/ORION_CONTINUATION_CHECKPOINT_20260916.md` в `dev/adr004-post-389`. Прочитай также SESSION-HISTORY и NEXT-ISOLATED-PROBE, не подменяй recovery track старым C4. База `a955d7c` восстановлена и field validated; native-tools текстовый probe проверен частично. Следующий изолированный external/MIXED/audio probe был только подготовлен. Сначала проверь наличие нового результата, ничего не запускай и не меняй автоматически.

Пароли, API keys, credential identifiers и реальные голосовые записи в этот публичный checkpoint не включены. Исходные файлы перечислены по именам и хешам; полный комплект прикреплённых материалов хранится отдельно в пользовательском recovery archive.
