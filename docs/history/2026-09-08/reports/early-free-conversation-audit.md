ORION ARCHITECTURE GUARD: OFF

## A. SOURCES VERIFIED / CURRENT BASELINE

**Свободный AI-разговор в истории ORION подтверждён.** Он существовал до D75 и современной recovery-линии. Но первые разговорные ответы Core были фиксированными; настоящая генеративная голосовая беседа появилась позднее, через Qwen Realtime.

Текущий `nontext_session` не доказывает отсутствие текстовой генерации у Yandex. Историческая текстовая генерация подтверждена сохранёнными provider benchmarks; точное серверное поле, вызвавшее нынешний отказ, утрачено.

### CHATGPT DATA EXPORT

Проверен [полный сохранённый ZIP](C:/Users/Алексей/Downloads/8b671f56c3ff3df7035ae1d1ec80174fa7f73adfa50705729b779ab8d5aebfe7-2026-08-28-13-02-09-2d3aca73e120442a869eecc0aec68752.zip).

- Размер: `233 063 533` байта.
- SHA-256: `EDD800F61210C6C682414E960C1A54D62DBBCC6DEED27B7FDF741DC5499937DB`.
- Дата в имени экспорта: **28.08.2026 13:02:09**, без явно указанного часового пояса. Локальное сохранение 30 августа — не дата экспорта.
- Структура: 446 файлов; `conversations.json`, `chat.html`, manifests, отображение имён вложений, 435 `.dat`-вложений и служебные JSON.
- **42 conversation records, 12 154 сообщений**.
- Диапазон сообщений: **01.08.2026 20:13:44 — 28.08.2026 12:57:06 UTC**.
- **29 бесед содержат ORION**; это число совпадений по содержимому, а не 29 независимых разработческих веток.
- Все 42 записи просканированы по содержимому. Хронологические окна подробно прочитаны в `Разработка ORION-000`, `ORION PR #104 Checks`, `Проект Orion продолжение`, `DCS Changelog Watch`; дополнительно проверены ранние сообщения `Репозиторий ORION готов` и `Проверка телеметрии ORION`.
- Прочитаны относящиеся к ключевым событиям диагностические вложения, включая исходный Yandex report с транскриптами.

Экспорт **содержит более раннюю историю, отсутствующую в отдельном DCS HTML и локальных Codex rollout**. Для августовских пользовательских сообщений он принят основным contemporaneous conversation source.

### Остальные источники и покрытие

- [DCS Changelog Watch.html](<C:/Users/Алексей/Documents/Новая папка/DCS Changelog Watch.html>) повторно проверен: SHA-256 совпадает с `AEEF61CDEB42A58A1A4803BFE055891A3873AA5BB80BA6D1D529D05DC65CB718`. Проверен скрытый массив сообщений, а не только видимый HTML.
- Подтверждён backing ID: `6a84d8f8-77b8-83eb-ae57-869cd8c0ebfe`.
- Просканировано содержимое **всех 21 доступных Codex rollout** в [локальных sessions](C:/Users/Алексей/.codex/sessions), за 19 августа — 8 сентября.
- Подробно использована задача [«Исправить SRS RadioInfo в ORION»](C:/Users/Алексей/.codex/sessions/2026/08/24/rollout-2026-08-24T19-31-34-01a0349c-ea7d-72c1-9d75-acbfd02f9343.jsonl).
- Проверены repository checkpoints, ADR-004/005/006/007, `ORION_PROJECT_MEMORY.md`, исторические документы, локальные Qwen/Yandex diagnostics и presentation benchmarks.
- Проверены доступные архивные места в Documents, Downloads, Desktop, `.codex` и сохранённых ORION evidence.

**Ограничение покрытия:** это весь обнаруженный локальный набор, не доказательство доступности всей когда-либо существовавшей истории ChatGPT. Удалённые беседы, несохранённые полевые состояния и содержимое всех изображений/аудиовложений не восстановлены.

Текущий worktree: [ORION-level0-conversation](C:/Users/Алексей/Documents/GitHub/ORION-level0-conversation).

- HEAD: `dca668d530dc6cbc4de05064400b22c2216ada3f`.
- Runtime baseline: `f0c9e364ed653e9497d7e2ef8ef8f35dc97157d4`.
- Tracked runtime diff относительно `f0c9e364`: отсутствует.
- Существующие семь untracked файлов Level-0 сохранены.
- Код, Git, архивы и установленный продукт не изменены; тесты, providers, DCS/SRS и сборки не запускались.

## B. EARLIEST DIALOGUE TIMELINE

Все времена ниже — Москва, если не указано иначе.

| Дата/checkpoint | Что действительно установлено | Уровень |
|---|---|---|
| 05.08, 15:47 | Пользователь предложил свободную форму запросов | L0 |
| 05.08, 15:48 | «Утвердили» — Natural Language First | L0 |
| 05.08, 15:50–15:52 | Предложены общение, случайная болтовня и новости; затем «Утвердили» | L0 |
| 06.08, `3aef774` | `classify_dialogue`: RU/EN intent matching, включая SMALL_TALK; фиксированные ответы | L1 |
| 06.08, `5240f7f`, `65419be` | Тесты intent routing и контекстных уточнений | L2 |
| 08.08, `5ea62ed`, `c81320f` | Grounded dialogue с данными миссии и детерминированными ответами | L1/L2 |
| 13.08, `d45a7b0` | Audio Test «Привет, как дела?» → фиксированный ответ | L1/L2 |
| 16.08, 18:27 | Пользователь услышал «Всё хорошо. Связь установлена» | L6, **не генерация** |
| 17.08, `b74bf1c` | Qwen Realtime text/tool smoke adapter | L1/L2 |
| 18.08, `e4cb203`, Build #332 | Исправлен обязательный user item перед `response.create`; сохранён отчёт о passing tool smoke | L3 по contemporaneous отчёту |
| 18.08, `091d408` | Коммит полноценного Qwen microphone → cloud → audio runtime | L1 |
| 19.08, #389 / `816efb0` | Первое найденное прямое подтверждение ответного AI-звука | L6 |
| 20.08, #402 / `4e8b49a` | Пользователь принял нормализовавшуюся речь как baseline | L6 |
| 24.08, Yandex tester | Сохранились точные generative transcript/response и playback evidence | L3 + machine playback |
| 24–25.08 | Yandex → SRS и затем DCS FlightContext | L4–L6, с разными границами доказательства |

L0 — обсуждение; L1 — код; L2 — offline; L3 — provider; L4 — DCS/runtime; L5 — физический voice transport; L6 — явное пользовательское подтверждение.

## C. FIRST TRUE GENERATIVE CONVERSATION

Самая ранняя найденная реализация **свободного генеративного разговора** — Qwen Live, `091d408`, затем #389.

Предшествующий `b74bf1c303ecbe484103bf0988f8477494843328` действительно использовал LLM, но для **контролируемого text/tool smoke**, не свободного conversational runtime.

В `3aef774ef378e6243a49ba42d0b36ed15519aed7`:

- `orion/dialogue.py:53` — классификация;
- `:89` — `_reply`;
- `:97` — фиксированное «На связи. Продолжаю следить за обстановкой».

Называть это первой генеративной беседой нельзя.

Для первой Qwen-беседы полный текст вопроса и ответа не сохранился. Это ограничение точности реконструкции, а не основание отрицать сам диалог.

## D. FIRST TRUE VOICE CONVERSATION

**19.08.2026 01:23:29**, DCS Changelog Watch:

> «Идет ответный звук. Но с большой задержкой и по китайски»

Message ID: `6cb4b998-5eaf-4c6f-91b8-7c9fc59224c8`.

Контекст прямо связывает тест с **Build #389 / `816efb0594a61cd43caacad8fa0bd8afa6b8cbd3`**.

Более сильное свидетельство именно состоявшегося разговора — **19.08, 22:11:52**:

> «Я решил без тебя проверить что будет если выключу vpn. Состоялся небольшое диалог. Потом начались легкие заикания и все упало»

Message ID: `04a30475-8b7a-4693-b25f-66dc6fb72846`.

Оба — L6, высокая уверенность в услышанном генеративном голосе; точная первая пара реплик — неизвестна.

## E. USER-CONFIRMED FREE-CONVERSATION EVIDENCE

Основной conversation source — проверенный Data Export.

| Событие | Фраза / ответ / наблюдение | Связь и уверенность |
|---|---|---|
| 05.08, 15:50:28; `Разработка ORION-000` | «…режим общения — как дела? Хорошая погода сегодня. Или — сегодня придется сложновато» | `a990e6da…`; L0, высокая |
| 05.08, 15:51–15:52 | «Я бы и случайную болтовню добавил» → обсуждение новостей → «Утвердили» | `11fd6681…`, `546b2efa…`; требование, не работающий код |
| 16.08, 18:27:27; `ORION PR #104 Checks` | «Он распознал звук и сказал фраз “все хорошо. Связь установлена”» | `ff6f8696…`; L6, но fixed Core response |
| 19.08, 01:23:29 | Ответный звук, задержка, китайский язык | #389; L6 |
| 19.08, 22:05:02 | «…я сразу услышал чистый ответ привет и все упало» | `168cd38d…`; L6, точный SHA запуска не установлен |
| 19.08, 22:11:52 | «Состоялся небольшое диалог» | L6, деградация и падение |
| 20.08, 01:43:51 | «я спросил “как дела” ответ подразумевал длинную фразу и обрыв все равно случился» | `a0dc6ad4…`; точный вопрос сохранён, полный ответ — нет |
| 20.08, 18:44:57 | «в целом речь стала нормальной. думаю нужно фиксировать №402 как baseline» | `75bb1360…`; `4e8b49a`, L6, высокая |
| 22.08, 02:41:56 | Получены ответы хорошего качества, но на «стоп» — повторения «привет»/«стоп» | `40c71537…`; L6, не стабильная семантика |
| 22.08, 02:53:48 | Модель начала постороннюю реплику, когда пользователь молчал | `50b6d2ca…`; L6, причина из одной реплики не устанавливается |

Особенно важное **машинное вложение Data Export**:

`file_00000000af6c81fb87a42f168505133c.dat`  
Оригинальное имя: `yandex-realtime-diagnostic-20260824-001033.txt`.  
SHA-256: `D869B61EAB64813EBDDF043F3B84B8C26FA596A060FCF5852043760677C637F7`.

Внутри него:

- **24.08, 00:07:35.603:** STT `привет как дела`.
- **00:07:37.289:** ответ ` Привет! У меня всё хорошо, спасибо. А как ваши дела?` — исходный ведущий пробел сохранён.
- Response ID: `resp_30b47cc397f24ade9fc8bb3f42884c5e`.
- Ответ completed; 418 420 decoded audio bytes, 44,1 кГц PCM, около 4,744 секунды.
- **00:07:45.998:** STT `расскажи что ты умеешь`.
- **00:07:48.020:** ` Я могу отвечать на вопросы, помогать с информацией, писать тексты, придумывать идеи, решать разные задачи — спрашивайте, чем смогу помочь! 😊`

Это **YandexRealtimeTester**, ещё не production ORION. STT-текст — точный результат распознавания, не независимая запись того, что человек намеревался сказать. Общий playback подтверждён; отдельного пользовательского подтверждения каждой дословной пары нет.

## F. EARLY DIALOGUE CALL GRAPH

```text
06 августа:
POST /v1/dialogue → classify_dialogue → фиксированный _reply

06–08 августа:
transcript → VoiceContext → parser → dispatcher
           → mission/domain result → детерминированный spoken_text

16 августа:
микрофон → whisper.cpp/VAD → Core fixed reply → Windows SAPI → динамики

Qwen #389/#402:
микрофон → PCM/resampling → Qwen Realtime
         → provider-generated PCM → playback → наушники
```

У последней цепочки **не было обязательного промежуточного локального STT → LLM → отдельного TTS**. Распознавание, генерация и синтез находились внутри cloud speech-to-speech пути.

## G. QWEN REALTIME EVOLUTION

- ADR-004: перенос тяжёлой speech-обработки в облако ради CPU/GPU бюджета DCS/VR.
- `b74bf1c`: text/tool smoke.
- `e4cb203`: обязательный user message перед generation.
- `091d408`: настоящий audio runtime.
- #389 / `816efb0`: услышанный разговор, но задержка/язык/качество проблемны.
- `1963c60`: удалён legacy Whisper/ORION-Voice; Qwen transport #389 сохранён.
- #395 callback experiment — rejected, не эталон.
- `7c1c9db`: reference-aligned WebSocket.
- #402 / `4e8b49a`: reference FIFO playback; пользовательское принятие.
- Позднее — подключение Core tools, разные устройства, повторения, ложные turns и проблемы прерывания.

Исторический Qwen Realtime и поздний **Qwen Planner через Yandex AI Studio — разные роли и runtime paths**.

## H. YANDEX REALTIME EVOLUTION

- `ec660dc66188cff72db770350c5529996a620fa1`, 23.08: standalone reference tester.
- Первый найденный точный разговорный transcript/audio report — 24.08, 00:07.
- `6d3ad42`: response-scoped 20 ms interruptible playback.
- `1297316`: microphone/playback correlation.
- `6a4c5d5`: production provider integration.
- `655dd7f` → `1a06a09`: SRS tester и исправление регистрации RadioInfo.
- `fae96a9`: зафиксирован SRS/Yandex field baseline.
- Stage 6A: постоянная Realtime-сессия получает FlightContext.
- IA-1/IA-1.1: отдельные presentation contracts и сравнение с SpeechKit.
- Позднее HR01/C1/D75: **текстовая formulation operation**, а не возвращение provider-owned voice.

Важное различие: ранний Yandex Realtime говорил своим синтезированным аудио; современный recovery использует **native SpeechKit STT и отдельный protected TTS**.

## I. SPEECH I/O EVOLUTION

| Эпоха | Кто распознавал | Кто формировал ответ | Кто синтезировал |
|---|---|---|---|
| Ранний dialogue API | Вход уже текстовый | Детерминированный Core | Нет обязательного аудио |
| Whisper baseline | whisper.cpp | Fixed Core reply | Windows SAPI |
| Qwen #402 | Qwen Realtime | Qwen Realtime | Qwen Realtime |
| Ранний Yandex Direct/SRS | Yandex Realtime | Yandex Realtime | Yandex Realtime |
| D75 candidate | Внешний существующий ingress | Realtime formulation + validation/binding | Отдельный downstream SpeechKit |
| Текущий Level-0 draft | Замороженный native STT вне нового компонента | Предполагаемый text backend + Core admission | Существующий streaming TTS; **не испытано live** |

## J. SESSION / OPERATION CONTRACT HISTORY

Ранние Qwen/Yandex conversations были **session-based**: соединение жило между пользовательскими репликами; server VAD управлял turns.

Исторический text presenter:

- persistent connection;
- очередь `maxsize=1`;
- корреляция request/response/item/generation;
- законченный текст до downstream;
- session reuse;
- в D75 — formulation и semantic judge в одной сессии.

Текущий draft намеренно отличается: **одно соединение на операцию**, закрытие после turn, без переноса provider history. Это ограничение памяти/ownership, не установленная причина `nontext_session`.

## K. HISTORICAL SESSION PAYLOADS

| Путь | Реальный запрос |
|---|---|
| Qwen tool smoke | `session.modalities=["text"]`, затем text operation |
| Qwen conversational voice | `session.modalities=["text","audio"]`, PCM, voice, VAD |
| Yandex conversational voice | `session.output_modalities=["audio"]`, nested audio configuration, 44 100 Hz, `dasha`, `ru-RU`, server VAD |
| Исторический Yandex text presenter | `session.output_modalities=["text"]`; user `input_text`; `response.output_modalities=["text"]` |
| Текущий Level-0 | Те же text intent поля, но новая строгая проверка возвращённого session field |

Точные исторические symbols:

- `4e8b49a:orion/qwen_live_audio_core.py:419` — `_audio_session_update`.
- `6a4c5d5:orion/yandex_realtime_provider.py:58` — `yandex_session_update`.
- `9ed45bb:orion/yandex_realtime_provider.py:86` — `yandex_text_session_update`.
- `:101` — `yandex_text_request_events`.
- `9ed45bb:orion/yandex_realtime_informational_presenter.py:573` — принятие `session.updated` **без проверки равенства modalities**.

Исторические helpers применяли `.strip()`. Это не разрешение переносить преобразования finalized protected text.

## L. WHAT “TEXT-ONLY” ACTUALLY MEANT

Нужно разделять:

1. возможности серверной сессии;
2. запрошенную модальность конкретной операции;
3. владение аудио в ORION.

Для нынешнего conversational компонента существенны **текстовый вход/выход и отсутствие аудиовладения**. Из этого логически не следует обязательное буквальное серверное подтверждение `["text"]`.

Однако найденные records **не доказывают**, что старый успешный text presenter реально получал мультимодальный acknowledgement. Они сохраняют успешные текстовые операции, но не соответствующее точное поле.

Также:

- наличие `response.output_text.done` в раннем audio report — не доказательство text-only operation;
- отсутствие отправленного PCM можно доказать кодом;
- отсутствие нежелательной генерации audio при текущем контракте ещё нужно наблюдать;
- просто игнорировать audio events и объявить PASS нельзя.

## M. CURRENT nontext_session ROOT-CAUSE ASSESSMENT

[Сохранённый результат единственной пробы](C:/Users/Алексей/Documents/ORION-Builds/level0-conversation-20260908/provider-probe-result.json) показывает:

```text
connect → session.update requesting ["text"]
        → session.created → session.updated
        → local nontext_session → close
```

В [адаптере, строка 141](C:/Users/Алексей/Documents/GitHub/ORION-level0-conversation/orion/yandex_realtime_text_conversation.py:141) отклоняется всё, кроме отсутствующего/`None` значения или точного `["text"]`.

**Доказанная непосредственная причина:** локальный handshake predicate отклонил присутствовавшее значение поля.

**Не установлено:** точное значение, его тип и смысл; API drift; реальный отказ text operation.

- User items: **0**.
- `response.create`: **0**.
- Генерация, Core admission, TTS: не достигнуты.
- Сессия и WebSocket закрыты; owned tasks: 0.
- 1594 ms — failed handshake + cleanup, не latency ответа.
- Auth достаточен для получения session events; generation quota/billing этим не проверены.

Основная классификация: **D — insufficient evidence**. Неподтверждённое ORION handshake assumption — конкретный кандидат, но не окончательно доказанная provider-level причина.

## N. D75 RELATIONSHIP

D75 **не был происхождением свободного разговора**. Это более поздняя попытка безопасной natural formulation вокруг Core facts.

[Машинный benchmark IPB-20260903-221854](C:/Users/Алексей/AppData/Local/ORION/development/presentation-benchmarks/IPB-20260903-221854.json) подтверждает:

- 80/80 accepted primary samples;
- 0 observed unsafe acceptances;
- persistent reuse;
- text formulation и semantic validation;
- verdict **SEMANTIC_NUMERICAL_GO_ONLY**, не универсальную гарантию.

Старый structural-only вариант пропускал дополнительные утверждения вокруг правильно подставленного aircraft marker. Следовательно, **точная подстановка одного факта не гарантирует безопасность всей фразы**.

В текущий Level-0 не следует автоматически переносить D75 judge, расширенный фактический контекст или persistent lifecycle.

## O. CONVERSATIONAL MEMORY / CONTEXT HISTORY

- Ранний `VoiceContext`: предмет разговора, callsign/unit, последний intent; не LLM conversational memory.
- Qwen/Yandex speech sessions: непрерывный provider conversation context внутри соединения.
- Долговременная «Crew Relationship» обсуждалась 5 августа, но её реализация этой историей не доказана.
- D75: formulation/judge использовали общую warm session; очистка истории между операциями не установлена как обязательный механизм.
- Level-0: request-scoped connection исключает обычный перенос истории через повторное использование сессии.

Посторонние реплики и повторения подтверждены пользователем. Но для каждого случая нельзя задним числом выбрать единственную причину между echo/VAD, контекстом и генерацией без соответствующего evidence.

## P. DCS CONTEXT / AUTHORITY HISTORY

Ранний чистый conversational voice мог работать **без DCS facts и без SRS**.

Поздний Stage 6A передавал фактический FlightContext модели. Это обеспечивало authoritative input, но не гарантировало authoritative output. Пользовательские ошибки координат/значений относятся именно к этой существенной границе.

Современная recovery-линия сохраняет:

- ToolGateway / WorldModel как источник фактов;
- intent-specific selection;
- typed semantic object;
- protected presentation;
- запрет raw ToolResult / telemetry dump → speech.

Отдельный remembered MODEL C incident не отождествлён со Stage 6A и не объявлен несуществовавшим.

**Зависимость свободной беседы от старого RadioInfo/SRS lifecycle не обнаружена.** Для воспроизведения conversational содержания поверх текущего voice baseline старую SRS архитектуру переносить не требуется.

## Q. LATENCY HISTORY

| Источник | Что измерено / сообщено | Ограничение |
|---|---|---|
| Qwen, 19 августа | Пользователь: примерно 6–10 секунд, заикания | Субъективные оценки конкретных неустойчивых сборок |
| Yandex tester, первая точная пара | 1015 ms от provider speech-stopped до первого audio delta | Не physical PTT END; не первый услышанный звук |
| `IPB-20260903-203229` | Warm text complete median 342,461 ms, p90 492,878 ms | 10% primary validation failures |
| `IPB-20260903-221854` | Warm formulation+validation total median 1110,625 ms; validation median 766,911 ms | Без STT/TTS/SRS, numerical gate only |
| Текущий Level-0 | 1594 ms failed handshake + cleanup | Ответ не генерировался |

Переносить warm benchmark latency на cold request-scoped Level-0 нельзя.

## R. BEST HISTORICAL CONVERSATION CHECKPOINT

**Лучший ранний пользовательски принятый conversational checkpoint:**

`4e8b49afff0b8f5d1ec1a008f09f79ae08e1a546` — **Build #402**, 20.08.2026.

Код:

- `orion/qwen_live_audio_core.py:419` — session configuration;
- `:990` — `_run_transport`;
- `:1227` — `_run`;
- `response.audio.delta` и reference FIFO playback.

Подтверждение: пользовательское сообщение `75bb1360-abf4-4cac-91ab-c3632375d49b`; contemporaneous фиксация `cbd3463abdeef1a769f99abff84821d414496dad`.

Это эталон **работавшей ранней беседы**, не кандидат на буквальный откат современного SRS/voice stack.

Для **текстовой transport operation** более релевантен `9ed45bb`/`8182e892` плюс сохранённые IPB reports. Одного исторического checkpoint, одновременно доказывающего все нынешние Level-0 constraints, не найдено.

## S. HISTORICAL REUSE MAP

| Источник | Repository confirmation | Классификация / следствие |
|---|---|---|
| Data Export: свободное общение с 5 августа | `3aef774` подтверждает только раннюю fixed implementation | **CONCEPT ONLY** для широкой беседы |
| DCS Changelog Watch: #402 принят | `4e8b49a`, `cbd3463`, ADR-005 / Project Memory | **CONCEPT ONLY** для текущей интеграции; не переносить audio owner |
| «Исправить SRS RadioInfo в ORION» | `1a06a09`, ADR-007; rollout строка 275 | **DO NOT USE** как новую миграцию: SRS baseline уже существует |
| `ORION_PROJECT_MEMORY.md`, ADR-004/005/006 | Соответствующие августовские commits | Использовать исторический rationale, не как замену current code |
| Yandex URL/auth helpers | Уже присутствуют в recovery | **COPY/REUSE** существующих symbols |
| Text session/item/response helpers | `9ed45bb`, `8182e892` | **ADAPT** после наблюдения текущего handshake; без `.strip()` finalized text |
| Response correlation / terminal assembly | Исторический presenter | **ADAPT** под bounded turn ownership |
| Persistent formulation + judge | D75 code и benchmarks | **DO NOT USE** в минимальном Level-0 |
| FlightContext → model → direct audio | Stage 6A | **DO NOT USE**: не обеспечивает нынешнюю output authority |
| Frozen STT/TTS/RadioRouter/SRS | Текущий recovery baseline | Сохранить без изменений |

Разговорные утверждения без repository/field подтверждения оставлены **CHAT-ONLY / NOT CONFIRMED**, особенно долговременная память и полная conversational competence.

## T. CURRENT LEVEL-0 MODULE REVIEW

| Модуль | Решение аудита |
|---|---|
| `conversational_contracts.py` | **KEEP**: typed request/candidate/finalized distinction, UUID/hash/deadline, отсутствие fact/tool authority |
| `conversational_core.py` | **KEEP как bounded MVP**: закрытый язык admission, не универсальная безопасность свободной прозы |
| `yandex_realtime_text_conversation.py` | **ADAPT после prerequisite proof**: handshake predicate не подтверждён сохранённым provider contract |
| `conversational_presentation.py` | **KEEP как unwired draft**: повторное использование protected streaming mechanics, не новый radio stack |
| Offline tests | **KEEP**, но не считать provider/field proof |

Дополнительные статические ограничения:

- финальный `response.done.output` проверяется на типы, но полного сравнения его текста с ранее собранным terminal text нет;
- сохранение текстовых observer events должно оставаться ограниченным explicit evidence mode при будущей интеграции;
- закрытая admission grammar допускает только узкий social-support slice, не общий разговор;
- live generation, разнообразие ответов и production lifecycle нового owner не доказаны.

Ничего из этого сейчас не исправлялось.

## U. PRESENTATION POLICY

Зафиксирована заданная пользователем политика:

**Authoritative source labels silent by default.**

Внутренние provenance, freshness, authority и binding остаются обязательными. Их не нужно автоматически озвучивать.

Точная нынешняя точка будущего изменения: [render_informational](C:/Users/Алексей/Documents/GitHub/ORION-level0-conversation/orion/hybrid_aircraft_core.py:175), текстовый префикс на строке 183.

Сейчас строка не изменена.

## V. FUTURE conversation + Core fact

Для будущего «Как дела? И какой у меня самолёт?» минимальная граница:

```text
social part → отдельный bounded conversational candidate → admission
fact part   → ToolGateway → authoritative typed aircraft result
                         ↓
              локальная композиция Core
                         ↓
                 finalized text → TTS
```

Conversational backend не получает aircraft value и не формулирует фактическую часть. Это направление дальнейшего bounded slice, **не выполненная интеграция и не причина расширять текущий handshake tranche**.

## W. THREE-ARCHITECTURE COMPARISON

| Свойство | Ранний working conversation | D75 | Текущий Level-0 draft |
|---|---|---|---|
| Назначение | Свободный speech-to-speech | Natural informational formulation | Узкий social-support ответ |
| Audio generation | Realtime provider | Отдельный downstream | Существующий SpeechKit |
| Session | Persistent | Persistent formulation + judge | На одну операцию |
| DCS facts | Сначала отсутствуют; позже FlightContext | Bounded authoritative context | Запрещены |
| Output admission | Ранняя линия без нынешних гарантий | Semantic validation + binding | Positive closed grammar |
| Фактическое доказательство | User-confirmed voice | Provider benchmarks, ограниченные verdicts | Offline + failed handshake |
| Перенос целиком | Нет | Нет | Ещё не готов к интеграции |

## X. DECISION TREE

1. **Работала ли генеративная свободная беседа физически? — YES.** Qwen #389; лучший принятый ранний baseline #402.
2. **Требовала ли она provider-owned audio? — YES для доказанного раннего speech-to-speech пути.** Это не доказательство необходимости такого устройства будущего Level-0.
3. **Требовала ли буквально text-only session? — NO.** Ранний voice path явно audio-enabled.
4. **Доказана ли multimodal session + отдельная text operation? — UNKNOWN** в смысле точного серверного acknowledgement. Text operations доказаны; фактическая возвращённая modality declaration не сохранена.
5. **Классификация `nontext_session` — D: insufficient evidence.** Прямая точка отказа доказана, provider-level причина — нет.
6. **Продолжать от существующих Level-0 contracts? — PARTIAL.** Сохранить bounded contracts и authority boundary; transport handshake ещё требует доказательства.
7. **Минимальный следующий tranche — Option A: Yandex Realtime handshake recovery only.**

## Y. RECOMMENDED NEXT TRANCHE

**Выбран только Option A.** Не смена backend, не восстановление старого audio runtime и не redesign.

После отдельной авторизации — одна изолированная protocol probe:

- одна connection;
- один exact synthetic input: `Что-то сегодня полёт тяжело идёт.`;
- один `conversation.item.create` с исходным `input_text`;
- один `response.create`, запрашивающий `output_modalities=["text"]`;
- сохранить presence/type/exact value относящихся к capabilities полей `session.created` и `session.updated`, включая `modalities`, `output_modalities`, session type и audio/turn-detection configuration, если возвращены;
- не сохранять secrets, headers или полный необработанный provider body;
- сохранить точный текстовый terminal result, response identity/status и факт появления либо отсутствия audio/tool/VAD events;
- не отправлять PCM, не открывать устройства, не подключать TTS/SRS/DCS;
- unexpected audio output — отдельный failure, без воспроизведения и без объявления успеха через игнорирование;
- bounded close и проверка отсутствия оставшихся owned tasks;
- никаких автоматических повторов или дополнительных provider experiments.

Она должна установить недостающий контракт. Одна успешная операция ещё не докажет всю разговорную вариативность или field readiness.

## Z. FINAL VERDICT

Воспоминание о раннем свободном разговоре подтверждено первичными пользовательскими сообщениями, кодом и сохранёнными generative diagnostics. Полный Data Export найден и проверен; он существенно дополнил отдельный DCS HTML.

Но историческая работа text generation не восстанавливает утраченное значение текущего handshake. Оснований сейчас исправлять predicate вслепую, переносить старый voice stack или менять backend нет.

Аудит завершён без изменений и без новых live действий.

EARLY CONVERSATION HISTORY DOES NOT RESOLVE CURRENT PROVIDER CONTRACT — TARGETED PROTOCOL PROBE REQUIRED
