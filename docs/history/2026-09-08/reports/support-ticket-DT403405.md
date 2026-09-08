ORION ARCHITECTURE GUARD: OFF

### A. SUPPORT CHANNEL USED

Официальный Yandex Cloud Support Center.

### B. TICKET SUBJECT

`Yandex Realtime API — output_modalities=["text"] returns multimodal response`

### C. TICKET / REQUEST ID

[**DT403405 — открыть обращение**](https://center.yandex.cloud/support/tickets/DT403405).

### D. SUBMISSION TIMESTAMP

Нажатие отправки: **08.09.2026, 23:22:43.647 Moscow (+03:00)**. Серверная карточка подтверждает создание **08.09.2026 в 23:22**; секунды интерфейс не показывает.

### E. PRODUCT / CATEGORY

**Yandex AI Studio → Вопрос.** Видимость: «Доступно только мне».

### F. MESSAGE SENT

Отправлен следующий текст; редактор преобразовал Markdown-разметку в форматирование:

Здравствуйте.

Нужна консультация по фактическому контракту Yandex Realtime API для модели `speech-realtime-260528`.

Endpoint:\
`wss://ai.api.cloud.yandex.net/v1/realtime`

Session ID:\
`4a11ff2e5d7a`

Response ID:\
`resp_3d259f4f9f4d4806b03c0792a9b64fbb`

В контролируемой сессии клиент отправил `session.update` с `output_modalities=["text"]`.

Затем был отправлен только `conversation.item.create` с `input_text`. Audio input не отправлялся.

После этого клиент отправил `response.create` также с `output_modalities=["text"]`.

При этом сервер в `session.created/session.updated` вернул `output_modalities=["text","audio"]`, а `response.created` также содержал `["text","audio"]`.

Текстовый ответ успешно был получен через `response.output_text.delta` и `response.output_text.done`.

Одновременно сервер прислал audio-related события:

- `response.content_part.added` для audio;
- `response.content_part.done` для audio;
- `response.output_audio.done`;
- `response.output_audio_transcript.done`.

Событий `response.output_audio.delta` получено не было.

Важно: наш диагностический лог не сохранял все возможные значения `part.audio`/audio content, поэтому мы не утверждаем, что audio bytes точно отсутствовали во всех полях.

Просим уточнить:

1. Является ли такая последовательность штатным поведением для text-only операции внутри мультимодальной Realtime-сессии?
2. Почему после запроса `output_modalities=["text"]` сервер возвращает `["text","audio"]` в `session.updated` и `response.created`?
3. Означают ли перечисленные audio-related events фактическую генерацию audio, или они могут быть структурными/terminal событиями с пустым audio payload?
4. В каких именно событиях/полях может находиться фактический generated audio payload: только `response.output_audio.delta` или также `part.audio` / item-content audio fields?
5. Достаточно ли отсутствия `response.output_audio.delta`, чтобы считать, что audio payload не передавался?
6. Как для модели `speech-realtime-260528` гарантированно выполнить text input → text output без generated audio payload?
7. Поддерживается ли буквально text-only session, или session остаётся multimodal, а модальность должна ограничиваться на уровне отдельного response?
8. Какой event является authoritative terminal contract для текста: `response.output_text.done`, `response.done.output` или необходимо проверять оба?
9. Почему `response.done.output` может содержать audio-shaped content при одновременно успешно полученном `response.output_text.done`?
10. В актуальном event reference некоторые реально наблюдаемые и используемые в официальных примерах text/audio delta/done events отмечены как unsupported. Какой контракт следует считать актуальным для `speech-realtime-260528`?

Если возможно, просим проверить на стороне сервера указанные Session ID и Response ID и подтвердить, генерировался или передавался ли для этого response непустой audio payload.

Наша задача — использовать Yandex Realtime только как text conversational backend. Распознавание и синтез речи выполняются отдельно, поэтому нам важно гарантированно исключить получение generated audio payload.

Спасибо.

### G. ATTACHMENTS

**Нет.** Скриншот, файлы evidence и секреты не отправлялись.

### H. CURRENT STATUS

**Открыт.** Получено автоматическое подтверждение: «Обращение DT403405 успешно создано».

Инженерного разъяснения пока нет. Второе обращение не создавалось; ожидание ответа циклически не выполнялось.

### I. USER ACTION REQUIRED

Не требуется.

### J. ORION CHANGE AUDIT
```
production code changed = NO
Git changed = NO
provider probe performed = NO
DCS/SRS/PTT performed = NO
```

### K. FINAL VERDICT

YANDEX SUPPORT REQUEST SUBMITTED — AWAITING PROVIDER CLARIFICATION
