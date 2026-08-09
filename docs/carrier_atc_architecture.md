# ORION Carrier ATC Architecture

Status: design baseline before Virtual ATC Core (#61)

## Goal

Carrier aviation is modeled as a first-class ATC domain, not as an airport with a moving runway. The subsystem must support launch, recovery, sequencing, handoff, moving-reference geometry, distinct controller roles/voices, and safe degradation when DCS data is incomplete.

## Control roles

ORION models separate carrier control agencies sharing one operational picture:

- Air Boss / PriFly: overall flight-deck and visual flight operations state.
- Departure: post-catapult departure control and routing/handoff.
- Marshal: inbound check-in, holding, sequencing, expected approach time and fuel awareness.
- Approach: instrument/procedural approach control, separation and final approach handoff.
- Tower / PriFly: visual pattern control near the carrier and landing-area availability.
- LSO: final landing guidance, ball-call handling, corrections, waveoff/bolter logic and grading events.
- Deck / Catapult coordinator: deck movement, catapult assignment/readiness and launch state. This is operational coordination, not a generic radio ATC role.

Each audible agency must have a distinct VoiceAgent/voice identity. LSO must be especially distinct and able to pre-empt ordinary ATC chatter for safety-critical calls.

## Shared carrier operational state

`CarrierOperationalState` should be the single moving-reference source of truth consumed by all carrier controllers. Required fields:

- mission_id, carrier unit_id/name/type
- position, heading, ground velocity and timestamp
- BRC (base recovery course)
- expected/actual final bearing where available or derivable
- wind direction/speed and wind-over-deck estimate when data is available
- current recovery case: CASE_I / CASE_II / CASE_III
- current cycle: IDLE / LAUNCH / RECOVERY / MIXED / SUSPENDED
- landing area state: CLEAR / FOUL / UNKNOWN
- launch availability and catapult states when exposed by DCS
- TACAN channel/callsign
- ICLS/ACLS/PALS capabilities and channels when known
- carrier ATC frequencies when known
- visibility/ceiling/time-of-day inputs used to select or validate recovery case
- data freshness/confidence flags; unknown values must remain unknown rather than invented

All geometry is computed relative to the current carrier state. Marshal fixes, radial/DME positions, pattern references, final course, departure gates and handoff boundaries must move with the ship.

## Recovery case selection

Case selection is policy, not a hard-coded assumption. ORION should consume mission/environment data and carrier configuration, then expose both the selected case and the reason.

Baseline rules for the DCS/Navy-compatible policy layer:

- CASE I: visual daytime recovery under suitable ceiling/visibility.
- CASE II: instrument penetration/arrival with a visual transition near the ship when conditions permit.
- CASE III: instrument recovery for night and/or lower weather conditions.

Mission designers or explicit carrier state may override auto-selection. ORION must never silently change a mission-authoritative case solely because one weather input is missing.

## Aircraft recovery session

Each inbound aircraft receives a mission-scoped `CarrierRecoverySession` with at least:

- session_id, mission_id, carrier_id
- aircraft_id/callsign/type
- fuel state and emergency/bingo flags when known
- assigned recovery case
- assigned marshal radial/DME/altitude or visual holding slot
- expected approach time (EAT) when applicable
- sequence number / traffic relationship
- current controller agency
- current state
- timestamps for last pilot/controller transmission and last state transition
- bolter count, waveoff count, divert state
- stale-data and lost-comms state

A session is invalidated on mission change, carrier identity change, aircraft destruction/despawn, explicit divert/abort completion, or timeout policy.

## Common recovery state machine

Common high-level states:

`INBOUND -> CHECKED_IN -> ASSIGNED -> HOLDING -> COMMENCING -> APPROACH -> FINAL -> LANDING_ATTEMPT -> RECOVERED`

Alternative terminal paths:

`LANDING_ATTEMPT -> BOLTER -> RESEQUENCE`

`FINAL/LANDING_ATTEMPT -> WAVEOFF -> RESEQUENCE`

`* -> EMERGENCY_PRIORITY`

`* -> DIVERTED`

`* -> LOST_COMMS`

Case-specific engines refine these states without duplicating shared session identity, traffic priority or handoff logic.

## CASE I engine

Primary requirements:

- visual inbound check-in and carrier-relative holding/pattern geometry
- deterministic sequencing of multiple aircraft/sections
- pattern occupancy tracking so ORION does not issue conflicting break/landing instructions
- transitions through initial/break/downwind/abeam/180/90/groove as aircraft data permits
- Tower/PriFly owns the visual pattern; LSO owns final landing guidance
- bolter/waveoff returns to a policy-defined resequencing point rather than creating a new unrelated session

The engine must tolerate limited telemetry. If ORION cannot reliably infer a detailed pattern leg, it should maintain coarse states and use conservative phraseology instead of fabricating precision.

## CASE II engine

Case II is modeled as a hybrid engine:

- Marshal/Approach control the instrument portion.
- A visual acquisition/transition event moves the aircraft into the visual carrier pattern.
- If the expected visual transition cannot be established, the session must remain instrument-controlled or move to a missed/divert policy; it must not pretend the carrier is in sight.
- Handoff boundaries are explicit state transitions, not merely voice changes.

## CASE III engine

Case III requires a real scheduler.

`CarrierTrafficSequencer` maintains:

- ordered inbound traffic
- marshal assignments
- EATs / commencement slots
- separation constraints
- fuel/emergency priority
- delay caused by fouled deck, waveoffs, bolters or preceding traffic
- recalculation when the carrier course/speed or traffic picture changes materially

Required flow:

`CHECK_IN -> MARSHAL_ASSIGNED -> ESTABLISHED -> EAT_WAIT -> COMMENCING -> PLATFORM/APPROACH -> FINAL -> LSO`

The exact phraseology adapter may vary by aircraft/module and DCS behavior, but scheduler state remains aircraft-agnostic.

## Handoff model

Controller ownership is explicit:

- launch: Deck/Catapult -> Departure -> external ATC/Mission Control as applicable
- CASE I recovery: arrival/Marshal as needed -> Tower/PriFly -> LSO
- CASE II: Marshal -> Approach -> Tower/PriFly -> LSO
- CASE III: Marshal -> Approach/Final -> LSO, with Tower/PriFly retaining landing-area authority

A handoff contains source agency, destination agency, reason, expected frequency/channel when known, and acknowledgement state. An aircraft cannot be simultaneously owned by two ATC agencies for conflicting control instructions.

## Launch operations

Carrier launch is also first-class state, with a separate `CarrierLaunchSession`:

`STARTUP -> DECK_MOVE -> CAT_ASSIGNED -> HOOKUP -> TENSION/READY -> LAUNCH_CLEARED -> AIRBORNE -> DEPARTURE -> HANDED_OFF`

ORION should track catapult availability and deck state only when grounded in DCS data or explicit mission configuration. Unknown catapult/deck state must not be reported as ready.

Launch and recovery cycle arbitration belongs to `CarrierOpsDirector`; the ATC controllers consume that decision rather than independently assuming deck availability.

## LSO subsystem

LSO is a dedicated controller with a lower-latency execution path than conversational ATC.

Suggested states:

`AWAITING_BALL -> BALL_CALLED -> IN_GROOVE -> CORRECTION_ACTIVE -> TOUCHDOWN | BOLTER | WAVEOFF`

Requirements:

- distinct LSO voice identity
- safety-critical calls can pre-empt non-critical ATC speech
- corrections require sufficiently fresh aircraft/carrier geometry; if confidence is inadequate, ORION must suppress precision corrections
- bolter/waveoff creates a deterministic re-entry/resequence event in the same recovery session
- grading is an observation/debrief artifact and must not interfere with real-time control

## Traffic priority

Traffic sequencing is deterministic and explainable. Policy inputs include:

1. declared emergency / immediate safety condition
2. critically low fuel / bingo state
3. aircraft already on final or committed approach
4. assigned EAT/sequence order
5. normal arrival order

Priority changes are recorded as events so voice callouts and debrief can explain why sequencing changed.

## Radio and voice behavior

Carrier ATC uses role-specific agents, not one `ATC` voice:

- CARRIER_AIR_BOSS
- CARRIER_DEPARTURE
- CARRIER_MARSHAL
- CARRIER_APPROACH
- CARRIER_TOWER
- CARRIER_LSO

The exact enum names may be adjusted during #61 implementation, but identity separation is mandatory.

Radio anti-spam rules:

- stable state is silent unless a procedural report is due
- state transitions and safety-critical changes may generate callouts
- repeated identical instructions are suppressed until an acknowledgement timeout/retry policy is reached
- LSO safety calls override normal suppression when necessary
- conversational/free-form responses never pre-empt urgent ATC/LSO calls

## DCS integration requirements

Minimum carrier-side data desired from DCS/mission bridge:

- carrier identity/type and live position/heading/speed
- ownship and relevant traffic live positions/altitudes/speeds/headings
- mission time and environmental data
- carrier radio/TACAN/ICLS configuration when exposed
- landing/deck/catapult state where exposed
- aircraft launch/recovery events, touchdown, arrestment, bolter/waveoff indicators where available

The adapter exposes capability flags for each datum. Controllers must branch on capability rather than assuming Supercarrier exposes every real-world state.

## Boundary with Mission Control

Carrier ATC owns traffic control, separation, launch/recovery sequencing and landing safety. Mission Control owns tactical mission reasoning.

Allowed information exchange includes:

- threat-driven recommendation to alter a recovery/departure plan
- carrier/aircraft availability status exposed to Mission Control
- divert/bingo/emergency state shared with tactical planning

Mission Control cannot issue groove/LSO corrections or bypass ATC sequencing. Carrier ATC cannot select targets or authorize weapons employment.

## Architecture baseline for #61+

Proposed modules/services:

`CarrierStateProvider`

`CarrierOpsDirector`

`CarrierTrafficSequencer`

`CarrierRecoverySessionStore`

`CarrierLaunchSessionStore`

`CaseIRecoveryEngine`

`CaseIIRecoveryEngine`

`CaseIIIRecoveryEngine`

`CarrierMarshalController`

`CarrierApproachController`

`CarrierTowerController`

`CarrierDepartureController`

`CarrierLSOController`

`CarrierDeckCoordinator`

`CarrierVoiceRouter`

`CarrierDcsAdapter`

Virtual ATC Core #61 should provide common session/radio/controller primitives that these carrier-specific engines can use, but carrier procedures must remain a dedicated domain layer rather than being flattened into generic airport runway logic.

## Implementation order after design sign-off

1. Common Virtual ATC controller/session/radio primitives.
2. CarrierOperationalState and moving-reference geometry.
3. CarrierRecoverySession + controller handoff framework.
4. CASE I engine and LSO skeleton.
5. CASE III scheduler/Marshal/Approach.
6. CASE II hybrid transition.
7. Carrier launch/departure/deck coordination.
8. Emergency, divert, lost-comms and multi-aircraft stress tests.
9. DCS-specific capability adapters and end-to-end voice integration.

## Source baseline

Design is grounded primarily in the DCS Supercarrier Operations Guide (manual updated 20 Nov 2024), official DCS Supercarrier feature documentation, and publicly available U.S. Navy/CNATRA carrier ATC descriptions. The implementation should prefer DCS-observable behavior when simulator behavior differs from real-world procedures, while keeping real-world terminology and control-role separation where feasible.
