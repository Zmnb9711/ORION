# Foundation Step 2 — Conversation on current Yandex

ORION ARCHITECTURE GUARD: OFF

2026-09-14. WORKTREE ONLY; live Conversation quality gate FAILED. No commit,
build, installation, physical test or Step 3. No post-failure prompt tuning.

## A. Contract / starting Git state

CONTRACT READ: ORION_NATURAL_LANGUAGE_FIRST_CONTRACT_V1.
Worktree: `C:/Users/Алексей/Documents/GitHub/ORION-level0-conversation`.
Branch: `codex/general-natural-language-ingress-tranche1`.
Parent/unchanged HEAD: `4b5a46959c241eec6ef8391ee52de4da93f3dc0f`.
Parent tree: `96ff342b844590d0d89db6a1df5d8873bb15fd28`.
Starting tracked/index state clean; untracked `data/` preserved.
Step 1 is committed at that parent; its old precommit report remains historical.

Canonical contract SHA-256 remains
`de59126cb79efc010996f4f8357ab80b641109b7ed3cd60ccbc7856d53c2a128`.
Invariants 1–3/6/12–13: open semantic ingress, no phrase grammar;
4–5/7: unchanged Core facts/permissions; 8: no Mixed execution;
9: bounded ORION context; 10–11: one operation; 14–15: preservation and truthful
field status. No architecture contract amendment.

## B. Historical Qwen 402 reference

Exact checkpoint `4e8b49afff0b8f5d1ec1a008f09f79ae08e1a546`:
the audio session instruction assigns ORION an open conversational role and
natural response in the user's language. This is a reusable ROLE reference,
not authority to restore its audio architecture.
The contemporaneous user verdict recovered in
[Foundation audit](2026-09-14-foundation-recovery-audit.md), section D,
2026-08-20 18:44:57: «в целом речь стала нормальной. думаю нужно фиксировать
№402 как baseline». This supports scoped audible speech quality, not a matched
Qwen/Yandex benchmark of knowledge, continuity or model latency.

Provider-independent: open role, direct generated response ownership, natural
language, conversational positioning. Qwen-specific: provider VAD, generated
audio path, provider-session history. These were NOT imported. Comparable
model-quality, repetition, instruction-following and latency superiority remain
UNKNOWN. No Qwen request or provider switch.

## C. Current Yandex before change

The parent already had a general typed DIALOGUE outcome, one General operation,
two explicit exchanges, reply fingerprints and delivery metadata. It was NOT
context-free and was no longer routed through local social admission after
Step 1. Existing instructions already mentioned knowledge and avoiding repeats.
Historical latest field evidence nevertheless showed repeated generated joke
text; the exact prompt/context supplied in that old run was not recoverable.
Current TTS failure debt is separate: seven RESOURCE_EXHAUSTED/zero-PCM cases
and one partial transmission in the prior audit do not establish semantic
model failure. See audit and [field index](FIELD_EVIDENCE_INDEX.md).

## D. Exact defects addressed

1. Role was predominantly schema-first; make open conversation, useful topic
   engagement and stable knowledge explicit without topic recognizers.
2. Semantic context acceptance occurred only after presentation returned/raised.
   Accept admitted Dialogue before audio, then correlate delivery separately.
3. Interpreter ValueError (including typed validation) became
   PROVIDER_UNAVAILABLE. It now has semantic_validation evidence and existing
   ADMISSION_REJECTED output; transport exceptions retain provider failure.

This does not assert these three issues explain all historical field failures.

## E. Provider role / prompt change

`general_semantic_contracts.provider_instructions`: one open conversational
copilot/semantic role; direct useful contributions; general knowledge is not a
missing simulator capability or an automatic REASONING_REQUEST. Context supplies
topics/referents; variation should add different content; requested quotation
remains allowed. No input examples, jokes list or new social classes.
Soft target <=200, hard 400 unchanged. No truncation, retry, second model or
length-policy change. Existing provider/model/transport remain unchanged.

## F. ORION context before / after

Still two whole exchanges, <=4096 UTF-8 bytes, 300 seconds, session/epoch reset;
no persistent transcript. User text, non-authoritative reply, semantic outcome,
language and fingerprint already existed. Add interaction_id to bind a delivery
update to its accepted exchange. No provider hidden memory is required.
`accept` records Dialogue as pending before presentation. `update_delivery`
changes only pending matching identity/fingerprint metadata, never re-admits or
increments semantic revision. Late/reset/expired/evicted updates do not revive
old context. Whole-exchange bounds also apply after longer delivery labels.
`user_heard` remains false. Facts/META output are not retained as factual prose.

## G. Continuation mechanism

The next request projects prior user/reply content through response instructions.
Real-host fake-I/O tests inspect pending semantics at presentation entry, then
inspect the following request including after TTS failure. Live requests 3 and
7 contained the exact preceding rainbow/pendulum exchanges, but the answers
failed to resolve those referents. Continuity is therefore NOT validated.

## H. Repetition mechanism

General prior-response content/fingerprint plus a variation instruction, not
per-topic state, blacklists, judge or retry. No identical reply occurred in this
gate, but variation turn 4 claimed the prior thought was missing. Absence of a
duplicate is insufficient to claim useful variation or a fixed repetition bug.

## I. General knowledge

All ten actual terminals were DIALOGUE. Basic knowledge was accessible without
tools; no false CAPABILITY_GAP/PROVIDER_UNAVAILABLE occurred. The rainbow answer
was approximate; continuation supplied unsupported orbit/curvature speculation.
The pendulum answer was useful; the thermal analogy was awkward. This small
evaluation does not prove general knowledge correctness across topics.

## J. DCS authority

Fact Registry, ToolGateway, WorldModel, router admissions, META rendering and
all fast-path runtime files are unchanged. Existing negative injection,
freshness/provenance/replay and factual host tests passed. Live gate forbade
tools and supplied no DCS or personal data. It did not test actual simulator
facts or prove that a language model can never hallucinate in free prose.

## K. Failure recovery

Turn 9 returned a valid provider palindrome answer. ONLY in the isolated gate
process, its parser input was replaced with `{"kind":"DIALOGUE","text":[]}`.
Original raw/normalized terminal and injected parse input are separately saved.
Expected ValidationError `string_type`, `DIALOGUE.text`; no Core admission of
the injected result. The real owner closed its dirty transport and performed
one fresh handshake. Turn 10 succeeded on the new session, same ORION context.
Ten operations total, two connections (initial + recovery), no same-turn retry;
zero remaining owned tasks after shutdown. This is controlled failure evidence,
NOT a naturally malformed Yandex response.

## L. RU / EN

RU turns 1–5: ordinary/topic change structurally and conversationally useful;
continuation/variation FAIL. EN turns 6–10: knowledge and post-recovery response
useful; continuation FAIL, variation only partial. No language phrase grammars.
No acoustic or pronunciation check.

## M. Latency

Cold handshake 1500 ms, excluded from operation values below. Warm first text
312–453 ms; terminal 594–828 ms; successful ACK isolation 250–297 ms.
Controlled failure: terminal-to-recovery-start/close ~188 ms, fresh handshake
1047 ms (~1235 ms terminal-to-ready). Next operation starts after recovery.
Parse/admission recorded 0 ms at this clock's granularity: NOT proof of zero
cost, and no sub-millisecond claim. First text is JSON-envelope onset, not
audible speech or necessarily first useful response words. No TTS/total-voice
latency claim; no latency optimization.

## N. Changed files / symbols

Runtime ONLY:

- `orion/general_semantic_contracts.py`: ContextExchange, provider_instructions.
- `orion/general_semantic_core.py`: InteractionContext.accept/update_delivery.
- `orion/general_semantic_voice.py`: GeneralSemanticVoice.run.

Tests/tooling: `tests/test_foundation_conversation.py` (15 mechanism cases),
`tests/test_foundation_routing.py` (freeze exact committed Step 1 runtime while
retaining original AST assertions), `tests/general_ingress_hashes.json` (three
reviewed runtime hashes only), `scripts/foundation_conversation_gate.py`
(explicit opt-in, bounded developer-only probe; no production import).
Documentation: this record plus Memory/history/field/contradictions status links.

## O. Anti-template audit

Production diff: no input phrases, regex, synonyms, joke-specific handling,
person rules, knowledge keyword classifier or new topic intent. Step 1 service
and hybrid runtime bytes remain unchanged. One General owner/operation; no
legacy ConversationVoice restoration. Production scope asserted by tests.

## P. Offline / host results

Full suite: 3295 passed, 5 pre-existing failures, 1 skipped (81.63 s).
This full run preceded the final <=4096-byte delivery-label trim and the added
probe test. Final changed-runtime targeted run: 249 passed (16.54 s), including
15 new cases, exact Step 1 routing, semantic/context/length, General and legacy
preservation host tests. The probe itself was replayed offline through the real
warm owner with fake wire: ten operations, controlled failure, two connections,
future success. Real service tests use fake STT/provider/TTS/radio; not field.
Final changed runtime Pyright: 0 errors/warnings. Ruff, compileall and diff check
PASS. Fixtures do not prove generated quality.

Five baseline failures unchanged and previously reproduced on be413a8:
interaction-contract import inventory; three setup-wizard autodiscovery stage
expectations; stale Project Memory exact-field-artifact phrase expectation.
See [Step 1 record](2026-09-14-foundation-step1-routing.md). No baseline fixes.
Temporary XML reports:
`C:/Users/Алексей/AppData/Local/Temp/orion-foundation-step2-offline.xml` and
`C:/Users/Алексей/AppData/Local/Temp/orion-foundation-step2-targeted.xml`.

## Q. One live Yandex multi-turn gate — every turn

2026-09-14 ~21:44:49–21:45:00 Moscow, developer-created text, not future blind
wording. Model is current `speech-realtime-260528`, existing secure credentials
and configured Yandex folder; no config edit. No personal facts sent.
All actual replies below were JSON DIALOGUE, with Markdown fences accepted by
the unchanged normalizer. Strict no-Markdown instruction following thus partial.

| # | Language / input | Exact admitted response (except controlled #9) | Quality outcome | First / terminal / isolation ms |
|---|---|---|---|---|
| 1 | RU: Хочется ненадолго отвлечься от дел. Предложи необычную тему для разговора. | Давайте поговорим о самых необычных аэропортах мира — например, о тех, что расположены на островах или среди гор. Интересно узнать, как там всё устроено! | Relevant, natural; novelty subjective; 153 chars | 453 / 813 / 265 |
| 2 | RU: Объясни коротко, почему радуга имеет форму дуги. | Радуга имеет форму дуги из-за того, что капли воды в воздухе преломляют и отражают солнечный свет в виде конуса; наблюдатель видит лишь его сечение — дугу. | Relevant but approximate explanation; 155 chars | 422 / 734 / 266 |
| 3 | RU: А почему её центр нельзя увидеть над горизонтом с земли? | Вероятно, речь о каком-то небесном объекте. Его центр может быть скрыт из‑за кривизны Земли или особенностей орбиты/расположения. | FAIL: loses rainbow referent, unsupported speculation; 129 chars | 344 / 656 / 266 |
| 4 | RU: Объясни ту же мысль иначе, через наглядное сравнение. | К сожалению, без исходной мысли не смогу провести сравнение. Расскажите, какую идею нужно объяснить — и я с радостью помогу с наглядным сравнением! | FAIL: supplied recent thought not used; 147 chars | 344 / 625 / 297 |
| 5 | RU: Сменим тему: что тебе кажется интересным в старых библиотеках? | В старых библиотеках интересна атмосфера — запах книг, тишина, уникальные издания. Ещё впечатляет, как много знаний собрано вручную, без цифровых технологий. | Relevant natural opinion; 157 chars | 328 / 594 / 265 |
| 6 | EN: Why does a pendulum gradually stop in ordinary air? | A pendulum stops due to air resistance and friction at the pivot point, which convert its kinetic energy into heat. | Useful basic explanation; 115 chars | 422 / 828 / 250 |
| 7 | EN: Where does that energy go? | It depends on the context — energy can dissipate as heat, do work, or transform into other forms. Could you clarify what kind of energy you’re referring to? | FAIL: unnecessary clarification despite explicit pendulum context; 156 chars | 312 / 625 / 250 |
| 8 | EN: Give me a different everyday analogy for that energy transfer. | Think of it like passing a hot pan between people — the heat (energy) moves from the hotter person to the cooler one, just as it moves from a warmer object to a cooler one in thermal transfer. | Partial/awkward analogy; no useful pendulum continuity proof; 192 chars | 312 / 687 / 250 |
| 9 | EN: Briefly explain what a palindrome is. | Original RAW text: A palindrome is a word, phrase, or sequence that reads the same backward as forward, like 'madam' or 'racecar'. NOT admitted: controlled parser fault. | Recovery mechanism PASS, not provider failure | 313 / 672 / recovery 1047 |
| 10 | EN: What makes a short story satisfying even with an open ending? | A satisfying open-ended short story often leaves a strong emotional impression, hints at deeper themes, or raises intriguing questions—letting readers fill in the gaps with their own imagination. | Relevant response after recovery; 195 chars | 407 / 735 / 250 |

Exact bounded request/context, RAW, normalized, parsed, admission, IDs and
timestamps: `C:/Users/Алексей/AppData/Local/Temp/orion-foundation-step2-live-20260914-01/report.json`.
SHA-256: `a707c8bf0951782c02e04ca12a6817f2fa2650a7da83c401c8dffd579a0570ba`.
Provider sessions `778845991d30` then `350badcae658`.
No secrets, auth headers, full event bodies, audio or hidden reasoning retained.

## R. Known limitations / stop classification

Confirmed: ORION projection at failed turn 3 contained the exact rainbow
exchange; failed turn 7 contained the pendulum exchange. The production code
constructs response.instructions from this projection; fake-wire tests verify
that handoff. Local projection is not proof of the provider applying it.
No live server-side instruction echo/application proof was collected.

Classification: effective context use/role contract failure; causal boundary
UNKNOWN between per-operation instruction application, prompt effectiveness and
model context following. No evidence of billing/auth/quota failure in this gate;
no natural parse/length failure. Do not label this proven intrinsic Yandex
inferiority, and do not switch provider. A separately authorized context-
application check should precede any provider conclusion; if model limitation
remains suspected, only a user-approved matched Qwen/Yandex comparison can
separate it. No such follow-up performed or authorized by this report.

## S. Exact diff summary / preservation

Tracked executable/test diff: 5 files +55/-9; new files are the 15-test module
and explicit provider gate script. Documentation is status/history only.
Complete review patch is preserved alongside the temporary provider report as
`step2-complete.diff`; new files included, user data excluded.
Canonical contract and all out-of-scope runtime files unchanged.
`data/fa18c_value_profiles.json` remains SHA-256
`4975e243ee95fdf997ccc5ecc4537eaff87947265c1c9a7f876ecf3ccee15c1f`.
Original 101803 bytes of events.jsonl retain SHA-256
`001d663f44f468b21667383c9bfF062b0e02b5eb7053347475c89677fa25d02c`;
test-generated appends preserved. Nothing staged or discarded.

## T. Product status

CODE / OFFLINE / real-host-fake-I/O proof only for mechanisms.
Live text STRUCTURAL + RECOVERY proof, but Conversation QUALITY FAIL.
No installed artifact/source changed, no DCS/STT/TTS/SRS/PTT/TX or acoustic gate;
blind field status NOT TESTED. Existing product FIELD FAIL is not upgraded.
Step 3 delivery debt remains untouched.

## U. Commit status / final verdict

No commit/push. HEAD remains 4b5a469. Worktree and evidence preserved for review;
do not commit this as a successful Step 2 or proceed to Step 3 automatically.

FOUNDATION STEP 2 YANDEX CONVERSATION QUALITY INSUFFICIENT — STOP FOR
PROVIDER / ARCHITECTURE DECISION
