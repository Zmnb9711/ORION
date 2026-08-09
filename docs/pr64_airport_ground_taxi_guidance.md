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

## Safety invariants
1. Hold-short and runway-boundary constraints override convenience/navigation prompts.
2. A turn-by-turn prompt cannot authorize entry into a protected runway resource.
3. Unknown/stale position or topology cannot produce falsely precise guidance.
4. Route revisions preserve/supersede safety constraints explicitly and are audit-visible.
5. Pilot deviation triggers re-evaluation/replanning; ORION does not silently pretend the aircraft remains on the old route.
6. `RUNWAY_VACATED` gates taxi-in Ground continuation.
7. All safety-critical instructions remain acknowledgement-aware under existing Virtual ATC Core rules.

## Initial implementation boundary
PR #64 will build the generic Ground taxi navigation engine and tests above the existing airport surface model. DCS-specific extraction for every individual airfield may be supplied incrementally by adapters/data packs; the generic engine must support full, partial and degraded topology from the start.

## Explicitly deferred
- full Airport Departure procedural engine;
- full Approach/Arrival procedural engine;
- broad DCS-specific phraseology expansion;
- visual map/UI rendering;
- exhaustive hand-authored topology for every DCS airfield.
