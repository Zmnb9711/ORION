# Golden Conversational Vertical #1 — bounded takeoff clearance

Status: **EXPERIMENTAL / NON-NORMATIVE / OFFLINE ONLY**.

## Scope and architecture

This vertical proves one narrow end-to-end architecture path without providers,
network, DCS, SRS, audio, Launcher or installer changes:

```text
RU/EN natural-language utterance
→ bounded takeoff-clearance intent
→ existing AirportTowerController decision
→ typed TakeoffAtcDecision
→ OperationalSemanticUnit adapter
→ PilotPhraseologyResolver
→ ProtectedOperationalFragment
```

Intent recognition does not decide whether takeoff is permitted. It recognizes
only a closed RU/EN family that contains both a takeoff/departure cue and a
request/readiness cue. Conflicting or incomplete takeoff wording is ambiguous
and resolves to the existing `general-say-again` entry without calling the ATC
decision seam. Unrelated input is unsupported and stops before ATC and Pilot.

## Existing deterministic ATC seam

`ExistingAtcTakeoffDecisionService` is a narrow adapter over the existing Tower
runtime. It neither duplicates nor replaces the Tower state machine. A positive
decision calls `AirportTowerController.clear_takeoff`, which already enforces:

- Tower ownership of `LANDING_AREA` authority;
- departure state `HOLD_SHORT` or `LINE_UP_AND_WAIT`;
- canonical runway occupancy/freshness suitable for positive clearance;
- canonical runway reservation and conflict handling;
- issuance of the existing `takeoff_clearance` `OperationalInstruction`.

The adapter classifies missing authority or unknown/stale runway context as
`unavailable`. Occupied/closed/reserved runway, conflicting reservation or an
incompatible departure state is `hold`. Only the existing Tower instruction and
resulting `TAKEOFF_CLEARED` state is `granted`.

## Protected semantics and Pilot extension

The Pilot catalog remains code-seeded, immutable and experimental/non-normative.
It gains three exact ATC entries plus the profile-aware clarification required
by the fail-closed path and now contains 29 entries:

- `atc-takeoff-clearance-granted`;
- `atc-takeoff-hold`;
- `atc-takeoff-context-unavailable`.

The takeoff entries select the existing `FAP_RUSSIAN_ATC` profile while
remaining explicitly experimental/non-normative; this is an architecture
selector and not a claim of verified ФАП-414 wording. All three require exact protected `atc.callsign` (`CALLSIGN`) and
`atc.runway_id` (`RUNWAY`) values. The adapter copies these values from the ATC
session identity and departure session. It creates exactly one authoritative
ATC decision provenance reference. The resolver remains value-preserving and
fail-closed.

These synthetic phrases prove architecture only. They make no claim of ICAO,
FAA, NATO, Russian national, military or local ATC normative compliance.

## Approved bounded corpus

Russian:

1. `Добрый день! Разрешите взлёт.`
2. `Разрешите взлёт.`
3. `Можно взлетать?`
4. `Башня, готов к взлёту.`
5. `Готов к взлёту, разрешите взлёт.`
6. `Запрашиваю разрешение на взлёт.`

English:

1. `Tower, request takeoff clearance.`
2. `Ready for takeoff.`
3. `Request takeoff.`
4. `Tower, Viper 2-1 ready for departure.`

The implementation is bounded by semantic cues rather than a literal lookup of
only these ten strings, but it deliberately has no generic NLU, LLM, embeddings,
fuzzy fallback or provider call.

## Offline deterministic Probe

Run:

```text
python -m orion.golden_takeoff_probe --output-dir <runtime-directory>
```

The Probe runs 18 cases: all ten approved variants with a permitted runway, two
blocked cases, two unavailable-context cases, two unsupported cases and two
ambiguous cases. A second fresh vertical run must reproduce the same canonical
chain. The evidence bundle contains `manifest.txt`, `summary.json`,
`cases.jsonl` and the exact Pilot `catalog.json`.

Each supported case records intent, typed ATC decision, semantic unit, protected
values, selected Pilot entry, rendered fragment and final ATC state. Unsupported
cases record the intentional stop before decision/rendering.

The independent validator must detect all eleven mandatory corruptions:

1. granted rendered as hold;
2. denied rendered as clearance;
3. wrong callsign;
4. wrong runway;
5. dropped protected slot;
6. fabricated protected slot;
7. wrong phrase entry;
8. unsupported input misclassified;
9. ambiguous input granted;
10. duplicate result;
11. dropped result.

`GOLDEN VERTICAL PASS` requires 18/18 cases, 11/11 corruption self-tests,
fresh-run semantic determinism, exact protected values, correct ATC state and a
complete chain for every supported result. Executed failure returns
`GOLDEN VERTICAL FAIL`.

## Explicitly deferred

No live/provider/SRS/DCS/audio path is added. Production interaction routing,
speech recognition, Qwen/Realtime/SpeechKit, presentation composition, radio
transport and Launcher integration remain deferred. The first future live
vertical should reuse this protected fragment after a separately approved
speech-input boundary and existing presentation/radio path; it must not move the
takeoff decision into a model or provider.
