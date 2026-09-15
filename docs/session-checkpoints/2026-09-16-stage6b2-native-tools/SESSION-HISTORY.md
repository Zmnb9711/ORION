ORION ARCHITECTURE GUARD: OFF

# Полный рабочий контекст чата ORION — 15–16 сентября 2026

## 0. Назначение и остановка

Пользователь: «давай на сегодня закончим. сохрани весь контекст текущего чата, запиши историю github».

Документ сохраняет инженерную линию, существенные развилки, решения, отменённые предположения, результаты, ограничения и точное место продолжения. Это подробная рабочая запись, не посимвольная стенограмма и не официальный ChatGPT Data Export. Источники и SHA-256 — в ARTIFACT-INDEX.md.

Основание: сообщения пользователя, локальные отчёты Astra, три загруженных тематических MD, два field-evidence ZIP, native-tools ZIP и независимый offline review. Полный старый DCS Changelog Watch HTML/export в этом сеансе напрямую ChatGPT не прочитан: исторические выводы опираются на извлечения Astra с node pointers. Нельзя выдавать чтение отчётов за повторное чтение всего первичного разговора.

На остановке: **PAUSED**. Разрешена запись документации GitHub. Новый provider probe, интеграция, сборка, установка, DCS/SRS тест и фоновое продолжение этой командой не запускаются.

## 1. Цель пользователя и ошибки первоначального восстановления

Пользователь хотел вернуть оригинальную историческую версию ORION, которую лично считал реально работающей, проверить её и восстановить исходный замысел без влияния поздней разработки. Не требовалось автоматически продолжать C4, modern presenter или поздний ORION.

ChatGPT сначала дважды выдал частичную память за точный конец чата «Восстановление состояния проекта». Упоминания adversarial 7/7 и STOP FOR USER REVIEW не были надёжной точкой продолжения. Пользователь принёс первичный фрагмент и исправил её. В дальнейшем сразу отделять доступный текст, память и реконструкцию; не писать «нашёл/проверил», если поиск фактически не выполнен.

Первоначальный критерий: **LAST BUILD DELIVERED TO USER BEFORE CUTOFF**, не last confirmed working build. Сначала оригинальный EXE. Rebuild только после доказанной утраты оригинала и точного commit/tree, с отдельным разрешением.

Затем пользователь уточнил цель: последний оригинальный **Stage 6B.2 installer**, лично установленный и положительно протестированный им; финальный PASS в DCS Changelog Watch не сохранился/не был отправлен. Нынешнее подтверждение пользователя важно, но не создаёт отсутствующий installed manifest исторического прогона.

Пользователь ранее просил не останавливать отдельную Work-задачу, поручив Astra независимый forensic. ChatGPT общался с локальным исполнителем через пользователя, не управлял задачами напрямую. Конечный статус той отдельной Work-задачи не проверен.

## 2. Три исторических установщика

### Pre-IA6 Lifecycle

Commit `b7800db89e4470bc9aea4e89d5376d5cb9fafc15`.
SHA-256 original installer: `632E00674BE97BBDFA8897EF431237B6DD18462443526C808F717F21B641C037`.

27 августа 15:00:26 МСК пользователь сообщил: «тест прошел хорошо - после exit в трее core и launcher из процессов исчезли». Это lifecycle/exit PASS, не full voice PASS.

### IA-6 Live — первый, затем заменённый recovery target

Commit `5c5c8314b5309a624ee93e584deadbb22d155a2b`.
Original `ORION-Alpha-0.2-IA6-Live-Setup.exe`.
SHA-256 `172F62088B0FFF9F8024F541EC6BDF440A05B634CCA1180A052B987211F56EB2`.
Выпуск: 27 августа 18:33:10 МСК.

Первоначальный cutoff был сообщением 27 августа 20:58:14.122764 МСК о расширении ORION до голосового управления DJI Neo. HTML update 20:59:23 не доказывает первоначальную редакцию ровно в 20:58. IA-6 — последний найденный original installer до этого cutoff, но не последний Stage 6B.2 installer. Эти временные границы различаются.

### Stage 6B.2 — окончательный recovery target

- Commit `a955d7c39f20c020e15de6bc2be272755928cc98`.
- Tree `7c010efadc2a8c0b6b892b49354a4019e4fdb3b2`.
- Original `ORION-Alpha-0.2-Setup.exe`.
- SHA-256 `CBC83918BE631A48E50D27A3F93D97091BB1DAF44AB546C2A17CA026F06F6F46`.
- Local source: `release-stage6b2-20260828/installer/ORION-Alpha-0.2-Setup.exe` under the user's ORION repository.
- Reported delivery: 28 августа 01:31:52 МСК; historical probe: 01:43–01:45 МСК.

Связь installer с историческим испытанием HIGH CONFIDENCE. Старый archive содержит `orion_build_sha=unknown`; exact installed bytes тогда не подтверждены отдельным manifest. Пользователь выбрал именно Stage 6B.2 как последнюю лично проверенную реально работающую сборку. Не возвращаться к IA-6 как основной цели.

## 3. Обратимое восстановление и авторизация

Локальная Astra установила: modern ORION `17ddfd12…` совпадал с 3267 product files своего installer, но рядом находились 20 старых файлов и противоречивые version labels. Общие AppId/install path/user data делали overlay нечистым. Uninstaller удаляет runtime/voice credentials; выбрана изоляция целых каталогов без деинсталляции.

Modern backup: `%USERPROFILE%/Documents/ORION-Restoration/HISTORICAL-IA6-RETEST-20260915-16/CURRENT-BACKUP`; каталоги `ORION-CURRENT-HOLD-20260915-16`. В отчёте повторно проверены 4395 backup files. Сохранены installer, installed files, registration/uninstall state, shortcuts, external configurations и credential references.

Сначала IA-6 установлена original EXE, 3189/3189 payload PASS. Переносились `active-dcs.json`, `runtime/cloud-voice.json`, `runtime/audio-device-selection.json`, `runtime/qwen-controller-binding.json`. Вложенный `Scripts/ORION/Export.lua` исторический; главный `Scripts/Export.lua` не менялся.

Затем Stage 6B.2 установлен вместо изолированной IA-6. Её backup: `%USERPROFILE%/Documents/ORION-Restoration/STAGE6B2-RESTORE-20260915/IA6-BACKUP`. Проверены 3189 exact product files плюс два штатных uninstaller files. Missing/modified/unexpected product files отсутствовали по отчёту Astra. Modern hold не изменён. Это локальные отчёты, не повторная удалённая проверка Windows при EOD save.

### Credentials

Пользователь увидел пустой Folder ID, трудность вставки и `insufficient_permissions`. ChatGPT ошибочно предположил, что второй identifier может быть Folder ID. Astra установила: это ID API-ключа от 31 августа, не Folder ID. Исторический каталог default был правильным.

Найден original key от 26 августа; secret восстановлен локально. Предыдущая credential сохранена отдельной защищённой записью Windows Credential Manager. Exact session.update из a955d7c прошёл HTTP101 → session.created → session.updated без генерации и радио. Поздний ключ также открыл сессию с правильным каталогом: причина прежнего отказа НЕ ДОКАЗАНА. Timestamp перезаписи Credential Manager сам по себе не доказывает изменение secret.

В публичную историю не переносим секреты и credential identifiers. Не спрашивать у пользователя ключ повторно; не ротировать и не угадывать Folder ID. Для разрешённого локального probe читать только известный ORION credential target.

### Что пользователь реально исправил после установочного отчёта

Первый запуск Stage 6B.2 снова показал пустой Folder ID/Direct Audio, позднее — отсутствие active DCS installation. Статус «всё восстановлено» был преждевременным относительно UI. Пользователь устал от бесконечных forensic-инструкций.

Фактически доведено: Folder ID введён, TEST CONNECTION OK; SRS Radio выбран, SAVE VOICE SETTINGS успешно; DCS SETUP выполнен до DCS READY. Не повторять настройки без новой проблемы.

SRS server/client и EAM были подключены, но ORION SRS NOT CONNECTED не менялся от REFRESH. Пользователь установил, что нужен START LIVE; после него появились ORION SRS READY и YANDEX STREAMING. Не связывать этот индикатор автоматически с DCS telemetry.

Раздел TEST оказался проверкой устройств, не интерфейсом нового live test. Test A/Test B — наши recovery-обозначения, не две штатные кнопки Launcher. Не отправлять пользователя искать несуществующую кнопку TEST B.

## 4. Исторический Test A и повтор 15 сентября

Исторический 28 августа: 10 готовых synthetic phrases × Realtime/SpeechKit, 20 completed transmissions, 1703 frames; BLUE 251.000 AM; свежий F/A-18C context, миссия неизвестна; acoustic_review=clear. Два ранних SRS RX без сохранённых words/STT/responses не доказывают полный input path. Cancel отправлялся, terminal completed: фактическое прерывание речи не доказано.

Новый Test A: `ORION-Test-Evidence-20260915-194026.zip`, 117 events, dropped_event_count=0, по20 adapter starts/completions и SRS starts/completions, 20 WAV, 1706 frames. На вопрос «Вы услышали все 20 передач через SRS нормально и разборчиво?» пользователь ответил «да». Это прямое новое акустическое подтверждение.

После20 TX последнее событие117 — `ia11_probe_failed/RuntimeError`. Audible20/20 PASS сохраняется, но formal post-probe interruption/recovery PASS не заявляется. Не смешивать1703 старых frames с1706 нового прогона.

Cases: heading-137; tas-286; altitude-12450; radio-264500; tacan-44x; laser-1577; callsign-viper21; distance-63; negative-850; tacan-unavailable. Все возникли из одного IA-1.1 prompt 26 августа13:32UTC, не десяти отдельных live ошибок. negative-850 — отрицательная поправка, не heading. Altitude case не устанавливает MSL/AGL; frequency case не доказывает нормативное ICAO digit-by-digit произношение.

Test A: prepared fixture text → Realtime/SpeechKit → PCM → RadioRouter/adapter → SRS. Это presentation fidelity и доставка, больше чем UDP smoke, но не microphone/STT/understanding, не live DCS normalization и не универсальный renderer.

## 5. Новый live Test B на original a955d7c

Пользователь предложил запустить DCS и попробовать вместо новых реконструкций UI. Для F/A-18C предложен запрос «В каком самолёте я нахожусь?». Затем получен широкий `ORION-Test-Evidence-20260915-200113.zip`.

Счётчики: 3501 events, 69 user transcripts, 69 response_done, 40 TX starts/completions, 8850 frames, dropped_event_count=0. WAV нет. 69 provider completions не означают69 услышанных передач. Раннее упоминание59 unique answers не заменяет итоговые счётчики.

Сохранились free conversation, greetings, память имени в сессии и DCS-context queries. Примеры: «привет», «добрый день в каком самолете», «в каком самолете я нахожусь» с ответами о F/A-18C. Это генеративная conversational capability, не доказанный protected MIXED Composer.

После смены самолёта:

- events1271–1272,19:53:55.597UTC: отправлена/локально помечена applied F-5E-3 projection;
- events1324,1596,2235: ответы всё ещё Hornet;
- event2376: позднее F-5E-3.

Applied marker не доказывает provider semantic adoption или root cause stale selection. Также3 `response_buffer_limit` (565,1545,2803),1 `response_queue_full` (3130). Числа высоты/координат не проверены для каждого ответа против exact source snapshot.

Ранняя оценка примерно1016ms до first provider audio не является end-to-end latency до уха: SRS endpoint ждёт полный PCM. Не объявлять достижение <1s по этой метрике.

Итог: **Stage 6B.2 a955d7c — RECOVERED AND LIVE FIELD VALIDATED AS A HISTORICAL CHECKPOINT.** Не финальная завершённая архитектура, не безошибочная фактология и не найденный утраченный августовский PASS.

## 6. AS-BUILT: три отдельные цепочки

### Обычный разговор

SRS RX/transmission completion → YandexRealtimeSession с injected FlightContext → Yandex Realtime `speech-realtime-260528` понимает/разговаривает/генерирует text/audio → SrsYandexPcmEndpoint собирает целый ответ → single-slot TX queue → существующий SRS worker.

Qwen не участвует в обычном Yandex/SRS conversation. Transcript записывается, но не вызывает автоматически InteractionRouter/ToolGateway. Core предоставляет DCS context, не проверяет каждый generated factual reply. RadioRouter не стоит на каждом live turn.

### Strict IA-6

Отдельный text/API path: interaction/planner → Qwen3.6-35B (`qwen3.6-35b-a3b` в аудите) через Yandex Responses/AI Studio → ToolGateway/WorldModel → bounded ownship semantic result, exact value/provenance binding для heading/latitude/longitude. Не приписывать ему migration обычного speech path или universal natural understanding.

Qwen direct-audio Realtime также существует как другая provider option. Отсутствие отдельного ключа в UI не доказывает отсутствия Qwen в source.

### Hybrid Probe

Prepared phrase → isolated Realtime или direct SpeechKit → RadioRouter → thin SrsRadioTransportAdapter → existing SRS worker. SpeechKit не получает Realtime output как input.

6B.1: immutable RadioContext/RadioEntityRef, neutral adapter/Fake, Router priority/FIFO/replay/completion. В восстановленном отчёте Router default queue=8; endpoint TX queue=1 — разные очереди. 6B.2 не предоставляет active TRANSMISSION_CANCEL. Queued cancellation не равен доказанному active interruption.

## 7. AS-INTENDED: только тогдашний DCS Changelog Watch

Пользователь многократно требовал тематически собрать разбросанные рассуждения, учитывать изменения решений и не подглядывать в будущую разработку. Три загруженных тематических отчёта прочитаны/сверены. Это историческое знание, не новая санкция на реализацию.

Source: conversation `6a84d8f8-77b8-83eb-ae57-869cd8c0ebfe`,2072nodes/2071messages, без видимых branch points. Диапазон18 августа22:13:17UTC →27 августа22:34:09UTC, то есть28 августа01:34МСК. После27 августа17:58UTC доступная поздняя часть в основном user messages/quotes. Final6B.2 report/PASS отсутствует. Last observed decision не гарантирует отсутствия утраченного superseding решения.

### AI и Core

AI понимает целую естественную реплику, неоднозначность, reasoning и рекомендации. Это не каталог команд и не обязательный keyword classifier. Core владеет authoritative facts, единицами, расчётами, state, permissions, domain decisions, validation, execution receipts. WorldModel — read-only facade над существующими owners, не конкурирующий store. ToolGateway ограничивает schemas/capabilities/freshness/permissions/actions, не unrestricted DCS Lua.

Facts несут source/authority/status/freshness. unknown/unavailable/stale/restricted не превращаются в0 или «контактов нет». Mission truth не sensor detection.

Итоговое историческое название: **Hybrid D mechanism + Hybrid B fail-closed policy**. Core формирует protected semantics → deterministic typed rendering → immutable fragments → final composition. Модель не получает finalized protected fragment на rerender. Optional AI envelope не содержит protected values/operational tokens; invalid envelope отбрасывается, invalid protected output блокируется. Это ограничение authority, не отказ от AI.

### Providers и четыре вида взаимодействия

Qwen Realtime как ранний voice эволюционировал в Yandex native/noncritical conversation, SpeechKit finalized critical speech и один Qwen3.6 reasoner/planner. Не гонять каждый Roger/привет через deep model. Полная окончательная FREE matrix Yandex vs Qwen envelope НЕ ЗАКРЫТА. Не придумывать обязательный Qwen every-turn или его отмену. Presentation policy provider-neutral; engine не hardcode «всё operational=SpeechKit».

FREE — базовый разговор без ненужного DCS tool; язык следует пользователю, не профилю. Непрерывная provider session полезна, но её память не authority состояния самолёта.

INFORMATIONAL — AI understanding → controlled query → fresh typed fact/status → Core normalization/calculation → protected rendering значимых данных. Heading/altitude/frequency защищаемы; universal renderer для всех вопросов не специфицирован.

OPERATIONAL — AI понимает/предлагает; Core domain решает clearance/denial/action; receipt подтверждает исполнение. OperationalSemanticUnit переносит утверждённый смысл, не решает взлёт.

MIXED — пользователь прямо настоял на social части: «Добрый день, colt1-1» и «еще раз добрый день! Разрешите взлет». Exclusive FREE OR OPERATIONAL признано слишком грубым. AI выделяет components, Core renderer/composer объединяет social+protected, urgency может убрать chatter. Это accepted design, не historical field PASS. Общий FREE+INFORMATIONAL principle есть; отдельная полная decomposition specification не найдена.

### Phraseology Engine / KB

Pure local deterministic renderer получает OperationalSemanticUnit[], не NL реплику. ProfileResolver → RuleResolver → typed formatters → templates. Не вызывает WorldModel/tools/TTS, не reasoning и не принимает clearance decision.

Одна Core-owned normative KB; immutable ACTIVE/CANDIDATE/PREVIOUS; interaction pins snapshot; offline source/licensing/semantic/human review; atomic activation/rollback. Qwen может помогать как untrusted extraction, но не owns KB и не активирует правила. Extended RAG отложен.

Final MVP coverage: ICAO ATC + NATO AWACS вместе для profile/domain proof. Controlled field verticals затем ATC→AWACS последовательно. Ранний only-ICAO заменён. «20–30 Pilot KB phrases» в pre-cutoff не подтверждены; найдено раннее10–15 ATC units. Ранние сообщения ChatGPT импортировали позднее число/название: не использовать как августовский факт.

Profiles: ICAO, FAA_US, NATO_MILITARY, FAP_RUSSIAN_ATC. Отдельны от input/conversation language, не меняют facts/permissions. Russian Military не подмена ФАП; AUTO/Mission Realistic — future. Наличие IDs не готовый normative coverage.

### Radio, domains и latency

RadioRouter — delivery/context/selection/queue/priority/replay/completion/failure, не reasoning/TTS/phraseology. SRS first proven transport, DCS native условен supported API. 6B.2 мигрировал controlled probe, не все live replies.

ATC authority — Core runway/traffic/clearance state. AWACS — разрешённая detected picture и Core geometry, не всеведение по MissionStore. Полный RadioEntity voice registry не реализован одним наличием seam.

Отзывчивость/fast-deep split обсуждались. Нынешняя пользовательская цель ideally <1s сохраняется, но единый исторический hard acoustic SLA <1s из pre-cutoff не доказан. Provider first audio не звук в ухе.

### Последняя доступная revision roadmap

IA-6 → Stage6B radio foundation → Phraseology contracts/Core engine+KB MVP → ICAO ATC → NATO AWACS → WorldModel coverage по потребности → остальные domains → FAA/ФАП → большой Launcher/installer cleanup. UI пользователь отложил. Exact post-6B2 implementation prompt/номер утрачен; не присваивать поздние Stage7A/B/C.

### Первичные pointers из тематического отчёта (UTC)

| Ref | Time | Node | Содержание |
|---|---|---|---|
| E01 |18.08 22:53:34|a72b81df-9e4c-4682-bd95-904311b45632|Qwen голос/собеседник, ORION facts/context/actions|
| E02 |20.08 16:40:54|eef29f9b-5f66-4f59-9fc8-c6109f0022dc|User выбирает natural conversation + Core tools|
| E07 |25.08 19:19:04|18cdcc5b-4ec7-4b09-9153-cd89a17c93eb|Radians→[0,360), magnetic reference not proven|
| E15 |26.08 13:30:11|0eee059c-6c8b-4bcd-b501-adf152f31dad|Dash/minus HIGH CONFIDENCE, не CONFIRMED|
| E16 |26.08 13:32:38|9bf06831-36ed-4481-ace1-8d78ab806676|IA-1.1 PRESENTATION-only cases|
| E29 |27.08 09:29:08|995203a1-f46c-4cd3-ad92-4116e620a3af|User mixed greeting/takeoff example|
| E30 |27.08 09:56:25|5078ee96-ed3d-4fed-978d-5b77d0558a14|«Утвердили. Записывай»|
| E34 |27.08 14:29:48|d2aaf308-9b7f-42eb-966e-924ad55c53b7|HybridD/HybridB report, затем accepted E35|
| E37 |27.08 15:39:08|a637d0b1-db07-46e4-9b7e-d7ac7ab3feec|Radio first, Phraseology next, UI deferred|
| E39 |27.08 21:54:30|44cc2e37-e461-487f-ac6c-fe3fe93c1c03|Stage6B1 49f083d|
| E40 |27.08 22:34:09|aea0d839-be0d-42ba-9a56-5bbbeab11fae|Цитата install a955d7c + Hybrid Probe, не final PASS|

## 8. «Минус»: зачем вообще нужна защита presentation

Пользователь сравнил чистые TestA ответы и live «курс минус137», предположив, что6B2 был промежуточным доказательством, не завершённым продуктом.

История разделяет raw telemetry → canonical semantic fact → protected text → actual sound. Correct source не гарантирует correct generated text; correct text не доказывает correct acoustics.

25 августа: отрицательная «скорость», TAS/VS/units hypothesis; Core normalization в6A.1, heading[0,360), MSL/AGL, DDM coordinates, запрет угадывать географию. 26 августа: «минус241градус»; source241 положителен, input безminus/dash; Realtime добавляет «скорость —241 узел». Dash→minus HIGH CONFIDENCE, raw WAV отсутствовал; altitude в том ZIP NOT OBSERVABLE.

Нынешний minus137 не найден в transcript TestB и не имеет exact source/WAV. RCA unknown. Не применять modulo к услышанному числу по догадке. Heading/altitude/frequency/TACAN/laser/BRAA требуют semantic protection, но TestA начинался готовыми строками. Stage6B2 был transport/delivery closure, не отсутствующим general normalizer/renderer.

## 9. Интеграционный preflight, который НЕ разрешил patch

После восстановления пользователь спросил, достаточно ли информации для соединения частей. Предложен минимальный FREE/HEADING/MIXED/FREE-after vertical без ATC и общего переписывания. Heading — диагностический slice, не доказанное RCA minus137.

Astra вернула **GO WITH CONDITIONS, не готовность к реализации**:

- 8 runtime +8 test files в условном changeset;
- finalized input в YandexRealtimeSession.receive_worker перед native audio admission;
- Core heading read без Qwen, но AI heading-only route отсутствует;
- SpeechKit/RadioRouter reusable;
- blockers: typed interpretation, input→response association, double answers, FREE suppression и provider history несказанного ответа;
- первый MIXED ограничен AI greeting cue + Core composition.

Changeset не одобрен. Полный preflight в чат не загружен, получена сводка; не дописывать ему неизвестные выводы. ChatGPT сперва предложил отдельный Typed Interpretation Probe. Пользователь потребовал изучить аналоги. После этого выбрана проверка native function calling, не обязательный новый классификатор FREE/HEADING.

## 10. Аналоги — исследовательские leads, не новая authority

Обсуждались DCSClaude/DCSCopilot, SkyEye, ATC-Bot, Wingman AI, COVAS:NEXT, LiveKit Agents. Полезные идеи: model выбирает tool, code поставляет game state; function result можно отделять от directly spoken response; domain calculation отдельно от speech composer; tool closure, reply admission и history — самостоятельные операции.

Видимые чтения включали DCSClaude copilot.py/llm.py, SkyEye parser/controller/composer/format.go и ATC-Bot context→LLM→TTS. Это не proof строгой ORION protection и не доказательство превосходства модели.

В некоторых итоговых сообщениях были несогласованные ссылки, а заявление об отсутствии DCSClaude source противоречило ранее прочитанным файлам. Поэтому внешние сравнения — leads; конкретный механизм перед переносом заново открыть в pinned primary source. Эти сравнения не используются для восстановления августовского intent. Главное — проверить НАШУ модель/API, не копировать чужую систему по репутации.

## 11. Exact a955d7c: что выяснили перед настоящим probe

`yandex_realtime_provider.py`: speech-realtime-260528, dasha/neutral, ru-RU, requested PCM44100; session update не регистрирует tools; test_tool_call disabled/not implemented.

`yandex_realtime_session.py`: transcript только diagnostics/evidence, function_call execution/result отсутствуют; неизвестные события логируются.

`yandex_srs_live_core.py`: PCM буфер поresponse_id; _maybe_queue требует audio_done +response_done +completed +nonempty +not dropped/queued. Первый provider chunk ещё не SRS TX. Admission gate на полном ответе технически возможен, но сейчас отсутствует.

FlightContext update снова вызывает общий session update с audio modality: одноразовый text-only switch может быть отменён следующим update.

Документация native tools дала candidate, не runtime proof. Пример другой модельной версии нельзя автоматически переносить на260528. call_id не физический PTT ID. Не использовать неподтверждённые API поля, возможности другого провайдера или предположение, что cancel вернёт уже переданный звук. TEST CONNECTION не test tools.

Задание первого probe — YANDEX-260528-NATIVE-TOOLS-VERIFICATION.md: отдельный процесс/sessions, один synthetic fixture tool,24 generation cap,10min,no retries,no ORION/SRS/DCS, credentials локально. Аутентифицированный запуск выполнила локальная Astra, не ChatGPT.

## 12. Первый native-tools probe и окончательный независимый review

Astra: PARTIAL,16генераций/3sessions/no retries. Затем пользователь загрузил ZIP, а ChatGPT проверил его offline, без исполнения probe.py и новых provider calls.

### Целостность и счётчики

ZIP SHA-256 `CB171921D7287912034DD80AFCB6A3AA54B8E253BBAC0B233E06CC14F631902D`.
Events SHA-256 `5E45C6825DDC5B4FA5F02709C71E9533FA26E4B52BAAB61A4A832F3CC0B0EDB9`.

CRC valid,19manifest entries плюс самmanifest=20files. 436 continuous events, monotonic nondecreasing;3sessions,12TEXTcases,16response.create/created/done all completed;5unique tools/results exactcall_id. Все5tool responses имеют0PCM. 11WAV,4,546,300PCMbytes, per-delta hashes совпали. Header mono16/44100 записан runner, не независимый server-rate proof. Config/prompt/schema hashes consistent;force_tool=false,args={}. No provider error events;no input_audio_buffer.append. Акустическое прослушивание не выполнено. Это внутренняя согласованность evidence, не независимая серверная аттестация.

### CONTROL и EXTERNAL — разные эксперименты

CONTROL: text →native functioncall →numeric/status fixture →explicit response.create →Yandex generated answer. Курс пересказывает модель. MIXED и ambiguity проверены здесь. Local protected formatter/composer,SpeechKit иSRS отсутствуют.

EXTERNAL: text →native functioncall →local fixture223 →service receipt БЕЗ ЧИСЛА →NO response.create →тишина →nextFREE. Seq399 local223,400receipt deliveryNOT_SENT,401нет incoming events/responses/audio за5.016s,432FREEcompleted. Это ONE text case, не VAD/concurrency/long-window proof. Изменены одновременно содержаниеresult и запроспродолжения: нельзя причинно приписать тишину только одному фактору. Numeric-result/no-response.create отдельно не проверен.

### MIXED

Seq81–119: «Добрый день! Какой у меня курс?» →tool{} →137 →runner response.create →«Ваш текущий курс составляет137градусов». Greeting отсутствует уже в final provider text. Prompt просил сохранить его, но empty-object schema сadditionalProperties=false не имела social cue. Core Composer и EXTERNAL MIXED не испытывались.

Нельзя объявить model incapable of greeting understanding или whole intended architecture failed. Но native continuation MIXED в этом случае НЕ PASS. WAV совпал с предыдущим137ответом, что не доказывает replay/retry/cache root cause.

### Неоднозначность и fresh-read

Seq231–263: «Куда я сейчас лечу?» →«Ваш текущий курс составляет137градусов — это направление движения самолёта»,tool_calls=0,no clarification. Fixture всё ещё137; он меняется на223 толькоseq264. Доказана current assertion безfreshread, НЕ wrongstale137against223.

Вhistory присутствовали и tool137, и пользовательский вопрос объяснить137; внутренний источник выбранного числа не установлен. После смены прямой вопрос «А какой у меня курс сейчас?» вызвалtool и получил223.

**Следствие: no function_call НЕ равно safe FREE.** Prompt уже требовал fresh lookup, запрещал память как current authority и просил уточнять ambiguity. Новая формулировка сама по себе не enforcement. Receipt-only может уменьшить один источник history contamination, но не доказанная защита: числа могут быть вusertext/FlightContext. Не очищатьhistory радиPASS.

### Корреляция, receipt, metadata, закрытие

Call→result5/5;response→items/audioIDs проверены. Input→response — oneactivecase ordering; explicit originating input_item_id отсутствует. Для ограниченного prototype допустим честный sequential ledger с отказом при ambiguity, не lastresponse heuristic и не PTT/barge-in proof.

Server ACK function_call_output отсутствует. Это само по себе не установленная ошибка: control data влияют наответ,nextFREEпослеreceiptработает. Не выдумывать ACK/delivered.

Каждая session сначала возвращает kirill, затемdasha;runner начиналпослепервогоupdate;response metadata kirill/role=null,rate=null. Actualvoice/rate notverified. Аудиовход не был выполнен вообще.

P1/P2CONTROLclose1000;P2EXTERNALclose1006послеsuccessfulFREE. Причинаunknown;summaryfailure=nullнеозначаетcleanclose.

### Итог

**TEXT-INPUT NATIVE TOOL PROTOCOL VERIFIED IN SUPPLIED EVIDENCE. EXTERNAL-RESPONSE CANDIDATE PARTIALLY SUPPORTED. PROTECTED MIXED/AUDIO/LIVE INTEGRATION NOT PROVEN.**

Модель не менять и не добавлять Qwen ради одного запроса на основании этого результата. Прежний16filepatch не разрешён. Protected phrase не возвращать наgenerative rerender. После review новых экспериментов не было.

## 13. Подготовленное продолжение и точка паузы

Создан `YANDEX-260528-INDEPENDENT-REVIEW-AND-NEXT-PROBE.md`, section9. Результата следующего probe пользователь ещё не прислал. Сохранённая исполнимая постановка — NEXT-ISOLATED-PROBE.md.

Содержание: paired CONTROL/EXTERNAL сfixture137→223 ДО ambiguous question; AI-selected bounded greeting cue →local protected composition; реальные synthetic audio questions FREE/HEADING/MIXED с одним pending turn; один heading иодинmixed output черезSpeechKit вWAV безplayback/SRS.

Budget24generations/10min/30sresponse/8MiBPCM,≤6SpeechKitsyntheses и≤1200chars,no retries. Previous evidence immutable. Остановиться приcurrent assertion безfresh tool; не маскироватьнеудачуregex/expected-caseprefix/retry.

Это подготовленная задача для отдельного разрешённого локального исполнения, НЕ выполненный эксперимент и НЕ разрешениеproduction integration. При возобновлении сначала спросить/проверить, нет ли уже результата отлокальнойAstra, чтобы не повторитьплатныйprobe. ChatGPT не имеет подтверждённого инструмента прямой отправки в её существующую Windows-задачу.

## 14. Предпочтения пользователя и запреты

- Historical baseline и late production не смешивать; читать exactcommit, не текущийHEAD поумолчанию.
- Originalinstaller преждеrebuild; backup modern/IA6 сохранять; безuninstaller/overlay.
- AI понимает цельную речь; Core не превращать вregexNLP.
- FREE сохранить; protectedvalues не отдаватьLLMнаперефразирование.
- Не выдавать20TXзаfullvoice,CONTROLзаEXTERNAL,knownvalueзаfreshread,providerfirstaudioзаacousticlatency.
- a955d7c — ценный fieldvalidated checkpoint, не окончательная архитектура.
- Не заставлять пользователя заново искатьcredentials/угадыватьID или делатьдесяткиручныхшагов,которые безопасно выполнит локальнаяAstra.
- Пользователь устал от бесконечных preflight/forensic циклов и неверных UI инструкций. Нужны реальные проверки, точный вывод и один ограниченный следующий шаг.
- Исторический intent собирать тематически сsupersession, неfutureknowledge.
- Возможности аналогов не переносить междуLLM/APIбезпроверки.
- Сегодня работа остановлена; фоновое продолжение не запускать.

## 15. Исправления с приоритетом над ранними сообщениями чата

1. Target не IA-6, а original Stage6B2a955d7c.
2. Исторические20TX не доказывали полныйvoiceinput; новыйTestBотдельный.
3. ОбычныйliveговоритYandex,неQwen,иобходитRadioRouter.
4. TestA — preparedphrases,неlive telemetrynormalization.
5. «Минус»неавтоматическиnegativeDCS;RCA−137unknown.
6. НовыйA:20TXуспешны,terminalpostprobeRuntimeErrorсохраняется.
7. НовыйB:40TX,не69acousticturns.
8. FlightContextнегарантируетfresh/correctgeneratedspeech.
9. «20–30PilotKB»иMixed9/9+14/14неподтвержденыпервичнымиprecutoffисточниками;неимпортировать.
10. Nativefunctioncallingtexttested,ноnotvoice/liveintegration.
11. MIXEDfailureпринадлежитCONTROLcontinuation,неCoreComposer.
12. Ambiguous137сказанприfixture137;fresh-readviolationважен,ошибочноечислонедоказано.
13. Externalquiet:receiptcontentиresponse.createpolicyизмененывместе.
14. Inputcorrelation/voice/rate/cleanexternalcloseнеполностьюдоказаны.
15. СтарыйrepoC4неявляетсяnextstepданногоrecoverytrack.

## 16. Сохранение документации не меняет runtime

EOD save добавляет только Markdown. Он не меняет historical commit/tree, installed bytes, credentials, settings, local working tree, backups или другие ветки. Remote dev documentation HEAD меняется от EOD commit, но это не новыйruntimebuild. Не объявлять локальныйcheckoutсинхронизированнымбезgitfetch/status.

Для следующего сеанса прочитать `docs/ORION_CONTINUATION_CHECKPOINT_20260916.md`, этот документ, ARTIFACT-INDEX и NEXT-ISOLATED-PROBE. Сверить новые сообщения и фактическое состояние прежде любых действий.
