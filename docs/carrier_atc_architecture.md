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

Case I is a dedicated visual traffic engine. It must not be reduced to free-form tower chatter.

### Case I session states

`INBOUND -> CHECKED_IN -> VISUAL_HOLDING -> CLEARED_TO_INITIAL -> INITIAL -> BREAK -> DOWNWIND -> ABEAM -> FINAL_TURN_180 -> FINAL_TURN_90 -> GROOVE_ENTRY -> BALL_CALL -> IN_GROOVE -> LANDING_ATTEMPT`

Terminal outcomes:

`LANDING_ATTEMPT -> TRAP -> RECOVERED`

`LANDING_ATTEMPT -> BOLTER -> BOLTER_PATTERN -> RESEQUENCE`

`GROOVE_ENTRY/IN_GROOVE/LANDING_ATTEMPT -> WAVEOFF -> WAVEOFF_PATTERN -> RESEQUENCE`

Emergency override:

`* -> EMERGENCY_PRIORITY`, with sequencing recalculated but current committed traffic protected unless safety requires otherwise.

### Case I controller ownership

- Inbound/check-in and holding assignment may be handled by Marshal/arrival control when configured.
- Tower/PriFly owns visual pattern sequencing from release to initial through groove entry.
- LSO owns final landing guidance from ball-call/groove acceptance through touchdown, bolter or waveoff.
- Tower/PriFly retains landing-area authority; LSO guidance must not imply a clear deck if landing-area state is unknown or foul.

### Case I moving-reference geometry

All pattern geometry is defined in a carrier-relative frame and recalculated from live carrier state. The engine needs at least:

- carrier position/heading/velocity freshness
- BRC and final bearing where available
- ownship position, altitude, groundspeed, heading and track
- traffic positions for occupancy/conflict checks
- landing-area state or an explicit UNKNOWN capability state

Derived geometric observations may include distance/bearing to ship, relative track to BRC/final bearing, pattern side, approximate initial/break/downwind/abeam/180/90/groove regions and closure trends. These observations are confidence-rated; low confidence prevents precise procedural claims.

### Case I pattern occupancy

`CarrierTrafficSequencer` maintains pattern occupancy slots, not merely an ordered queue. At minimum it tracks:

- aircraft/section cleared toward initial
- aircraft committed to the break
- aircraft on downwind
- aircraft in final turn
- aircraft in groove / landing attempt
- bolter/waveoff traffic re-entering

A new clearance to initial or break is suppressed if it would create a known conflict with occupied pattern capacity. When telemetry is insufficient to establish safe spacing, ORION must delay or use conservative instructions rather than inventing separation.

### Case I transition evidence

Transitions are event-driven and require evidence. Examples:

- `CHECKED_IN -> VISUAL_HOLDING`: carrier/mission accepts the aircraft into Case I recovery flow.
- `VISUAL_HOLDING -> CLEARED_TO_INITIAL`: sequencer grants a release slot and landing area/cycle policy allows continuation.
- `CLEARED_TO_INITIAL -> INITIAL`: aircraft enters configured carrier-relative initial region with compatible track/altitude confidence.
- `INITIAL -> BREAK`: observed turn/track change in the break region or an explicit pilot/controller event.
- `BREAK -> DOWNWIND`: aircraft settles onto the expected downwind side/track.
- `DOWNWIND -> ABEAM`: aircraft passes the carrier-relative abeam gate with expected geometry.
- `ABEAM -> FINAL_TURN_180 -> FINAL_TURN_90`: progressive carrier-relative final-turn geometry.
- `FINAL_TURN_90 -> GROOVE_ENTRY`: aircraft approaches final bearing/landing axis within configured geometry and stability limits.
- `GROOVE_ENTRY -> BALL_CALL`: explicit pilot ball call or DCS-equivalent event; ORION must not fabricate this acknowledgement.
- `BALL_CALL -> IN_GROOVE`: LSO accepts/continues final guidance and telemetry remains fresh enough.
- `LANDING_ATTEMPT -> TRAP`: arrestment/touchdown event positively indicates successful recovery.
- `LANDING_ATTEMPT -> BOLTER`: touchdown/landing attempt followed by no arrestment and continued flight, when inferable with adequate confidence or explicit DCS event.
- `* -> WAVEOFF`: LSO/Tower safety decision or DCS event; this has immediate voice priority.

### Case I radio behavior

The engine should preserve real procedural rhythm without becoming a canned script. Required categories include:

- inbound/check-in response
- holding/recovery information
- release toward initial when traffic permits
- pattern sequencing/advisories when required
- ball-call exchange
- LSO corrections/waveoff
- trap/bolter/waveoff outcome and resequence instructions

Stable geometry is silent. ORION should not narrate every state transition. Speech is generated for control instructions, mandatory reports/acknowledgements, materially changed sequencing and safety events.

### Case I section/formation support

The session model must allow a section/division to check in together while still tracking individual aircraft through the landing pattern when they split for recovery. The leader may own the radio session initially, but individual aircraft become separately sequenced before landing attempts. This should be represented explicitly rather than by cloning identical sessions with no relationship.

Suggested fields:

- `formation_id`
- `formation_role`
- `radio_lead_aircraft_id`
- `split_state`
- `preceding_aircraft_id`

### Bolter and waveoff policy

Bolter and waveoff do not destroy the recovery session. They create a re-entry state in the same session, increment counters, preserve fuel/emergency state and trigger deterministic resequencing. LSO outcome and Tower pattern ownership are separate events so ORION can reason about a clear/foul deck independently of pilot performance.

### LSO latency and safety boundary

The LSO path must bypass ordinary conversational latency. Safety-critical calls use a higher-priority voice queue and can pre-empt routine Tower/Marshal/Mission Control chatter. Precision corrections are only allowed when ownship/carrier telemetry meets freshness and confidence thresholds; otherwise ORION limits itself to non-precision safety calls or suppresses guidance.

### Case I observability

Status/debug output should expose, per recovery session:

- current Case I state
- current controlling agency
- preceding/following traffic relation
- pattern occupancy slot
- geometry confidence and last update age
- ball-call received flag
- landing-area state/freshness
- bolter/waveoff counters
- last sequencer decision and reason

This is required for auditability and later debrief.

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
