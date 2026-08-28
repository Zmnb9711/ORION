# Pilot Phraseology KB and offline deterministic Test Probe

Status: **EXPERIMENTAL / NON-NORMATIVE**.

## Purpose and boundary

The Pilot answers one bounded architecture question: can Core deterministically
turn already-decided operational semantics into Russian and English protected
fragments without changing values, units, signs, availability or identity?

The Pilot is not a production Phraseology Engine and makes no ICAO, NATO, FAA,
Russian military, national ATC, regulatory or doctrinal compliance claim. Its
phrases are synthetic architecture fixtures and are not an authoritative
real-world phraseology source.

The only runtime direction is:

```text
runtime truth
→ existing ORION semantic architecture
→ OperationalSemanticUnit
→ PilotPhraseologyResolver
→ ProtectedOperationalFragment
```

The resolver never reads DCS telemetry, MissionStore, WorldModelFacade,
ToolGateway, provider sessions, SRS, RadioRouter or Launcher state. It does not
perform composition, speech, audio or radio transmission. Existing production
routes and domain wording are unchanged.

## Catalog model and exact selection

`PilotPhraseologyCatalog` is a code-seeded immutable 25-entry catalog. External
JSON/YAML package data is intentionally avoided for this experiment. Every
`PilotPhraseologyEntry` contains:

- a stable entry ID and `pilot-phraseology-v1` version;
- one exact selector: communication profile, domain, unit type, semantic
  meaning, status and polarity;
- explicit slot definitions;
- ordered `en-US` and `ru-RU` realizations;
- an enforced experimental/non-normative marker.

The Pilot uses the existing `NATO_MILITARY` profile as an experiment selector;
this does not claim that the synthetic wording is normative NATO phraseology.
Zero exact matches return `not_found`; multiple matches return `ambiguous`.
There is no fuzzy selection, nearest phrase, embedding, LLM selection,
free-text parsing or fallback phrase.

Catalog construction rejects duplicate IDs/selectors, incomplete language
pairs, undeclared or missing placeholders, duplicate slots, format specs,
conversions and formatter/kind/unit incompatibility. Catalog identity is the
SHA-256 of its canonical sorted JSON representation.

## Slot and formatter policy

Slots reuse `ProtectedValue`, `ProtectedValueKind` and the semantic keys already
carried by `OperationalSemanticUnit`. The closed Pilot formatter set is:

- `exact_text`;
- `integer`;
- `signed_integer`;
- `fixed_three`;
- `tacan_exact`;
- `laser_code_exact`;
- `coordinate_six`;
- `modulation_exact`.

KB entries cannot supply Python format strings, code or provider formatting.
The resolver requires exactly the declared protected keys, kinds and units.
Missing, extra, invalid or wrongly-unitized values produce typed failures and no
fragment.

## Unavailable semantics and provenance

Unavailable is selected explicitly. `navigation-tacan-unavailable` has no TACAN
value slot and cannot inherit, infer or fabricate `44X` or another channel.

Existing provenance is unit-level rather than per-slot. The Pilot therefore
requires exactly one coherent `ProtectedProvenance` on each semantic unit. It
rejects zero or multiple provenance records instead of silently composing
mixed-origin values. Redesigning provenance is deferred.

## Pilot entries

| ID | Semantic coverage | Protected slots |
|---|---|---|
| `general-acknowledgement` | acknowledgement | — |
| `general-affirmative` | affirmative | — |
| `general-negative` | negative | — |
| `general-unable` | unable | — |
| `general-information-unavailable` | unavailable information | — |
| `general-say-again` | repeat/clarification | — |
| `general-readback-confirmed` | confirmation/readback | — |
| `radio-callsign` | callsign | callsign |
| `radio-frequency` | frequency | frequency/MHz |
| `radio-modulation` | modulation | AM/FM |
| `radio-frequency-modulation` | combined channel | `264.500 MHz`, `AM` |
| `navigation-heading` | heading | degrees |
| `navigation-altitude` | altitude | feet |
| `navigation-speed` | speed | knots |
| `navigation-range` | distance/range | nautical miles |
| `navigation-bearing` | bearing | degrees |
| `navigation-signed-correction` | signed offset | `-850 ft` |
| `navigation-tacan-available` | TACAN available | `44X` |
| `navigation-tacan-unavailable` | TACAN unavailable | — |
| `jtac-laser-code` | laser code | `1577` |
| `navigation-position` | position | latitude/longitude degrees |
| `warning-fuel-low` | bounded warning | — |
| `warning-traffic` | bounded warning | — |
| `status-ready` | operational status | — |
| `status-not-ready` | operational status | — |

Every entry has both language realizations. RU/EN verification compares the
canonical semantic case, protected values, units, status, meaning and
provenance; it does not require literal cross-language text equality.

## IA-6 compatibility demonstration

`adapt_ia6_ownship_heading` is deliberately capability-specific. It accepts
only `world.ownship.read`, reads only the structured authoritative
`ownship.heading_deg` fact with unit `deg` and requires its source reference. It
does not parse or trust `SemanticResponse.recommendation`. No generic
`SemanticResponse` conversion is implemented.

## Offline Probe and evidence

Run without network, providers, credentials, DCS, SRS or audio devices:

```text
python -m orion.pilot_phraseology_probe --output-dir <runtime-directory>
```

The Probe executes all 25 entries in both languages: 50 expected positive
cases. It repeats the full corpus with a fresh catalog and resolver, compares
canonical outputs after excluding correlation IDs/timings, and verifies stable
catalog identity and RU/EN semantic equivalence.

The ZIP evidence bundle contains:

- `manifest.txt` — bounded scope/count/privacy declarations;
- `summary.json` — result and aggregate gates;
- `cases.jsonl` — positive cases plus validator self-tests;
- `catalog.json` — canonical catalog representation and SHA-256.

Each positive case records selectors, language, protected inputs/units,
provenance, expected/selected entry, resolved slots, rendered text, assertions,
typed failure and bounded duration.

## Corruption self-tests

The independent record validator must detect all twelve injected defects:

1. `264.500 → 264.050`;
2. `AM → FM`;
3. `44X → 44Y`;
4. `1577 → 157`;
5. `-850 → +850`;
6. `MHz → kHz`;
7. `ft → m`;
8. unavailable TACAN → fabricated TACAN;
9. missing required slot;
10. wrong selected entry ID;
11. duplicate result;
12. dropped result.

A self-test passes only when the validator reports the injected defect.

## PASS/FAIL and deferred work

`PILOT PASS` requires 20–30 entries, all 50 positive results, exact unique
selection, preservation of protected semantics, no drops/duplicates/fabricated
facts, bilingual semantic equivalence, fresh-resolver determinism, stable
catalog hash and 12/12 successful negative self-tests. Any executed Probe that
misses a gate returns `PILOT FAIL`.

Deferred by design: normative source selection, a large corpus, per-slot
provenance, production PresentationRouter/composition, TTS, Direct Audio, SRS,
live DCS testing and migration of ATC/AAR/AWACS/JTAC/Mission Control wording.
