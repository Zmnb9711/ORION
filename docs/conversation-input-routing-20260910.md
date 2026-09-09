# Conversation input routing: bounded SpeechKit surface variation

ORION ARCHITECTURE GUARD: OFF (explicit historical recovery authorization).

## Baseline and proven failure

Baseline: c444860dcfc8c735aa2a2dd4d4edc094b24236b0, clean
`codex/level0-yandex-event-contract`. Physical turn
`8ac426ab-a25d-489d-b825-2731bf7d680f`, Test Session
`370c46abd5414d30baf4a31ba2a02dff`, archive
`ORION-Test-Evidence-20260909-203741.zip`.
Exact FINAL: `чтото полет сегодня тяжело идет`. Both Hybrid and Conversation
declined; no Conversation provider, Planner, ToolGateway, response TTS or TX.

The old `_INPUT.fullmatch` accepted idealized `что-то сегодня полет тяжело
идет` but not hyphen loss or the observed temporal-modifier placement.

## New bounded recognition contract

Only `orion/conversational_core.py` input recognition changes. It recognizes
the existing subjective/social class, not universal free dialogue:

- source remains <=500 characters; existing ru-RU request check unchanged;
- case, ё/е and whitespace normalization is classification-only;
- terminal full stops/exclamation and internal commas may be absent;
- discourse particles `что-то` / `что то` / `чтото` and corresponding
  `как-то` forms normalize only in the classification view;
- at most one each of `чтото`, `както`, `сегодня` may move between constituents;
- the complete remaining ordered clause must match the bounded social class;
- explicit singular/plural flight agreement and `летал`/`летала` are supported;
- negation, pronouns and every unknown word are retained; no arbitrary stemming,
  keyword subset, arbitrary word permutation, sentence extraction or residue drop;
- quotes, questions, control symbols and multiple sentences are not stripped into
  an accepted social fragment. Unknown/operational residue means unsupported.

This intentionally remains a bounded local recognizer, not universal Russian
NLU. Phrases outside this class remain unsupported. No cloud classifier,
Qwen decomposition or UNKNOWN -> Conversation fallback is introduced.

Exact source text and SHA-256 passed to the provider remain untouched. No output
policy, parser, SocialDraft, event/audio handling or provider lifecycle changes.

## Evidence and regression

`test_conversation_stt_routing.py` covers the recorded FINAL, four mandatory
nearby variants, punctuation/whitespace/ё/hyphen variants, inflections,
modifier movement and full-source operational/corrupted negatives. Generated
insertion tests inject operational/unknown residue at every token boundary.

Existing normal host replay is parameterized over the original idealized source
and all five mandatory STT strings, across success and failure/STOP modes:
FINAL -> real Core/Hybrid -> Conversation -> fake provider -> real finalizer ->
fake TTS -> real RadioRouter -> fake TX. Each successful social turn has exactly
one Conversation provider call, zero Planner and zero ToolGateway calls. The
following aircraft turn uses the authoritative Core path without Conversation.

The old historical scope oracle is updated only for the explicitly authorized
eligibility symbols. Independent c444860 AST comparison freezes every other
Core symbol including output policy; whole-production differential permits only
this single production file. Existing historical frozen/lifecycle gates remain.

Final relevant gate: 1565 PASS, 4 existing intentional SKIP, 42 modules, 48.98 s.
Focused routing/host/prerequisite gate: 321 PASS before the additional whole-file
freeze assertion. Pyright changed production module: 0 errors; Ruff changed
Python files, compileall orion/tests and git diff --check PASS. No broad unrelated
Pyright baseline is claimed. The first full run stopped on four old scope
assertions only (1560 PASS); its original XML remains preserved separately.

## Stop boundary

One installer only after offline regression/static/frozen gates pass. No provider
probe, installation, SRS/EAM changes, DCS/SRS launch or physical PTT in this task.
Build and test evidence is outside the worktree under
`C:\Users\Алексей\Documents\ORION-Builds\conversation-input-routing-20260910`.

After separately authorized installation and normal voice readiness, the user
speaks naturally: `Что-то сегодня полёт тяжело идёт.` PASS requires normal FINAL
variation -> CONVERSATION -> one audible response. Use existing Test Session;
no manual log collection. Do not repeat a failed turn before evidence review.
Only after PASS, optionally verify `Какой у меня самолёт?` with Core routing and
zero Conversation provider calls. No physical or acoustic PASS is claimed here.
