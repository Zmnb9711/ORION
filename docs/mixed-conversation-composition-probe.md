# Qwen Mixed FREE + OPERATIONAL Composition Probe

Status: **EXPERIMENTAL / NON-NORMATIVE / TEXT ONLY**.

## Proven boundary

The Probe exercises the existing real Yandex AI Studio Qwen 3.6 provider and
stops before speech, audio or radio:

```text
natural mixed utterance
→ YandexQwenPlannerProvider strict function-call boundary
→ MixedConversationDecomposition
├─ FREE semantics + short Qwen conversational reply
└─ takeoff_clearance_request
   → existing GoldenTakeoffVertical
   → existing AirportTowerController
   → OperationalSemanticUnit
   → FAP_RUSSIAN_ATC profile selector
   → PilotPhraseologyResolver
   → ProtectedOperationalFragment
→ ResponseCompositionPlan
→ local deterministic FREE then PROTECTED composition
```

Qwen identifies meaning and generates only the FREE reply. It cannot grant or
deny takeoff, supply runway truth, select the final operational wording, or
rewrite the protected fragment. The existing Tower state machine remains the
sole decision authority. No provider sees the `ProtectedOperationalFragment`
after it exists.

## Strict decomposition

`MixedConversationDecomposition` is provider-neutral and extra-forbidden. It
contains only:

- detected input language (`ru-RU`, `en-US` or `unknown`);
- status (`classified`, `ambiguous` or `unsupported`);
- bounded FREE kinds (`greeting`, `social_exchange`), copied source span and a
  short FREE response;
- zero or one operational intent, currently only
  `takeoff_clearance_request`;
- an ambiguity reason only for ambiguous results.

Unknown intent, missing structure, contradictory fields, extra operational
decision fields and FREE replies containing takeoff clearance wording fail
closed.

The existing `YandexQwenPlannerProvider` forces one strict emitter call. The
Probe validates its arguments and cancels the run immediately after receiving
the decomposition, which triggers the existing provider response-ID deletion
and transport cleanup. The emitter is never executed as an IA-3 Core tool.

## Communication Profile

The active profile is the existing `FAP_RUSSIAN_ATC`. Input language remains a
separate `CommunicationContext` property and is not inferred from the profile.
The current synthetic takeoff wording remains experimental/non-normative and is
not represented as verified ФАП-414 phraseology. Profile-specific KB storage,
updates and normative population remain deferred.

## Composition invariant

The existing `ResponseCompositionPlan` already separates an untrusted,
droppable `UntrustedConversationalEnvelope` from immutable Core-rendered
`ProtectedOperationalFragment` values. The local composer uses one explicit
ordering rule:

```text
FREE envelope, if present
→ protected_fragments tuple in order
```

It rejects duplicate protected fragments and verifies that every protected text
occurs exactly once in the final response. The composed response is never sent
back to Qwen for naturalization.

## Corpus and controls

The real provider corpus contains six naturally different Russian mixed
utterances, plus:

- pure operational: `Разрешите взлёт.`;
- pure conversational: `Добрый день! Как дела?`;
- aviation non-takeoff: `Башня, запрашиваю разрешение на посадку.`.

Every operational case uses a fresh identical deterministic fixture:
`Viper 2-1`, runway `07/25`, Tower authority, `CLEAR/FRESH`. Therefore the
existing ATC result is `TAKEOFF_CLEARED`, and the exact protected fragment is:

```text
Viper 2-1, полоса 07/25, взлёт разрешён.
```

Controls without takeoff intent never enter the ATC path or select takeoff
phraseology.

## Evidence and gates

Run with the existing secure Yandex credential and runtime Folder ID:

```text
python -m orion.mixed_composition_probe
```

The Probe makes nine sequential provider cases, each with an absolute
105-second deadline, at most two attempts under the existing retry policy and
the existing 45-second transport window. It stores safe normalized
decomposition and scalar usage/request IDs, never credentials, headers, raw
provider bodies or reasoning.

`MIXED COMPOSITION PASS` requires 6/6 mixed cases, 3/3 controls, exact protected
composition and all 14 injected corruption self-tests. Provider
configuration/availability failure returns `BLOCKED_PROVIDER`; provider output
that runs but violates the semantic contract returns `MIXED COMPOSITION FAIL`.

## Deferred

Microphone capture, Qwen Realtime audio, SpeechKit, Direct Audio, RadioRouter,
SRS, DCS, Launcher and installer integration are not part of this Probe. The
next approved stage may carry the locally composed text into the existing
speech/radio path without returning protected wording to a generative provider.
