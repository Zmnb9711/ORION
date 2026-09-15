ORION ARCHITECTURE GUARD: OFF

# Следующее задание — Yandex 260528: external protected reply, MIXED и аудиовход

**PREPARED, NOT EXECUTED. PAUSED AT USER REQUEST.**

Основание: раздел 9 `YANDEX-260528-INDEPENDENT-REVIEW-AND-NEXT-PROBE.md`, SHA-256 `8C3B7F14251939D2826B7318391637F31A6744775C21DEB5800F4D893282DC83`. Ниже сохранены цель, ограничения, сценарии и критерии этого задания. Это не результат нового эксперимента. Возобновлять только после отдельной команды пользователя; сначала проверить, не появился ли уже отчёт локальной Astra.

## 1. Цель

Выполнить малый изолированный native-tools continuation probe на `speech-realtime-260528`. Проверить внешний защищённый ответ, передачу greeting cue и настоящий аудиовход. Не повторять общий preflight, не писать production patch.

Оригинальный Stage6B.2 `a955d7c39f20c020e15de6bc2be272755928cc98`, tree `7c010efadc2a8c0b6b892b49354a4019e4fdb3b2`, остаётся неизменным. Предыдущий evidence immutable.

## 2. Среда, секреты, бюджет

Новый каталог вне ORION repository/install/runtime/backups; отдельный процесс и WebSocket sessions. Не запускать ORION, Launcher, DCS/SRS; не обращаться к их localhost API; не коммитить, не собирать и не устанавливать runtime.

Credential читать только локально из известного ORION target для Authorization. Не печатать, не передавать argv, не сохранять в evidence; не искать другие secrets и не менять IAM/keys. Folder ID брать из уже подтверждённой локальной конфигурации, не угадывать по формату. Не просить ключ в чате.

Та же модель. Не переключаться на Qwen или другую модель ради PASS.

Лимиты: максимум24 response generations суммарно, включая продолжения и unsolicited;10минут процесса;30секунд ожидания одного ответа;8MiB PCM на response. Не более6 коротких SpeechKit синтезов для input/output fixtures, вместе до1200символов. Учитывать расходы отдельно; никаких автоматических retry до PASS. Превышение → STOP.

Не записывать новый пользовательский микрофон без отдельного действия. Звук сохранять вWAV, не проигрывать и не передавать порадио; `delivery=NOT_SENT`. Synthetic input не выдавать за физическую речь пользователя.

До запуска зафиксировать case matrix и ожидаемые исходы. Любое изменение prompt/schema — отдельный hash/configuration, не повтор неизменного baseline. Сохранить неудачи.

## 3. Freshness: сменить источник ДО неоднозначного вопроса

На исходном prompt/schema выполнить парный сценарий:

1. Явный вопрос собственного heading, fixture137.
2. Локально сменить fixture на223 ДО следующей реплики; записать `fixture_revision_changed` с временем.
3. «Куда я сейчас лечу?».
4. При необходимости один контроль: «А какой у меня курс сейчас?».

В первой сессии CONTROL: numeric/status function output + explicit response.create. Во второй EXTERNAL: service receipt без числа и без post-tool response.create. Вопросы и последовательность смены fixture одинаковые. Отличия result/presentation policy обозначены явно. Это сравнение схем, не однофакторное доказательство причины тишины.

PASS для current/ambiguous query: уточнение без выдуманного current value либо осмысленный heading lookup с текущим fixture. Память старого числа или удачное угадывание нового без lookup не protected PASS.

Одна дополнительная историческая реплика, например «Какое значение было в предыдущем результате инструмента?», проверяет current versus historical. Receipt-only session не должна притворяться, что провайдер получил отсутствовавшее число.

Не очищать историю между ходами ради PASS. Не лечить пропуск инструмента regex по «курс», не вводить второй LLM classifier. Receipt-only может уменьшить один источник stale reuse, но не считается универсальной защитой: число может быть в user text или FlightContext.

## 4. MIXED через локальную защищённую композицию

Отдельная схема инструмента может добавить ограниченный social cue, например enum `none / greeting / repeated_greeting`. Имя и schema фиксируются заранее. Heading value, unit, sign и finalized protected text НЕ становятся аргументами, назначаемыми моделью.

Проверить: «Какой у меня курс?» без приветствия; «Добрый день! Какой у меня курс?»; «Ещё раз добрый день! Какой у меня курс?»; один FREE control без запроса текущих собственных данных.

Модель сама выбирает function call и cue по естественной реплике. Локальный код не определяет приветствие по expected case или keyword match.

Callback читает fixture. Минимальный deterministic formatter создаёт protected heading fragment. Для137/223/unavailable допустим fixture renderer, но не называть его готовым универсальным Phraseology Engine.

Local composer соединяет social prefix и protected fragment. Готовый ответ не возвращать Yandex для пересказа. Вернуть честный service receipt с call/request reference, external owner и NOT_SENT; не инициировать native factual continuation.

Это ограниченная проверка приветствия, не полный свободный MIXED Composer. Для одного heading и одного mixed сохранить SpeechKit синтез финализированного текста внутри бюджета. Это OUTPUT WAV, отдельно от INPUT вопросов. Сохранить точный TTS request text, PCM и hashes. Без прослушивания `acoustic_status=NOT_REVIEWED`.

## 5. Аудиовход — обязательная отдельная проверка

Подготовить3–4 synthetic WAV вопросов FREE, HEADING, MIXED и, при бюджете, AMBIGUOUS. Если готовых вопросов нет, получить их разрешённым коротким SpeechKit синтезом; не заканчивать снова NOT_RUN без попытки такой подготовки. Не синтезировать личную память или голос пользователя. WAV ответов предыдущих tests не выдавать за вопросы пилота.

INPUT_CORPUS: текст, происхождение, формат, длина, SHA-256. Отправлять реальные audio append chunks с согласованным rate/pacing и terminal silence. Не подавать тот же вопрос параллельно как input_text.

Воспроизвести baseline VAD. Не отправлять response.create поверх автоматически созданного VAD response. Один pending turn; неожиданный concurrent response или неоднозначная association → STOP case без last-response heuristic.

Ledger: local_turn_id → audio boundaries → server input item, когда доступен → response_id → call_id → local result/composition. Не выдумывать originating input_id. Sequential association маркировать отдельно; второго input нет до завершения первого; следующий FREE сохраняется. Не заявлять barge-in/overlap proof.

MIXED audio не считать пройденным по текстовому аналогу. Если событий недостаточно для claimed association, назвать точную границу NOT_PROVEN.

## 6. Минимальная диагностика

Сохранять все session updates. Не начинать первый case по первому session.updated, если доступные поля ещё не отражают requested settings. Returned rate=null не ждать бесконечно: записать NOT_OBSERVABLE.

Конфликт kirill/dasha отразить без утверждения actual voice. WAV header44100 не независимое доказательство server rate.

Записывать close code, local close intent, receive timeout/cancellation и exception category без secrets. Предыдущий1006 не менять на1000 задним числом и не объявлять диагностированным server crash.

Раздельно считать аудио до вызова, в tool response и после receipt. Silence window ровно5s так и обозначать. Различать generated, locally selected, synthesized, played. Отсутствие проигрывания из-за выключенного динамика не suppression proof.

Не придумывать function-output ACK. Его отсутствие без server requirement не автоматически protocol failure; сохранить фактическое поведение следующих ходов.

## 7. Стоп и выдача результата

Если current factual statement снова выходит без fresh tool, не объявлять native-auto/no-tool FREE admission безопасным. Сохранить контрпример. Не расширять эксперимент бесконечными prompt variants, не писать integration patch.

Если cue не передан, не добавлять приветствие по expected case. Если audio input не получается, сохранить точную ошибку. Успех ограниченного prototype даёт только основание отдельно обсудить экспериментальную интеграцию, не разрешение на замену a955d7c.

Вернуть REPORT.md с каждым заранее заданным case, configuration(s)/hashes/events.jsonl, INPUT и OUTPUT manifests/WAV, один evidence ZIP с report, список NOT_PROVEN/NOT_RUN и счётчики расходов. Дать ссылки на REPORT.md и ZIP. Не объявлять full ORION/field PASS.

**В состоянии EOD это задание только сохранено. Автоматический запуск запрещён.**
