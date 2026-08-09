# PR #64 — Airport Ground Taxi Guidance & Navigation

## Goal
Complete the fixed-airfield Ground ATC surface-navigation layer before moving deeper into airborne Departure/Approach procedures.

ORION must be able to dispatch and assist an aircraft continuously from parking/stand to the runway holding point and, after landing and confirmed runway vacation, from the runway exit to parking/stand.

## Required capabilities
- surface graph/topology representation for parking/apron nodes, taxiway segments, intersections, holding points, runway boundaries and runway exits;
- current-position matching against known surface topology with explicit confidence/freshness;
- route planning from parking/stand to departure holding point;
- route planning from runway exit to assigned/requested parking/stand;
- ordered turn-by-turn guidance derived from the active `TaxiRoute`;
- proactive prompts for meaningful upcoming actions: turn, continue, hold position, hold short, runway boundary and destination arrival;
- free-form taxi questions such as `куда дальше?`, `здесь направо?`, `где остановиться?`, `какой следующий поворот?`, `это Alpha?`, `где holding point?`, `как доехать до стоянки 14?`;
- deviation detection and route replanning when position/topology evidence is sufficient;
- parking/stand selection or acceptance of a pilot-requested destination;
- integration with existing `SURFACE_MOVEMENT`, `TaxiRoute`, hold-short and runway-crossing safety contracts;
- deterministic, audit-visible decisions and regression tests.

## Guidance modes
### ATC mode
Ground issues normal taxi clearances and safety-critical instructions. A taxi clearance never implies runway crossing authority.

### Navigation-assist mode
ORION may additionally provide concise orientation cues such as `next right`, `second left`, distance-to-turn when reliable, or `stop before the runway holding point`.

Both modes share the same active route and safety constraints; navigation assistance cannot weaken an ATC restriction.

## Degraded topology invariant
ORION must never invent taxiway names or exact geometry. If DCS/mission/static airport data cannot support a named route with adequate confidence, guidance degrades explicitly to reliable geometric/relative cues only. If even those cues are uncertain, ORION must say that position/route confidence is insufficient rather than fabricate directions.

### Deliberate runway-number exception
A runway numeric designator is not treated as fabricated when ORION derives it from a sufficiently reliable magnetic runway course. This is a deliberate exception to the general degraded-topology rule because runway numbers are conventionally derived from magnetic direction.

Source precedence:
1. published/authoritative runway designator when available;
2. DCS/mission runway designator when reliable;
3. `DERIVED_MAGNETIC` numeric designator computed from a reliable magnetic runway course.

The numeric designator is the magnetic course rounded to the nearest ten degrees and expressed as `01..36`; north is `36`, never `00`. The reciprocal runway direction is derived independently from the reciprocal magnetic course. `L/C/R` suffixes are never inferred from course alone: they require authoritative data or known parallel-runway geometry/order.

A `DERIVED_MAGNETIC` numeric designator is valid for normal ATC phraseology, including instructions such as `hold short runway 27`.

## Aerodrome information layer
Runway identity/course and pressure information are cross-domain aerodrome data, not Ground-only state. Ground, Tower, Departure, Approach and free-form conversational modes must consume one shared aerodrome-information contract.

### Runway heading information service — forward contract
Runway identity/course data must be reusable outside Ground ATC. Future Departure/Approach/free-flight integrations must expose a general query that can answer, for any known aerodrome and runway, questions such as:
- `какой курс полосы?`
- `какой курс ВПП 27 в Батуми?`
- `runway heading?`
- `what is the magnetic course of runway 09?`

The answer must be available while taxiing, airborne, or on approach and should return the exact known/derived magnetic runway course, not merely `designator * 10`. When useful and available, ORION may also return reciprocal runway, true course and source/confidence. The query must not depend on the aircraft currently being at that aerodrome.

### Aerodrome pressure information service — forward contract
ORION must also answer pressure questions for any known aerodrome regardless of the aircraft's current location or phase of flight.

Default interpretation of `какое давление на аэродроме?` is current **QNH**. Explicit requests may ask for QFE. Responses should expose common units (`hPa`, `inHg`, and when useful `mmHg`) plus observation time, source, freshness and confidence.

Pressure is dynamic meteorological information and must come from a runtime observation/source such as DCS environment/weather, mission weather, ATIS/METAR-like data or another trusted adapter. ORION must never synthesize a current QNH merely from aerodrome geometry/elevation. Stale pressure may be reported only with an explicit stale/uncertain indication and must not be presented as fresh.

QFE may be aerodrome- or runway/threshold-specific when that datum is available. `STANDARD` (`1013.25 hPa` / `29.92 inHg`) is a separate flight-level altimeter setting and must never be substituted as the answer to a normal aerodrome-QNH request.

Representative free-form queries include:
- `какое давление в Батуми?`
- `QNH Кутаиси?`
- `дай QFE полосы 07`
- `какое давление поставить?`
- `pressure at Senaki?`

#64 establishes the shared pressure answer/observation contract; later airborne ATC integrations must consume the same contract rather than create separate pressure stores.

## Safety invariants
1. Hold-short and runway-boundary constraints override convenience/navigation prompts.
2. A turn-by-turn prompt cannot authorize entry into a protected runway resource.
3. Unknown/stale position or topology cannot produce falsely precise guidance.
4. Route revisions preserve/supersede safety constraints explicitly and are audit-visible.
5. Pilot deviation triggers re-evaluation/replanning; ORION does not silently pretend the aircraft remains on the old route.
6. `RUNWAY_VACATED` gates taxi-in Ground continuation.
7. All safety-critical instructions remain acknowledgement-aware under existing Virtual ATC Core rules.
8. Reliable magnetic runway course may be used to derive the numeric runway designator even when painted/explicit runway-number data is absent.
9. Parallel-runway suffixes `L/C/R` are never guessed from magnetic course alone.
10. Dynamic aerodrome pressure must retain source/freshness; stale/unknown pressure is never silently treated as current.
11. Standard pressure is not aerodrome QNH.

## Initial implementation boundary
PR #64 will build the generic Ground taxi navigation engine and tests above the existing airport surface model. DCS-specific extraction for every individual airfield may be supplied incrementally by adapters/data packs; the generic engine must support full, partial and degraded topology from the start.

## Explicitly deferred
- full Airport Departure procedural engine;
- full Approach/Arrival procedural engine;
- broad DCS-specific phraseology expansion;
- visual map/UI rendering;
- exhaustive hand-authored topology for every DCS airfield.
