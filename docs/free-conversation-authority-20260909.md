# Bounded free Conversation: approved authority correction

ORION ARCHITECTURE GUARD: OFF — explicitly approved historical recovery task.

Predecessor: `f346e13f879a7845ad2ffa24ee6360afd8ebde70` preserves all five
Yandex text protocol gates. Canonical recovery context is `d0f58b5`; this is
the isolated `codex/level0-yandex-event-contract` development line, not main.

Core = authoritative facts/actions. Conversation = natural non-authoritative
language. Planner = separately authorized reasoning/tools. These roles are not
interchangeable. `social_support` is a schema hint, NOT semantic certification.

The old `_CLAUSES` output productions blocked valid generative Russian (the
fifth real reply included “Если хотите поговорить — я на связи.”). They are
removed, not expanded or replaced by a semantic judge. Output validation checks
Russian text shape, nonempty content, 300-character bound, strict schema,
terminal provider result, IDs/source hash, expiry, cancellation and replay.
Exact provider text is retained in finalized text and TTS; even whitespace is
not rewritten. Whole JSON/fence envelope normalization remains unchanged.

This does NOT guarantee truth, appropriateness or absence of unsolicited advice.
A probabilistic model can hallucinate even without tools. The user explicitly
accepted this risk for the bounded non-authoritative slice. Tests deliberately
demonstrate that factual-sounding prose may pass text-shape validation without
acquiring a fact receipt, tool, Planner or action capability. No telemetry,
ToolResult, mission state or conversation history is supplied to the provider.

## First input surface

Russian only, entire source matched (at most 500 characters). Recognition uses
case/ё/whitespace equivalence but request text/hash preserve the exact source.
Supported subjective flight/day constructions are defined by `_INPUT`:

- “Что-то сегодня полёт тяжело идёт.” / “Полёт идёт тяжело.” and bounded optional
  “что-то”, “сегодня” variants;
- “Сегодня как-то непросто летится.” / “Сегодня тяжело летится.”;
- “Что-то я сегодня не в форме.”;
- “Что-то сегодня всё идёт тяжеловато.”;
- “Сегодня как-то всё тяжеловато.”;
- “Давно я нормально не летал.”;
- “Что-то сегодня не мой день.”

Trailing period/exclamation and whitespace are allowed. No substring matching,
quoted speech, operational suffixes, generic unknown fallback, general facts,
current news or mixed Conversation+Core requests. Existing local greeting/
wellbeing Hybrid behavior is not replaced. Known Core/Hybrid routes go first.

## Evidence reuse

The fifth report remains immutable at
`C:\Users\Алексей\Documents\ORION-Builds\level0-event-contract-20260909\fifth-structured-provider-result.json`,
SHA-256 `9C88F6A9D2C47D68A350F7DFBF5AE6A440BE42929BEAEE9AAB7241AEB31BCC25`.
It proved a single terminal text operation with zero tools/provider audio,
bounded completed cleanup. It did NOT prove the new prompt or physical voice.
Its exact candidate is replayed through new finalization and existing TTS/radio
fakes. No additional provider request is necessary: protocol algorithms remain
unchanged; only instructions stop requiring canned clause productions.

Physical naturalness and the installed end-to-end voice path remain unproven
until the separately performed first physical Conversation gate.
