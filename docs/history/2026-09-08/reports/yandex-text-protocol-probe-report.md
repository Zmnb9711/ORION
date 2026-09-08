ORION ARCHITECTURE GUARD: OFF

**Единственный разрешённый запрос выполнен. Текстовый ответ получен, но строгий контракт «никаких audio-событий» не подтверждён. Production не изменён; повторных запросов не было.**

### A. BASELINE / WORKTREE STATE

Проверена рабочая копия `C:\Users\Алексей\Documents\GitHub\ORION-level0-conversation`.

- HEAD: `dca668d530dc6cbc4de05064400b22c2216ada3f`.
- Field-runtime checkpoint: `f0c9e364ed653e9497d7e2ef8ef8f35dc97157d4`.
- Tracked diff пуст до и после.
- Семь ранее существовавших untracked-файлов сохранены без изменений.
- Сверка содержимого **727 файлов**, HEAD/status и конфигурации `cloud-voice.json`: **unchanged**.

### B. PREVIOUS nontext\_session RECONSTRUCTION

Предыдущий [provider-probe-result.json](C:/Users/Алексей/Documents/ORION-Builds/level0-conversation-20260908/provider-probe-result.json) фиксировал:

`session.created → session.updated → nontext_session → cleanup`

Пользовательский текст и `response.create` тогда не отправлялись. Точное значение прежнего acknowledgement не сохранялось.

В текущем адаптере проверка `output_modalities not in (None, ["text"])` вызывает `nontext_session`. Полученное **сейчас** значение `["text","audio"]` удовлетворяет этому условию. Это объясняет механизм отказа, но не восстанавливает отсутствующее поле предыдущего запуска.

### C. PROBE HARNESS

Создан изолированный [protocol\_probe.py](C:/Users/Алексей/Documents/ORION-Builds/yandex-realtime-text-protocol-probe-20260908/protocol_probe.py), вне репозитория.

Использованы существующие построение Yandex URL, auth helper и Windows Credential Manager. Конфигурация только прочитана.

Ограничения: одна сессия, без retry/reconnect; deadline 15 секунд и отдельный cleanup budget 1 секунда; ограниченные размеры сообщений, количества событий и текста. Audio payload не сохранялся, не декодировался и не воспроизводился.

### D. OFFLINE HARNESS CHARACTERIZATION

**10 тестов — PASS до обращения к провайдеру.**

Проверены:

- Различение missing / null / пустого массива / текстовых и мультимодальных значений / неверных типов.
- Безопасная проекция полей и редактирование секретов.
- Audio/tool/VAD-счётчики.
- Сохранение пробелов в тексте.
- Единственный text-only outbound без tools/audio.
- Продолжение после мультимодального acknowledgement.
- Остановка при session/item error.
- Невозможность PASS при audio-событии.
- Закрытие ресурсов.

Тесты: [test\_protocol\_probe.py](C:/Users/Алексей/Documents/ORION-Builds/yandex-realtime-text-protocol-probe-20260908/test_protocol_probe.py).

### E. LIVE PROBE AUTHORIZATION USED

Использовано ровно одно разрешённое соединение:

- Время записи результата: **2026-09-08 22:49:15 Moscow**.
- Endpoint: `wss://ai.api.cloud.yandex.net/v1/realtime`.
- Настроенная модель: `speech-realtime-260528`.
- Session ID: `4a11ff2e5d7a`.
- Response ID: `resp_3d259f4f9f4d4806b03c0792a9b64fbb`.
- Retry/reconnect: **0 / 0**.

Ошибок auth, billing/quota или provider error в этой сессии не наблюдалось.

### F. EXACT session.created

Ниже — точные сохранённые значения релевантных полей; это безопасная проекция, не полный raw provider body.

| Поле`session.created`                                    |                                     |
| -------------------------------------------------------- | ----------------------------------- |
| `id`                                                     | `"4a11ff2e5d7a"`                    |
| `type` / `object`                                        | `"realtime"` / `"realtime.session"` |
| `modalities`                                             | отсутствует                         |
| `output_modalities`                                      | `["text","audio"]`                  |
| `instructions`                                           | присутствует, `null`                |
| `tools`                                                  | `[]`                                |
| `model`, `tool_choice`                                   | отсутствуют                         |
| Верхнеуровневые `voice`, `turn_detection`, audio formats | отсутствуют                         |
| `version`, `protocol_version`, `api_version`             | отсутствуют                         |

Вложенный `audio`:
```
{
  "input": {
    "format": {"type": "audio/pcm", "rate": null},
    "turn_detection": {
      "type": "server_vad",
      "silence_duration_ms": 800,
      "threshold": null,
      "idle_timeout_ms": null,
      "yc_idle_llm_message": null
    },
    "languages": null
  },
  "output": {
    "format": {"type": "audio/pcm", "rate": null},
    "speed": null,
    "voice": "kirill",
    "role": null
  }
}
```

### G. EXACT session.update SENT
```
{
  "type": "session.update",
  "event_id": "probe-session-6ab606862ea6470294188fe935a54707",
  "session": {
    "instructions": "Respond briefly in Russian to the user's subjective remark. Return text only. No tools, factual claims or operational advice.",
    "output_modalities": ["text"]
  }
}
```

### H. EXACT session.updated

Релевантные поля совпали с разделом F, кроме `instructions`: вместо `null` получена строка; её входящее содержимое не сохранялось.

Ключевой результат:
```
"output_modalities": ["text", "audio"]
```

Провайдер не подтвердил сужение session output до `["text"]`. `tools` осталось `[]`, вложенный audio/VAD/default voice сохранился.

### I. SESSION CAPABILITY INTERPRETATION

Session metadata показывает мультимодальную конфигурацию. ORION в этом запросе не настраивал audio/VAD/voice.

Само наличие этих defaults ещё не доказывает генерацию аудио. Однако последующие audio-события означают, что строгий **operation-level zero-audio-event** контракт также не доказан.

| BoundaryOutboundInbound: релевантные поляРезультат |                                       |                                        |                              |
| -------------------------------------------------- | ------------------------------------- | -------------------------------------- | ---------------------------- |
| Создание сессии                                    | Connect                               | `output_modalities=["text","audio"]`   | Сессия создана               |
| Обновление                                         | `["text"]`                            | `["text","audio"]`                     | Сужение не подтверждено      |
| User item                                          | Один `input_text`                     | Тот же текст, user, completed          | Принят                       |
| Генерация                                          | `response.output_modalities=["text"]` | `response.created`: `["text","audio"]` | Начата                       |
| Text terminal                                      | —                                     | Непустой `output_text.done`            | Текст получен                |
| Audio boundary                                     | Audio не запрошено                    | Audio done/transcript done             | Строгий контракт не выполнен |
| Response terminal                                  | —                                     | `status=completed`                     | Нормальный terminal          |

### J. TEXT USER ITEM

Точная отправка:
```
{
  "type": "conversation.item.create",
  "event_id": "probe-input-6ab606862ea6470294188fe935a54707",
  "item": {
    "type": "message",
    "object": "realtime.item",
    "role": "user",
    "content": [
      {
        "type": "input_text",
        "text": "Что-то сегодня полёт тяжело идёт."
      }
    ]
  }
}
```

До `response.create` получено подтверждение принятия с точным совпадением текста. Нормализации, `.strip()` или переписывания не было.

### K. response.create
```
{
  "type": "response.create",
  "event_id": "probe-response-6ab606862ea6470294188fe935a54707",
  "response": {
    "instructions": "Respond briefly in Russian to the user's subjective remark. Return text only. No tools, factual claims or operational advice.",
    "output_modalities": ["text"]
  }
}
```

Отправлено ровно один раз.

### L. EVENT SEQUENCE

Полная последовательность типов, с объединением только 12 последовательных одинаковых событий:
```
01     session.created
02     session.updated
03     conversation.item.created        user
04     response.created
05     conversation.item.created        assistant, empty
06     conversation.item.created        assistant, text + audio
07     response.output_item.added
08     response.content_part.added      text
09     response.content_part.added      audio
10–21  response.output_text.delta       ×12
22     response.content_part.done       text
23     response.output_text.done
24     response.content_part.done       audio
25     response.output_audio.done
26     response.output_audio_transcript.done
27     response.output_item.done
28     response.done
```

Классификация harness: TEXT 13; AUDIO 5; TOOL 0; VAD/SPEECH 0; SESSION 2; ERROR 0; OTHER 8.

**AUDIO 5 — не пять PCM-фрагментов:** сюда входят terminal/content metadata.

### M. TEXT RESULT

Точный текст из `response.output_text.done`, включая **один начальный пробел**:
```
 Понимаю, бывает такое. Надеюсь, дальше будет полегче!
```

Склейка 12 delta совпала с terminal text. Ничего не обрезалось и не нормализовалось.

Особенность: в конечном `response.done.output` сохранился только `output_audio` content shape, без текста. Поэтому текст доказан событием `output_text.done`, а не извлечением из конечного `response.done.output`.

### N. AUDIO OBSERVATION

| ВопросНаблюдение               |                                                    |
| ------------------------------ | -------------------------------------------------- |
| Session audio-capable?         | Да, по metadata                                    |
| Audio настроено ORION?         | Нет                                                |
| Audio input отправлен?         | Нет                                                |
| Audio output запрошен?         | Нет, в обоих запросах `["text"]`                   |
| Получены output audio-события? | Да: done, transcript.done и audio content metadata |
| Audio декодировано?            | Нет                                                |
| Audio воспроизведено?          | Нет                                                |

`response.output_audio.delta` / `response.audio.delta`: **0**.

Следовательно:

- Строгий запрет любых audio-событий **не прошёл**.
- Получение фактического PCM/audio payload **не установлено**.
- Нельзя по этому запуску отличить пустое обязательное audio-оформление протокола от режима, который потенциально допускает audio generation.
- WAV/PCM не создавались.

### O. TOOL / AUTHORITY OBSERVATION

| ПроверкаРезультат               |                                  |
| ------------------------------- | -------------------------------- |
| Planner вызван                  | Нет                              |
| ToolGateway вызван              | Нет                              |
| Tools объявлены                 | Нет; provider session `tools=[]` |
| Tool call возвращён             | Нет                              |
| DCS facts переданы/получены     | Нет                              |
| Mission facts переданы/получены | Нет                              |
| Действия исполнены              | Нет                              |

Это синтетическая conversational-проба, не проверка operational authority path.

### P. CLEANUP / RESOURCE OWNERSHIP

| РесурсСоздание / владелецTerminal / остаток |                                    |                                                                              |
| ------------------------------------------- | ---------------------------------- | ---------------------------------------------------------------------------- |
| WebSocket                                   | Harness                            | Закрыт                                                                       |
| HTTP client session                         | Harness                            | Закрыта                                                                      |
| Provider session                            | Провайдер, через harness           | `response.done`; соединение закрыто; удаление серверной сессии не наблюдаемо |
| Async tasks                                 | Harness / asyncio                  | Незавершённых: 0                                                             |
| Threads                                     | Возможны служебные executor-потоки | Новых оставшихся: 0                                                          |
| Reconnect timer                             | Не создан                          | Нет                                                                          |
| Retry owner                                 | Не создан                          | Нет                                                                          |
| Audio device                                | Не открыт                          | Нет                                                                          |
| DCS connection                              | Не создано                         | Нет                                                                          |
| SRS connection                              | Не создано                         | Нет                                                                          |

Cleanup exception: **нет**. Эксклюзивный attempt latch предотвращает случайный повторный запуск.

### Q. LATENCY

| ИнтервалВремя                                |                            |
| -------------------------------------------- | -------------------------- |
| Connect                                      | 1157 мс                    |
| Connected → session.created                  | 78 мс                      |
| session.update → session.updated             | 250 мс                     |
| User item → response.create после acceptance | 265 мс                     |
| response.create → первый text delta          | 297 мс                     |
| response.create → text complete              | 500 мс                     |
| Text complete → response terminal            | 0 мс на разрешении отметок |
| Terminal → cleanup complete                  | 313 мс                     |
| Connect start → cleanup complete             | **2563 мс**                |

Это не физическая voice/PTT latency и не результат её оптимизации.

### R. HISTORICAL 9ed45bb COMPARISON

Сопоставлены:

- `9ed45bbd820e60784d83c357a248d3b95dae765a`
- `8182e892a951afe7f239f3f7f5a2231415c6d57d`

Исторический путь также отправлял session/response `output_modalities=["text"]`, но принимал `session.updated` без нынешней строгой проверки значения acknowledgement.

Исторические текстовые результаты подтверждают работу того пути. **Точное старое значение server acknowledgement не сохранено**, поэтому доказать изменение провайдера во времени нельзя.

Старый parser не переносился.

### S. API / CONTRACT DRIFT

**Временной API drift не доказан.**

Доказано текущее расхождение:

`запрошено ["text"] → session/response metadata ["text","audio"] → text result + audio terminal events`

Не хватает сопоставимого старого acknowledgement и однозначной интерпретации пустых audio terminal events. Нельзя объявить ни гарантированную text-only поддержку, ни глобальную невозможность такого режима.

### T. PREVIOUS nontext\_session ROOT CAUSE

**E. INCONCLUSIVE — confidence HIGH в недостаточности доказательств для окончательной классификации.**

Непосредственный механизм локального отказа установлен: строгий predicate отвергает мультимодальный acknowledgement.

Но признать это только validation bug или безопасным session/operation confusion нельзя: диагностическое продолжение получило запрещённые audio-события. Исторический drift также не доказан.

Предыдущий `nontext_session` возникал до генерации; он не является свидетельством отказа модели ответить на пользовательский текст.

### U. CURRENT LEVEL-0 MODULE STATUS

Production Level-0 оставлен без изменений и **не объявляется готовым**.

Дополнительная offline-проверка полученного текста:

- `admit_social_text(...)` → `False`.
- `parse_draft(...)` → schema rejected.

Причина ожидаема: probe запрашивал обычный текст, не production JSON `SocialDraft`. Этот ответ не доказывает прохождение Core admission; его отклонение само по себе не означает, что ответ небезопасен.

Политика молчаливых source labels по умолчанию сохранена как требование; в рамках probe не реализовывалась. Hybrid wording не менялось.

### V. FUTURE IMPLEMENTATION DIFF BOUNDARY

Одной замены `nontext_session` predicate **недостаточно**. В текущем адаптере далее имеются проверки:

- Assistant `conversation.item.created` → `unexpected_item`.
- Audio content part → `nontext_output`.
- Terminal output только с audio shape → `nontext_terminal`.

Нельзя просто отключить эти проверки или начать игнорировать audio-события. Сначала требуется установить допустимый контракт наблюдённой последовательности. Любое последующее изменение — только отдельная авторизация; STT/Core/TTS/SRS и Launcher не входят в этот diff.

### W. SECURITY / CHANGE AUDIT

- Секреты и auth headers не записаны.
- Полные provider bodies и audio payload не сохранены.
- API key и folder ID исключены из сохранённых строк.
- Репозиторий, семь untracked-файлов и конфигурация неизменны.
- Build/install/commit/push отсутствуют.
- DCS/SRS/audio devices не запускались и не использовались.
- Единственные новые файлы — изолированный harness, тесты, latch и результаты вне worktree.

Основное доказательство: [provider-protocol-result.json](C:/Users/Алексей/Documents/ORION-Builds/yandex-realtime-text-protocol-probe-20260908/provider-protocol-result.json).

SHA-256:
```
C45012C772FBB45D5B5B1C0B30135401548046D08A5127980B7A90A1088E6DAD
```

### X. NEXT TRANCHE

Один предлагаемый следующий шаг, **не выполненный сейчас**: отдельно авторизованное read-only уточнение контракта пустых audio terminal events по уже сохранённой последовательности и целевой официальной документации.

Без нового provider-запроса, без изменения backend и без ослабления production-проверок.

### Y. CURRENT STATUS

Provider response завершён; ресурсы закрыты; evidence сохранено. Harness verdict: **`FAIL_UNEXPECTED_OUTPUT`**.

Текстовая генерация наблюдалась, но требуемая комбинация «текстовый результат и ноль audio-событий» не доказана. Работа остановлена.

### Z. FINAL VERDICT

YANDEX REALTIME PROBE INCONCLUSIVE — DO NOT MODIFY PRODUCTION
