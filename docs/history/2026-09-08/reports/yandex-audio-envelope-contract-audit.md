ORION ARCHITECTURE GUARD: OFF

### A. BASELINE / EVIDENCE VERIFIED

HEAD подтверждён: `dca668d530dc6cbc4de05064400b22c2216ada3f`.

[Сохранённый результат пробы](/C:/Users/Алексей/Documents/ORION-Builds/yandex-realtime-text-protocol-probe-20260908/provider-protocol-result.json) соответствует ожидаемому SHA-256:

```text
C45012C772FBB45D5B5B1C0B30135401548046D08A5127980B7A90A1088E6DAD
```

Прочитаны harness, его тесты, текущий draft-адаптер и указанные исторические реализации. Повторная проверка **727 файлов: изменений нет**. Tracked diff пуст; семь untracked-файлов сохранены.

**Главный результат:** audio terminal marker не доказывает получение звуковых байтов. Но сохранённый harness также не позволяет доказать отсутствие байтов во всех предусмотренных схемой полях. Дополнительно обнаружен конфликт между официальным справочником, официальными примерами и фактически полученными событиями.

### B. OFFICIAL DOCUMENTATION SOURCES

Дата доступа ко всем источникам: **2026-09-08**. Видимая дата обновления/номер редакции рассмотренных страниц не найдены. Дату индексации поисковой системы за дату документации не принимал.

| Официальный источник | Назначение / версия |
|---|---|
| [REST: session.update](https://aistudio.yandex.ru/en/docs/ai-studio/clientEvents/realtimeSessionUpdate) | Обновление effective session configuration |
| [REST: response.create](https://aistudio.yandex.ru/en/docs/ai-studio/clientEvents/realtimeResponseCreate) | Session defaults и per-response overrides |
| [Creating a voice agent with text responses](https://aistudio.yandex.ru/en/docs/ai-studio/operations/agents/voice-text-agent) | Официальный `["text"]` пример; модель `speech-realtime-250923` |
| [Creating a voice agent](https://aistudio.yandex.ru/en/docs/ai-studio/operations/agents/create-voice-agent) | Реальное получение audio через `output_audio.delta` |
| [Realtime API format update](https://aistudio.yandex.ru/en/docs/ai-studio/concepts/agents/realtime-changes) | Прекращение старого формата **12 мая 2026** |
| [REST: Server events](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/) | Справочник событий; отдельные страницы приведены в E |

Важный конфликт: справочник помечает `output_text.delta`, `output_text.done`, `output_audio.delta` и `output_audio.done` как неподдерживаемые. Официальные примеры используют соответствующие text/audio delta, а сохранённая проба получила text delta/done и audio done. Это не позволяет считать пометки справочника достоверным описанием фактически работающего набора событий.

### C. CURRENT YANDEX SESSION MODALITY SEMANTICS

Согласно документации:

- `session.created` содержит конфигурацию по умолчанию.
- `session.update` изменяет переданные поля.
- `session.updated` представляет полную **effective configuration**, а не просто каталог возможностей модели. [Session created](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerSessionCreated), [session.update](https://aistudio.yandex.ru/en/docs/ai-studio/clientEvents/realtimeSessionUpdate).

Поэтому называть возвращённое `output_modalities=["text","audio"]` **только capability advertisement** нельзя.

`["text"]` официально используется для текстового output. Однако объяснение, почему после такого update effective configuration продолжает содержать обе модальности, — **NOT DOCUMENTED / NOT FOUND**. Обязательная мультимодальность сессии и нормализация acknowledgement обратно в обе модальности также не найдены. [Текстовый пример](https://aistudio.yandex.ru/en/docs/ai-studio/operations/agents/voice-text-agent).

Вложенный `server_vad` относится к обработке audio input; его наличие в defaults не означает, что ORION отправлял звук или владел микрофоном.

### D. CURRENT YANDEX RESPONSE MODALITY SEMANTICS

`response.create.response` — необязательные настройки конкретного ответа; без них используются session defaults. Документация прямо включает modalities в перечень возможных overrides. [Response create](https://aistudio.yandex.ru/en/docs/ai-studio/clientEvents/realtimeResponseCreate).

Но схема оставляет `response` общим объектом: подробное правило обработки `output_modalities=["text"]` и возвращаемого acknowledgement не раскрыто.

`response.created` означает начало генерации, статус `in_progress`. Его `output_modalities` описаны как модальности результата, но **это не доказательство уже полученных непустых audio bytes**. [Response created](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerResponseCreated).

Ответы на конкретные вопросы:

- Text-only output предусмотрен: **да**, официальный пример существует.
- Per-response modality override предусмотрен: **да**, на уровне общего контракта.
- Точный text-only override внутри возвращаемого мультимодального envelope гарантирован: **не установлено**.
- Audio обязательно неявно сопровождается текстовым transcript: **не установлено**; схема описывает transcript как условный.
- Сервер обязан сохранять обе модальности при text-only операции: **NOT DOCUMENTED / NOT FOUND**.

### E. EVENT SEMANTICS TABLE

«Не требует audio» ниже означает, что событие само по себе не доказывает непустые звуковые байты. Это не утверждение об отсутствии внутренней генерации.

| Event / официальный источник | Определение | Payload-bearing? | Metadata / terminal | Требует непустое audio? | В пробе | Confidence |
|---|---|---|---|---|---:|---|
| [session.created](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerSessionCreated) | Создана сессия, defaults | Конфигурация | Metadata | Нет | 1 | HIGH |
| [session.updated](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerSessionUpdated) | Сессия обновлена | Конфигурация | Metadata | Нет | 1 | HIGH |
| [conversation.item.created](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerConversationItemCreated) | Создан conversation item, включая assistant | Возможно content | Item metadata/content | Нет | 3 | HIGH; повтор одного ID — не объяснён |
| [response.created](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerResponseCreated) | Начало ответа | Response object | Metadata | Нет | 1 | HIGH |
| [response.output_item.added](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerResponseOutputItemAdded) | Добавлен output item | Возможно content | Declaration | Нет | 1 | HIGH |
| [response.content_part.added](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerResponseContentPartAdded) | Добавлена часть assistant message | **Возможны text/audio поля** | Declaration, не обязательно только metadata | Нет | 2 | HIGH |
| [response.output_text.delta](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerResponseOutputTextDelta) | Обновление текста | Text delta | Streaming | Нет | 12 | HIGH по схеме; support-label конфликтует |
| [response.output_text.done](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerResponseOutputTextDone) | Завершение text part | Final text | Terminal | Нет | 1 | HIGH по схеме; support-label конфликтует |
| [response.content_part.done](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerResponseContentPartDone) | Завершение content part, также при прерывании | **Возможны text/audio поля** | Terminal + content | Нет | 2 | HIGH |
| [response.output_audio.done](https://aistudio.yandex.ru/docs/en/ai-studio/serverEvents/realtimeServerResponseOutputAudioDone.html) | Завершение audio output, также при cancellation/incomplete | **Нет audio bytes в схеме** | Audio terminal | Не доказывает | 1 | HIGH по форме; zero-payload semantics UNKNOWN |
| [response.output_audio_transcript.done](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerResponseOutputAudioTranscriptDone) | Завершение transcript выходного audio | **Transcript string, не PCM** | Transcript terminal | Не доказывает | 1 | HIGH по форме; placeholder semantics UNKNOWN |
| [response.output_item.done](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerResponseOutputItemDone) | Завершение output item | Возможно content | Terminal | Нет | 1 | HIGH |
| [response.done](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerResponseDone) | Завершён поток ответа; raw audio может отсутствовать | Output items/status | Response terminal | Нет | 1 | HIGH |
| [response.output_audio.delta](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerResponseOutputAudioDelta) | Обновление generated audio | **Base64 audio в `delta`** | Streaming payload | Непустой валидный delta доказывает bytes | **0** | HIGH по схеме; support-label конфликтует |

### F. AUDIO PAYLOAD PROOF STANDARD

Минимальное положительное доказательство получения audio bytes:

1. Непустое валидное Base64 audio в `response.output_audio.delta.delta`; **или**
2. Непустое валидное Base64 в `RealtimeOutputAudioPart.audio`.

Второй путь прямо предусмотрен схемой content part. Поэтому `output_audio.delta` — документированный payload-bearing event, **но не единственное описанное место хранения audio bytes**. [Audio delta](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerResponseOutputAudioDelta), [Output audio part](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerResponseContentPartDone).

**ACTUAL AUDIO PAYLOAD OBSERVED: UNKNOWN — для всех возможных полей совокупно.**

Точнее:

- Audio-delta events: доказан **ноль**.
- Положительного сохранённого свидетельства audio bytes: **нет**.
- Отсутствие bytes в остальных полях: **не доказано**.

Причина — [Trace.receive](/C:/Users/Алексей/Documents/ORION-Builds/yandex-realtime-text-protocol-probe-20260908/protocol_probe.py:111): harness не сохранял presence/type/length поля `part.audio`, содержимое output-item events и audio transcript. Проекции conversation/response content сохраняли тип и текст, но отбрасывали audio/transcript.

Отсутствие этих полей в сохранённой проекции **не означает**, что они отсутствовали в исходном событии. Их значения сейчас восстановить нельзя.

### G. ZERO-PAYLOAD AUDIO ENVELOPE — VALID OR NOT

**Как возможная структура — допустимо схемой; как гарантированный режим данного сервера — не подтверждено.**

Схема допускает `output_audio` с отсутствующим/null `audio`; `output_audio.done` вообще не содержит audio payload. Следовательно, наличие audio part или terminal marker нельзя автоматически приравнивать к звуковым байтам.

Но документация не определяет стандартный режим: «при text-only ответе сервер всегда создаёт пустую audio-ветвь». Такая интерпретация — **гипотеза**, не установленный контракт.

В частности, `content_part.added/done` нельзя без проверки содержимого объявлять исключительно envelope-событиями.

### H. CURRENT PROBE REINTERPRETATION

Доказано:

`input_text → 12 text delta → text done → response.done(completed)`

Точный текст, с начальным пробелом:

```text
 Понимаю, бывает такое. Надеюсь, дальше будет полегче!
```

Также доказаны audio declaration/terminal events и отсутствие audio-delta events.

Уточнение предыдущего отчёта: **«не сохранено/не декодировалось/не воспроизводилось» не равно «провайдер нигде не прислал bytes»**. Прежний verdict `FAIL_UNEXPECTED_OUTPUT` остаётся корректным относительно прежнего запрета любых audio-событий. Он не является доказательством фактической audio generation.

### I. session.updated ["text","audio"] DECISION

**UNKNOWN — разрешение игнорировать это расхождение не обосновано.**

Не следует считать такое значение доказательством audio payload. Но документация называет acknowledgement effective configuration, поэтому переобозначить его как безвредную capability metadata тоже нельзя. [Session update](https://aistudio.yandex.ru/en/docs/ai-studio/clientEvents/realtimeSessionUpdate).

Текущую production-проверку в этом аудите не ослаблять.

### J. response.created ["text","audio"] DECISION

**UNKNOWN — для автоматического production acceptance.**

Само начальное metadata не доказывает полученное audio. Однако возвращение обеих output modalities после text-only override не объяснено найденным контрактом. [Response create](https://aistudio.yandex.ru/en/docs/ai-studio/clientEvents/realtimeResponseCreate), [response created](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerResponseCreated).

### K. AUDIO EVENT DECISION TABLE

Решения относятся к будущему text-only parser; текущий код не меняется.

| Event | Если заявлен zero payload, принимать? | Почему | Production action |
|---|---|---|---|
| `content_part.added(output_audio)` | **UNKNOWN** | Part может содержать `audio`; пустая форма не объясняет выбор audio-ветви | Не добавлять безусловный ignore |
| `content_part.done(output_audio)` | **UNKNOWN** | Может содержать audio/transcript; значения пробы не сохранены | Не считать terminal автоматически пустым |
| `output_audio.done` | **UNKNOWN** | Сам marker не содержит bytes; документированный text-only placeholder не найден | Не приравнивать к PCM, но allowlist пока не расширять |
| `output_audio_transcript.done` | **UNKNOWN** | Это transcript channel, а не PCM; значение в evidence утрачено | Не использовать как альтернативный conversational текст |
| `output_audio.delta` | **REJECT** | Это предназначенный для audio payload канал; пустой delta также нарушает предлагаемый strict channel contract | Fail-closed без decode/playback |

Основания: определения и схемы из E–F. Это не рекомендация считать все audio-события одинаковыми: declaration, transcript и terminal требуют разных проверок.

### L. TEXT TERMINAL AUTHORITY

Для завершённого text part документирован `response.output_text.done.text`. Но событие может прийти и при interrupted/incomplete/cancelled response; значит, оно **не заменяет** проверку `response.done.status=="completed"`. [Text done](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerResponseOutputTextDone).

Для будущего parser необходимы:

- Один связанный text terminal.
- Точное совпадение склейки delta с terminal, без нормализации.
- Успешный terminal того же response.
- Если другие terminal-поля содержат текст того же part — отсутствие противоречия.

Документация разрешает `response.done` не включать raw audio. Она не объясняет исчезновение text part с сохранением только audio-shaped content в этой пробе. **Ожидаемая нормализация такого вида не установлена.** [Response done](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerResponseDone).

### M. ASSISTANT ITEM EVENTS

`conversation.item.created` официально допускает роли user, assistant и system. Поэтому blanket-проверка «любое такое событие должно быть user» **слишком строгая относительно общей схемы**. [Conversation item created](https://aistudio.yandex.ru/en/docs/ai-studio/serverEvents/realtimeServerConversationItemCreated).

Однако два `created` одного assistant item — сначала пустого, затем text+audio — отдельно документацией не объяснены. Нельзя автоматически разрешить любые повторные assistant items.

`output_audio_transcript.done` относится к transcript audio output, а `output_text.done` — к text part. В пробе это разные `content_index`: **1 и 0** одного item. Их наличие не доказывает две независимые генерации. Сравнить тексты нельзя: audio transcript не сохранён. Гипотеза стандартного пустого placeholder остаётся неподтверждённой.

### N. HISTORICAL 9ed45bb COMPARISON

Проверены точные commits:

- `9ed45bbd820e60784d83c357a248d3b95dae765a` — 2026-09-04 15:05:13 +03:00.
- `8182e892a951afe7f239f3f7f5a2231415c6d57d` — 2026-09-04 15:32:03 +03:00.

Релевантные presenter/provider/session файлы между ними одинаковы.

| Символ | Историческое поведение | Последствие |
|---|---|---|
| `yandex_text_session_update` | Запрашивал `["text"]` | Text intent был явным |
| `yandex_text_request_events` | Text item + response `["text"]` | Audio не запрашивал |
| `YandexRealtimeInformationalPresenter.connect` | Принимал `session.updated` без проверки modalities | Текущий acknowledgement прошёл бы |
| `RealtimeTextResponseAssembler.handle` | Обрабатывал text delta/done и response lifecycle; неотработанные audio events пропускал | Не доказывал zero audio payload |
| Тот же assembler | Принимал assistant item; применял `.strip()` и нормализованное сравнение | Не годится для буквального переноса в строгий контракт |
| Исторический voice session | Декодировал `output_audio.delta`; `audio.done` закрывал audio-поток | Payload и terminal были разными сущностями |

Скрытый риск старого text parser: unexpected audio bytes могли не попасть в playback, но само их получение **не отклонялось**. «Работал» не означает «выполнял нынешний zero-payload invariant».

### O. API DRIFT CLASSIFICATION

| Наблюдение | Классификация |
|---|---|
| Session defaults и per-response overrides | **CONFIRMED CURRENT API SEMANTICS** |
| `audio.done` отличается от bytes; content part может содержать audio | **CONFIRMED CURRENT API SEMANTICS** |
| Прежний parser доверял text request и игнорировал прочие события | **ORION HISTORICAL PARSER ASSUMPTION** |
| Почему acknowledgement остаётся text+audio | **UNKNOWN** |
| Почему некоторые реально полученные события помечены unsupported | **UNKNOWN; подтверждён documentation/evidence conflict** |
| Почему terminal output содержит только audio-shaped part | **UNKNOWN** |
| Изменение этих правил между сентябрьскими checkpoints | **CONFIRMED API DRIFT не установлен** |

Официальная миграция формата до 12 мая 2026 подтверждена, но не объясняет автоматически текущий сентябрьский случай. [Format update](https://aistudio.yandex.ru/en/docs/ai-studio/concepts/agents/realtime-changes).

### P. CURRENT ADAPTER CHECKS REVIEW

Все проверки находятся в `TextConversationProvider.generate`.

| Проверка | Классификация | Обоснование |
|---|---|---|
| [nontext_session](/C:/Users/Алексей/Documents/GitHub/ORION-level0-conversation/orion/yandex_realtime_text_conversation.py:142) | **UNKNOWN** | Effective-config mismatch реален; безопасное толкование широкого ACK не установлено |
| [unexpected_item](/C:/Users/Алексей/Documents/GitHub/ORION-level0-conversation/orion/yandex_realtime_text_conversation.py:170) | **TOO STRICT** | Общая схема допускает assistant; разрешение конкретных повторов требует correlation |
| [nontext_output](/C:/Users/Алексей/Documents/GitHub/ORION-level0-conversation/orion/yandex_realtime_text_conversation.py:185) | **CORRECT AS-IS** для non-message/tool items; **CORRECT PRINCIPLE / WRONG EVENT** для доказательства audio bytes по типу part | Audio declaration не равна payload; это ещё не основание разрешить её |
| [nontext_terminal](/C:/Users/Алексей/Documents/GitHub/ORION-level0-conversation/orion/yandex_realtime_text_conversation.py:214) | **CORRECT PRINCIPLE / WRONG EVENT** как byte-detector | Terminal shape может не содержать raw audio даже у audio response; безопасный accept остаётся UNKNOWN |

Ни одна строка не изменена.

### Q. SAFE FUTURE PROTOCOL CONTRACT

**Production-usable acceptance contract для наблюдённого envelope пока не утверждён.**

Если провайдер подтвердит нужную семантику, минимальные инварианты для отдельной коррекции:

- Только точный `input_text`, явный text-only response request.
- Одна операция; проверенная привязка response/item/output/content IDs.
- Один text terminal, без дубликатов и перестановки частей.
- Exact delta-to-terminal equality, без `.strip()`/переписывания.
- Только `response.done(completed)` разрешает выдачу candidate.
- Запрет audio-delta channels **и непустого audio во всех content/item полях**.
- Запрет tool/function output и неизвестных payload-bearing форм.
- Никакого provider playback, microphone ownership или прямой передачи ответа в SpeechKit до Core admission.
- Поздние данные не допускаются в завершённый candidate; lifecycle не принимает второй ответ.

Allowlist пустых audio markers зависит от ответа на документационный вопрос, а не от предположения.

### R. PROTOCOL SAFETY VS SEMANTIC SAFETY

**Protocol safety:** если marker действительно пуст и никуда не передаётся как речь, сам по себе он не даёт провайдеру authority, микрофон или playback. Но отсутствие playback не доказывает отсутствие полученных/сгенерированных bytes.

**Semantic safety:** корректный text-only transport не гарантирует допустимое содержание. Core admission, no-authority ограничения и SpeechKit-only spoken output остаются отдельными требованиями.

Отклонение обычного probe text вместо `SocialDraft` не является protocol failure. Исторические подтверждения generative conversation не пересматриваются.

Политика **AUTHORITATIVE SOURCE LABELS ARE SILENT BY DEFAULT** сохранена; presentation code не менялся.

### S. LATENCY CONTEXT

Сохранённые **297 мс до первого текста / 500 мс до завершения текста** относятся только к provider response. Это не end-to-end voice latency и не аргумент для ослабления контракта. Оптимизация не выполнялась.

### T. CHANGE AUDIT

- Новых Realtime/provider вызовов: **0**.
- Probe и тесты повторно не запускались.
- Изменений файлов, конфигурации и Git: **0**.
- Build/install/DCS/SRS/PTT/audio testing: **0**.
- Credentials и заголовки не читались для аутентификации и не публиковались.
- Сохранённое evidence неизменно; его hash повторно подтверждён.

Сетевые обращения ограничены разрешённой проверкой документации.

### U. RECOMMENDED NEXT TRANCHE

**Одно адресное уточнение у Yandex по контракту модели `speech-realtime-260528`**, с использованием уже существующих session/response IDs. Без нового эксперимента и без backend-selection audit.

Обращение в поддержку в рамках этого задания не отправлялось.

### V. EXACT FUTURE DIFF BOUNDARY

**Исправление сейчас не обосновано.**

Если уточнение подтвердит text-only operation в таком envelope, потенциальная граница — только `TextConversationProvider.generate` в `yandex_realtime_text_conversation.py` и соответствующие offline parser tests.

Перенос старого presenter целиком, изменения Router/Core/STT/TTS/SRS/Launcher/STOP не требуются этим аудитом и не разрешены.

### W. OPEN DOCUMENTATION GAPS

Один объединённый вопрос провайдеру:

> Для `speech-realtime-260528`, session `4a11ff2e5d7a`, response `resp_3d259f4f9f4d4806b03c0792a9b64fbb`: после session/response `output_modalities=["text"]` сервер вернул `["text","audio"]`, text delta/done, audio part/done и audio-transcript.done без audio-delta events. Является ли эта последовательность штатным text-only ответом без audio generation/delivery? Если да, какие поля гарантированно пусты, может ли audio передаваться через `part.audio`/item content, и какой terminal text contract действует при audio-only форме `response.done.output`?

Это также должно прояснить конфликт support-labels и фактического протокола. Отсутствующие `part.audio`/transcript значения исходной пробы из сохранённой проекции восстановить невозможно.

### X. CURRENT STATUS

Text generation доказана. Provider audio ownership у ORION не возникало. **Ноль audio delta доказан; ноль audio payload по всем полям — нет.**

Нет оснований объявить text-only API невозможным или сменить backend. Также нет достаточного основания разрешить наблюдённый envelope в production.

### Y. DECISION OPTION

**OPTION E — Current evidence/docs conflict and require provider support clarification.**

Это один узкий contract blocker, не повод для новой архитектуры или серии live-проб.

### Z. FINAL VERDICT

YANDEX DOCUMENTATION / OBSERVED PROTOCOL CONFLICT — PROVIDER CLARIFICATION REQUIRED