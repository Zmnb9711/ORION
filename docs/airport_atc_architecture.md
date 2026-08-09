# ORION Fixed-Airfield ATC Architecture

Status: design baseline following Virtual ATC Core #61

## Goal
ORION is the pilot-facing ATC interface at fixed airfields. Normal operation is voice-first and does not require the pilot to navigate the native DCS radio menu. Native DCS ATC remains a simulator backend/fallback when synchronization is required or ORION lacks a capability.

## Sources and fidelity policy
The architecture is informed by current FAA AIM / JO 7110.65 terminal concepts and official DCS aircraft/user manuals describing native ATC behavior. ORION should use realistic military/ICAO-style terminology where appropriate, but DCS-observable state and mission configuration remain authoritative for simulator behavior. Missing simulator data stays unknown; ORION must not invent runway, clearance, traffic, weather, or navigation-aid state.

## Controller agencies
Fixed-airfield ATC is not one monolithic Tower agent. Logical agencies include:
- ATIS / aerodrome information
- Clearance Delivery where applicable
- Ground
- Tower / Local Control
- Departure
- Approach / Arrival
- Precision Approach / PAR where mission/capability supports it

Small or simple DCS airfields may collapse multiple logical agencies onto one frequency/voice while preserving distinct authority scopes internally.

## Shared aerodrome operational state
`AerodromeOperationalState` is the facility source of truth and should include:
- mission/facility identity and coalition/access policy
- runway inventory and geometry
- active/departure/arrival runway configuration with reason
- runway occupancy and incursion/conflict state
- taxiway/parking topology and known closures
- wind/weather/QNH/QFE/visibility where observable
- ATIS/information code where modeled
- tower/ground/approach/departure frequencies
- ILS/TACAN/NDB/other approach capability where known
- traffic picture and freshness/confidence/capability flags

Unknown runway/occupancy state must never be interpreted as clear.

## Departure session
A normal departure preserves one ATC session across agencies:

`PARKED -> STARTUP_REQUESTED -> STARTUP_APPROVED -> TAXI_REQUESTED -> TAXI_CLEARED -> TAXIING -> HOLD_SHORT -> READY_FOR_DEPARTURE -> LINE_UP_AND_WAIT(optional) -> TAKEOFF_CLEARED -> TAKEOFF_ROLL -> AIRBORNE -> DEPARTURE_CONTROLLED -> HANDED_OFF`

Alternative overlays/branches include delay, runway change, taxi reroute, rejected takeoff, emergency, lost comms, native fallback and session cancellation.

### Startup / clearance delivery
ORION may provide startup approval, local departure information and mission-derived route/clearance data when supported. Route clearance and traffic-control authority are separate from conversational acknowledgement. Any safety-critical clearance requiring readback uses the common acknowledgement-aware instruction lifecycle.

### Ground movement
Ground owns taxi/movement authority outside runway/local-control scope. Taxi clearance is structured as a route, not only speech:
- origin/parking position
- destination runway/holding point
- ordered taxiway segments where topology is available
- runway crossings
- hold-short constraints
- route version/reason

Progressive taxi is supported when requested or when topology/traffic complexity warrants it. ORION must not fabricate taxiway names or a route when the map topology is unavailable; degraded guidance should say what is actually known.

### Runway crossing and hold short
Runway crossing is an explicit operational instruction and resource conflict boundary. A taxi clearance never implicitly authorizes crossing a runway unless that crossing is explicitly represented by policy. Hold-short instructions are acknowledgement-sensitive and remain active until released/replaced.

### Tower / departure
Tower owns runway/local traffic authority. Takeoff clearance is runway-specific and requires known-enough runway state. `LINE_UP_AND_WAIT` is distinct from takeoff clearance. After an irreversible airborne event, event-gated handoff can transfer `FLIGHT_TRAFFIC` authority from Tower to Departure while Tower retains runway authority.

## Arrival session
A normal arrival preserves one ATC session across agencies:

`INBOUND -> APPROACH_CHECKED_IN -> ARRIVAL_SEQUENCED -> APPROACH_ASSIGNED -> APPROACH_CLEARED -> FINAL -> TOWER_HANDOFF -> LANDING_CLEARED -> LANDING_ATTEMPT -> LANDED -> RUNWAY_VACATED -> GROUND_HANDOFF -> TAXI_IN -> PARKED`

Branches include visual approach, instrument approach, overhead/military pattern, go-around/missed approach, runway change, emergency, divert and lost comms.

### Approach / Arrival
Approach owns arrival sequencing and terminal separation within its scope. It may issue headings, altitudes, vectors, approach assignments and sequence information only when the corresponding data/capability is available. Visual acquisition is evidence-based; geometry alone does not fabricate a pilot visual report.

### Tower arrival authority
Tower owns landing/runway authority. Approach clearance is not landing clearance. Landing clearance is runway-specific and depends on runway/traffic state. Handoff from Approach to Tower is explicit; frequency tuning alone is not proof of transfer.

### After landing
The aircraft remains under Tower until runway-vacated evidence or an explicit policy transition. Ground authority begins through a handoff; ORION should not issue conflicting Tower and Ground taxi instructions. Taxi-in uses the same structured ground-route model as departure.

## Traffic patterns and military operations
The airport engine must support more than straight-in civilian arrivals. Procedure adapters may model:
- standard left/right visual patterns
- overhead break / military pattern
- straight-in
- instrument approaches
- touch-and-go / stop-and-go / low approach where mission policy allows
- helicopter ground/air taxi and runway-independent operations where topology/capability supports them

These are procedure-domain engines layered above Virtual ATC Core, not hard-coded into generic authority primitives.

## Runway configuration policy
Active runway selection is an explicit policy decision based on mission-authoritative configuration first, then observable wind/weather, runway availability, traffic and procedure constraints. A runway change is a versioned operational event that triggers re-evaluation of taxi routes, departure queues and arrival sequencing. Committed traffic is protected unless safety requires intervention.

## Sequencing and conflicts
Airport sequencing reuses common `TrafficPriority`, `CommitmentState`, `TrafficConflict` and resource-assignment primitives. Conflict classes include:
- runway occupancy/incursion
- departure vs arrival runway conflict
- crossing vs takeoff/landing conflict
- duplicate runway/resource assignment
- taxi-route intersection/deadlock where topology permits detection
- arrival sequence loss
- go-around/missed-approach conflict
- controller authority conflict

If separation or runway clearance cannot be established from available state, ORION suspends the affected clearance rather than assuming safety.

## Emergency / lost comms / divert
Emergency, critical fuel, lost comms and degraded simulator integration are overlays preserving the procedural state. Emergency priority can resequence non-committed traffic. Lost-comms traffic remains in the traffic picture and its expected protected space is retained. Divert is a structured plan/transaction, not merely a spoken suggestion.

## Voice behavior
Each logical agency can have a distinct voice identity. Stable state is silent. Readbacks/acknowledgements, hold-short, runway, altitude, heading and approach-clearance elements use bounded retry/correction policy. Urgent safety calls pre-empt casual conversation. Free-form pilot language is normalized into structured ATC intents; phraseology is not required to be exact for recognition.

## DCS-native compatibility
Official DCS manuals expose a simpler context-sensitive native ATC flow including engine-start permission, taxi-to-runway, takeoff request, `Inbound`, and lost-aircraft guidance. ORION should cover that baseline but is intentionally richer.

Pilot-facing target:
`Pilot <-> ORION <-> DCS adapter`

not mandatory manual traversal of the native DCS F-menu. `AirportDcsAdapter` may mirror/synchronize native DCS actions when technically necessary. Unsupported/failed/unknown synchronization uses the common integration-mode degradation/fallback model.

## Proposed domain modules after #61
- `AerodromeStateProvider`
- `AirportOpsDirector`
- `AirportSessionStore`
- `AirportTrafficSequencer`
- `AirportGroundController`
- `AirportTowerController`
- `AirportDepartureController`
- `AirportApproachController`
- `AirportPrecisionApproachController`
- `TaxiRoutePlanner`
- `RunwayOccupancyManager`
- `AirportVoiceRouter`
- `AirportDcsAdapter`

## Recommended implementation order
1. Aerodrome state/runway model and capability/freshness.
2. Ground startup/taxi/hold-short engine and structured taxi routes.
3. Tower runway occupancy, line-up, takeoff and landing authority.
4. Departure and Approach handoffs/sequencing.
5. Visual/overhead pattern engine.
6. Instrument approach and missed-approach engine.
7. PAR/precision military approach where supported.
8. Emergency/divert/lost-comms and multi-aircraft stress tests.
9. DCS adapter synchronization and end-to-end voice integration.

## Design invariant
The pilot talks to ORION. Controllers remain logically distinct, authority is scope-based, instructions are stateful, simulator facts are capability/freshness-gated, and native DCS ATC is a backend/fallback rather than the required user interface.