# ORION Fixed-Airfield ATC — Ground / Tower Detailed Design

Status: detailed design before merging Virtual ATC Core #61

## Purpose
Define the safety-critical airport surface and runway-control model before procedural implementation. Ground and Tower are separate logical authorities even when a DCS airfield exposes one frequency.

## Core invariants
1. Taxi clearance is not runway-crossing authority.
2. Runway crossing is explicit, runway-specific, acknowledgement-sensitive, and revocable until physical commitment.
3. `LINE_UP_AND_WAIT` is not takeoff clearance.
4. Takeoff and landing clearances are runway-specific and require known-enough runway/resource state.
5. Unknown/stale occupancy is never interpreted as clear.
6. Ground does not own active-runway movement authority; Tower/Local does.
7. Authority transfer is event/acknowledgement gated; frequency tuning alone changes nothing.
8. A clearance cannot silently mutate after a runway configuration or taxi-route version change.
9. Committed traffic is protected unless safety requires intervention.
10. Every safety-critical decision records reason and evidence/freshness.

## Aerodrome surface model
`AerodromeSurfaceState` contains versioned runway and taxi topology plus freshness/capability. Runway resources are first-class objects with identity, geometry, operational direction/configuration, availability, occupancy evidence, crossing points, entry/exit points and closure state. Taxi resources include parking/apron nodes, taxiway segments, intersections, holding points and runway boundaries where known.

The model supports degraded topology. If DCS does not expose reliable taxiway names/connectivity, ORION may provide coarse guidance only and must not fabricate named routes.

## Surface session states
Departure surface flow:
`PARKED -> STARTUP_APPROVED -> TAXI_CLEARED -> TAXIING -> HOLDING_POINT -> READY_FOR_DEPARTURE -> LINE_UP(optional) -> TAKEOFF_CLEARED -> TAKEOFF_ROLL -> AIRBORNE`

Arrival surface flow:
`LANDING_ATTEMPT -> LANDED -> ROLLOUT -> RUNWAY_EXITING -> RUNWAY_VACATED -> GROUND_HANDOFF -> TAXI_IN -> PARKED`

Crossing subflow:
`CROSSING_REQUESTED -> HOLD_SHORT -> CROSSING_CLEARED -> CROSSING_COMMITTED -> CROSSING_COMPLETE`

A session can carry emergency/lost-comms/degraded overlays without losing its procedural state.

## Taxi route contract
`TaxiRoute` is versioned and structured:
- route/session/facility identity
- origin and destination
- ordered known surface segments
- holding points
- explicit runway crossings
- blocked/unknown segments
- issued/revised timestamps
- topology/configuration version
- reason

Any material route revision supersedes the prior route and requires acknowledgement when safety-relevant constraints change. A pilot deviation, closure, runway change, conflicting traffic or stale topology can invalidate the active route.

## Hold-short contract
`HoldShortConstraint` binds a session to a specific protected boundary/resource. It remains active until explicitly cancelled/replaced or an authorized crossing/entry transaction becomes committed. Readback policy is strict for runway boundaries.

ORION must detect attempted boundary crossing against an active hold-short constraint when telemetry supports it and issue an urgent safety call.

## Runway crossing transaction
A crossing is a resource transaction, not a phrase string. Required fields:
- session and runway
- entry/crossing point if known
- requested/cleared/committed/completed timestamps
- controlling Tower authority
- conflicting runway reservations
- acknowledgement state
- evidence/freshness

Ground may route an aircraft to the boundary but cannot grant crossing authority. Tower grants the crossing after conflict evaluation. Once physical crossing is committed, cancellation semantics change from ordinary revocation to safety intervention.

## Runway occupancy manager
`RunwayOccupancyManager` maintains conservative runway state from all available evidence:
- aircraft/vehicle on runway geometry
- takeoff roll
- landing/rollout
- crossing transaction
- line-up occupancy
- known DCS runway events
- reservations for imminent committed operations
- stale/unknown evidence

States should distinguish at least `CLEAR`, `OCCUPIED`, `RESERVED`, `UNKNOWN`, `STALE`, `CLOSED`. Only sufficiently fresh `CLEAR` plus conflict checks can support a positive runway-clear assertion.

## Tower departure state machine
`READY_FOR_DEPARTURE -> HOLD_SHORT | LINE_UP_AND_WAIT -> TAKEOFF_CLEARED -> TAKEOFF_ROLL -> AIRBORNE -> DEPARTURE_HANDOFF`

Tower evaluates runway occupancy, arrival/departure/crossing reservations, wake/separation policy where modeled, runway configuration and session commitment. `LINE_UP_AND_WAIT` reserves/occupies runway space and blocks conflicting clearances according to policy. Takeoff clearance is not issued when occupancy/conflict evidence is unknown or stale beyond policy.

A rejected takeoff is a first-class branch: `TAKEOFF_ROLL -> REJECTED_TAKEOFF -> RUNWAY_OCCUPIED/EMERGENCY_ASSESSMENT -> EXIT/HOLD/ASSISTANCE`.

Airborne is an irreversible physical event suitable for event-gated Tower -> Departure traffic-authority handoff.

## Tower arrival state machine
`TOWER_HANDOFF -> FINAL -> LANDING_CLEARED | CONTINUE/DELAY -> LANDING_ATTEMPT -> LANDED/GO_AROUND -> ROLLOUT -> RUNWAY_VACATED`

Approach clearance never implies landing clearance. Tower evaluates runway occupancy/reservations and conflicting departures/crossings. A landing clearance remains associated with one runway/configuration version.

Go-around is first-class and can be triggered by pilot action, runway conflict, loss of safe state, traffic, runway change or mission policy. It preserves the same ATC session and creates/reuses appropriate Approach/Departure coordination rather than creating a new aircraft identity.

## Runway change
`RunwayConfiguration` is versioned. Change triggers:
- invalidate/re-evaluate non-committed takeoff/landing clearances
- replan taxi routes/holding points
- resequence arrivals/departures
- preserve physically committed operations unless safety demands intervention
- record reason and old/new configuration

No clearance silently changes runway number after issuance.

## Conflict classes and deterministic response
Priority conflict classes:
- occupied runway vs takeoff/landing/crossing
- arrival vs departure reservation
- crossing vs takeoff/landing
- line-up vs landing/crossing
- two crossing transactions
- opposite-direction runway use
- taxi intersection/head-on/deadlock
- runway incursion
- go-around path vs departure traffic
- helicopter operation vs runway/fixed-wing protected area

Resolution order: protect irreversible/physically committed traffic; protect immediate emergencies; stop/suspend non-committed clearances; resequence remaining traffic; degrade to explicit uncertainty when evidence is insufficient. Never solve uncertainty by assuming clearance.

## Multiple aircraft
Surface planning is resource-based rather than per-aircraft isolated scripts. Taxi segments, intersections, holding points and runway boundaries can be reserved or conflict-checked. Deadlock detection should identify opposing route claims where topology is available. Sequencing decisions use common priority and commitment primitives and remain deterministic/explainable.

## Helicopter operations
Helicopters require a distinct procedure adapter while sharing surface/runway resources. Supported modes may include parking departure, ground taxi, air taxi, runway takeoff/landing and runway-independent pads/FARPs when represented by mission/topology data. ORION must not force every helicopter through fixed-wing runway states. Any operation intersecting protected runway/local-control space still requires Tower authority.

## Voice / readback behavior
Safety-critical items receive concise phraseology and strict acknowledgement handling: runway designator, hold short, crossing, line-up, takeoff, landing, go-around and route changes affecting runway boundaries. Casual conversation and non-critical speech are pre-empted by runway safety calls. Free-form pilot language is accepted but normalized to structured intents/transactions.

## DCS adapter boundary
`AirportDcsAdapter` supplies observations and optionally mirrors native DCS actions. It does not own ATC policy. If native DCS cannot represent a richer ORION transaction, ORION retains its own state and marks synchronization capability/result explicitly. Native fallback must not erase ORION audit history.

## Required pre-implementation tests
Before implementation is considered complete, tests must cover:
1. taxi clearance cannot authorize runway crossing implicitly;
2. active hold-short survives unrelated taxi updates;
3. crossing cannot be cleared against committed takeoff/landing;
4. unknown/stale runway occupancy blocks positive clearance;
5. line-up does not imply takeoff;
6. runway change invalidates/replans non-committed clearances without mutating them silently;
7. rejected takeoff keeps runway protected;
8. go-around preserves session and coordinates downstream authority;
9. runway-vacated event gates Tower -> Ground transition;
10. airborne event gates Tower -> Departure transition;
11. two aircraft cannot exclusively own the same protected resource incompatibly;
12. committed traffic cannot be displaced by ordinary priority;
13. emergency can pre-empt/resequence non-committed traffic;
14. helicopter runway-independent flow does not unnecessarily acquire runway authority;
15. helicopter crossing/protected-area conflict still requires Tower authority;
16. all safety-critical transitions produce reasoned audit events.

## Implementation boundary
These are airport-domain rules above Virtual ATC Core. Generic authority, instructions, acknowledgement, priority, commitment, overlays, event history and simulator-sync remain in #61; detailed surface/runway procedure engines should be implemented after the design audit is frozen.
