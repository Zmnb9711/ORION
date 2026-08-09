# ORION Fixed-Airfield ATC Cross-Document Audit

Status: canonical audit before merging Virtual ATC Core #61

## Scope reviewed
This audit reconciles:
- `docs/airport_atc_architecture.md`
- `docs/airport_atc_ground_tower_detailed_design.md`
- `docs/airport_atc_departure_approach_detailed_design.md`
- Virtual ATC Core #61 common authority/instruction/session primitives

## Audit result
No blocking procedural contradiction remains between surface, runway and airborne terminal-control designs. Two common-core authority gaps were identified and must be corrected before merge: a domain-neutral surface-movement authority scope and a domain-neutral route/clearance authority scope.

## Canonical authority model
The fixed-airfield authority model is scope-based, not one global controller owner.

Required generic scopes:
- `ROUTE_CLEARANCE`: route/departure clearance authority that may be held by Clearance Delivery or another configured agency without granting movement authority.
- `SURFACE_MOVEMENT`: taxi/apron/movement-area traffic authority outside protected runway/local-control space.
- `FLIGHT_TRAFFIC`: airborne/local flight-traffic authority and local pattern sequencing as appropriate.
- `LANDING_AREA`: protected runway/landing-area authority including runway entry/crossing/takeoff/landing availability.
- `FINAL_GUIDANCE`: precision/final guidance where a dedicated controller such as PAR owns that guidance function.
- existing domain-neutral tactical/resource scopes remain available where applicable.

Canonical normal ownership examples:
- Clearance Delivery: `ROUTE_CLEARANCE`
- Ground: `SURFACE_MOVEMENT`
- Tower/Local on surface runway operations: `LANDING_AREA`; Tower may additionally own `FLIGHT_TRAFFIC` for local/pattern traffic.
- Departure: `FLIGHT_TRAFFIC` after airborne handoff.
- Approach/Arrival: `FLIGHT_TRAFFIC` in terminal arrival control.
- PAR/precision controller: `FINAL_GUIDANCE` while Approach/Tower retain their other scopes.

One agency may hold several scopes; different agencies may simultaneously hold distinct scopes. Two agencies may not own the same exclusive scope for the same session.

## Canonical handoff gates
- Clearance Delivery -> Ground transfers relevant control context but does not automatically grant runway authority.
- Ground -> Tower for departure is acknowledgement/procedure gated at the runway/local-control boundary.
- Tower -> Departure `FLIGHT_TRAFFIC` transfer is event-gated by reliable `AIRBORNE` evidence.
- Approach -> Tower transfer is explicit; frequency tuning alone is not proof.
- Tower -> Ground after landing is gated by reliable `RUNWAY_VACATED` evidence or equivalent configured event.
- Go-around/missed approach creates explicit Tower -> Approach/Departure coordination while preserving session identity.
- PAR handoff transfers only `FINAL_GUIDANCE` unless configuration explicitly transfers another scope.

## Canonical runway/resource model
A runway is a protected resource with versioned configuration and occupancy/reservation state. `UNKNOWN`/`STALE` never mean clear. Ground taxi routing may approach a runway boundary but crossing/entry requires `LANDING_AREA` authority and a dedicated transaction.

`LINE_UP_AND_WAIT`, crossing, takeoff and landing are distinct runway transactions/instructions. None implies another.

Runway/configuration changes supersede non-committed clearances explicitly; committed/irreversible operations are protected unless safety demands intervention.

## Canonical procedural continuity
A single ATC session survives controller changes and normal branches. Rejected takeoff, go-around, missed approach, immediate return, emergency, lost comms, native fallback and runway change do not create a new aircraft/session identity.

Emergency, critical fuel, lost comms and degraded simulator integration remain overlays preserving procedural state.

## Clearance Delivery and ATIS
ATIS is informational and does not require movement authority. It may expose weather/runway/configuration information only when capability/freshness permits.

Clearance Delivery owns route/departure clearance semantics through `ROUTE_CLEARANCE`; it does not grant taxi, runway crossing, takeoff or landing authority. At small airfields the same voice/frequency may implement several agencies, but authority scopes remain logically separate.

## Ground / surface movement
Ground owns `SURFACE_MOVEMENT`. Taxi routes are versioned structured data. Runway crossing is not implicit in taxi clearance. Hold-short constraints persist until explicitly released/replaced or an authorized crossing/entry becomes committed.

Surface conflict detection is resource-based and may cover segment/intersection conflicts, head-on claims, deadlock and runway-boundary incursions when topology/telemetry allows.

## Tower / local control
Tower owns `LANDING_AREA` and may own local `FLIGHT_TRAFFIC`. Tower decides runway entry/crossing/line-up/takeoff/landing/go-around safety transactions. Tower does not fabricate a clear runway from missing evidence.

## Departure / Approach
Departure and Approach reuse `FLIGHT_TRAFFIC` with explicit non-overlapping ownership transitions. Arrival sequencing and departure sequencing share common priority/commitment primitives but remain domain procedure engines.

Visual acquisition and traffic-in-sight are evidence-based. Instrument and PAR capabilities are capability/freshness-gated.

## PAR / precision approach
PAR is a distinct final-guidance authority domain. `FINAL_GUIDANCE` permits a precision controller to issue high-frequency corrections while Approach/Tower retain flight-traffic and landing-area authority. Stale precision geometry immediately removes the basis for precision guidance.

## Helicopters
Helicopters share common authority/resources but use a distinct procedure adapter. Runway-independent operations do not require `LANDING_AREA` when they remain outside protected runway/local-control space; any runway/protected-area interaction does.

## Multi-aircraft conflict policy
Canonical priority order:
1. protect irreversible/physically committed traffic;
2. immediate emergency/safety condition;
3. critical fuel/high-priority traffic;
4. committed reservations/sequence;
5. normal sequence/order.

Uncertainty is resolved conservatively by withholding/suspending new clearances, not by assuming separation or resource availability.

## Simulator integration
Pilot-facing target remains `Pilot <-> ORION <-> DCS adapter`. Native DCS ATC is backend/fallback. Adapter observations are capability/freshness tagged and do not own policy. Unsupported native synchronization must not collapse ORION's richer state or erase audit history.

## Common-core corrections required before merge #61
1. Add `SURFACE_MOVEMENT` to `ControllerAuthorityScope`.
2. Add `ROUTE_CLEARANCE` to `ControllerAuthorityScope`.
3. Add agencies for `AIRPORT_CLEARANCE_DELIVERY` and `AIRPORT_PAR` (or equivalent generic configurable agency identity) so procedure engines do not overload Ground/Approach identities.
4. Add regression tests proving different agencies can simultaneously hold `ROUTE_CLEARANCE`, `SURFACE_MOVEMENT`, `LANDING_AREA`, `FLIGHT_TRAFFIC`, and `FINAL_GUIDANCE` without conflict, while duplicate ownership of the same scope remains forbidden.
5. Preserve all existing carrier semantics; the new scopes must be additive and domain-neutral.

## Freeze gate
Airport ATC design is ready to freeze after the common-core corrections above pass CI. Implementation of airport procedure engines should then begin in a subsequent PR, not inside the generic core PR.
