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

`CarrierOperationalState` should be the single moving-reference source of truth consumed by all carrier controllers. Required fields include mission/carrier identity, live position/heading/velocity, BRC, final bearing, wind/environment inputs, recovery case, launch/recovery cycle, landing-area state, catapult availability, TACAN/ICLS/ACLS/PALS configuration, carrier frequencies, and freshness/confidence flags. Unknown values remain unknown rather than being invented.

All geometry is computed relative to the current carrier state. Marshal fixes, radial/DME positions, pattern references, final course, departure gates and handoff boundaries move with the ship.

## Recovery case selection

Case selection is policy, not a hard-coded assumption. ORION consumes mission/environment data and carrier configuration and exposes both selected case and reason. Mission-authoritative case selection wins over incomplete auto-detection.

## Aircraft recovery session

Each inbound aircraft receives a mission-scoped `CarrierRecoverySession` carrying aircraft/carrier identity, fuel/emergency state, recovery case, marshal/holding assignment, EAT where applicable, traffic relationship, current controller/state, timestamps, bolter/waveoff counters, divert/lost-comms state and freshness information.

## Common recovery state machine

`INBOUND -> CHECKED_IN -> ASSIGNED -> HOLDING -> COMMENCING -> APPROACH -> FINAL -> LANDING_ATTEMPT -> RECOVERED`

Alternative paths include BOLTER/RESEQUENCE, WAVEOFF/RESEQUENCE, EMERGENCY_PRIORITY, DIVERTED and LOST_COMMS.

## CASE I engine

Case I is a dedicated visual traffic engine, not free-form tower chatter.

### Case I session states

`INBOUND -> CHECKED_IN -> VISUAL_HOLDING -> CLEARED_TO_INITIAL -> INITIAL -> BREAK -> DOWNWIND -> ABEAM -> FINAL_TURN_180 -> FINAL_TURN_90 -> GROOVE_ENTRY -> BALL_CALL -> IN_GROOVE -> LANDING_ATTEMPT`

Terminal outcomes are TRAP/RECOVERED, BOLTER/BOLTER_PATTERN/RESEQUENCE and WAVEOFF/WAVEOFF_PATTERN/RESEQUENCE. Emergency priority can interrupt normal sequencing while protecting already committed traffic where safe.

Tower/PriFly owns visual sequencing through groove entry; LSO owns final landing guidance. Tower/PriFly retains landing-area authority. Geometry and pattern occupancy are carrier-relative and confidence-rated. State transitions require telemetry or explicit event evidence; ORION must not fabricate ball calls, traps, bolters or precise pattern positions. Stable geometry is silent. Section/division relationships are represented explicitly and split into individual landing sequences. Bolter/waveoff preserves the same recovery session and triggers deterministic resequencing. LSO safety calls use a high-priority low-latency voice path.

## CASE II engine

Case II is modeled as a hybrid engine: Marshal/Approach own the instrument portion and an explicit visual-acquisition transition moves the aircraft into the visual carrier pattern. Failure to establish the required visual transition keeps the aircraft under instrument control or moves it to missed/divert policy; ORION never pretends the carrier is in sight.

## CASE III engine

Case III is a timed instrument-recovery system and therefore defines the most demanding traffic-control primitives required by Virtual ATC Core.

### Case III session states

`INBOUND -> CHECKED_IN -> MARSHAL_ASSIGNED -> PROCEEDING_TO_MARSHAL -> ESTABLISHED -> EAT_WAIT -> COMMENCE_AUTHORIZED -> COMMENCING -> PENETRATION -> PLATFORM -> APPROACH_CONTROLLED -> FINAL -> LSO_HANDOFF -> IN_GROOVE -> LANDING_ATTEMPT`

Terminal/recovery branches:

`LANDING_ATTEMPT -> TRAP -> RECOVERED`

`LANDING_ATTEMPT -> BOLTER -> MISSED_APPROACH -> RESEQUENCE`

`FINAL/IN_GROOVE -> WAVEOFF -> MISSED_APPROACH -> RESEQUENCE`

`* -> EMERGENCY_PRIORITY`

`* -> DIVERTED`

`* -> LOST_COMMS`

### Marshal assignment model

A Case III marshal assignment is structured data, not only spoken text. It includes, when known/authoritative:

- carrier-relative marshal radial/bearing reference
- DME/range reference
- assigned altitude/block
- expected approach time (EAT)
- recovery case and approach type/capability
- BRC/final bearing information appropriate to the phase
- altimeter/weather information when available
- controlling agency/frequency when known
- assignment revision number and timestamp

Assignments are mission-scoped and versioned. If the carrier changes course/speed materially or the recovery plan changes, the sequencer may issue a revised assignment. A stale assignment is never silently treated as current.

### CarrierTrafficSequencer and EAT scheduler

`CarrierTrafficSequencer` owns the ordered recovery plan. EAT is first-class state, not a phrase generated on demand. For each aircraft the scheduler tracks assigned EAT, sequence predecessor/successor, minimum spacing policy, current marshal status, estimated time-to-commence, fuel/emergency priority and whether the aircraft is already committed to penetration/final.

The scheduler must be deterministic and explainable. Recalculation can be triggered by:

- new inbound traffic or cancellation/divert
- declared emergency or materially worsening fuel state
- aircraft failing to establish or commence within tolerance
- bolter/waveoff/missed approach
- landing area becoming foul/clear
- recovery suspension/resumption
- material carrier course/speed change affecting moving-reference geometry
- loss/restoration of approach/navigation capability

Recalculation does not casually reorder committed traffic. Aircraft already commencing, on approach or final receive commitment protection unless an emergency/safety condition requires intervention.

Every resequence emits a machine-readable reason and old/new slot data for observability and debrief.

### Marshal stack separation

Marshal occupancy is explicit. ORION tracks aircraft assigned to each marshal altitude/slot and prevents known conflicting assignments. If telemetry/capability is insufficient to prove a slot is clear, the allocator uses conservative capacity rather than assuming availability.

The model supports sections/formations checking in together, while preserving a relationship that can later split into individual approach slots when procedure/configuration requires it.

### Establishment and EAT waiting

`PROCEEDING_TO_MARSHAL -> ESTABLISHED` requires either an explicit pilot/DCS establishment event or sufficiently confident carrier-relative geometry. ORION does not infer an `established` report solely because time has elapsed.

While `ESTABLISHED/EAT_WAIT`, Marshal owns the aircraft. The scheduler continually compares mission time against EAT and expected travel/commence tolerance. Stable waiting is silent except for required reports, revisions or safety changes.

### Commence gate

`EAT_WAIT -> COMMENCE_AUTHORIZED` occurs only when the scheduler releases the aircraft. Inputs include EAT tolerance, preceding traffic progress, approach capacity, landing-area/recovery-cycle state, and emergency overrides.

`COMMENCE_AUTHORIZED -> COMMENCING` requires acknowledgement or observed commencement evidence according to capability. If the aircraft does not commence within policy tolerance, ORION records a missed slot and resequences rather than pretending the approach has begun.

### Penetration and platform

The instrument descent is represented explicitly because it is both a procedural and separation boundary. `COMMENCING -> PENETRATION -> PLATFORM` uses carrier-relative geometry, altitude/descent trends and/or explicit reports. Precision claims are suppressed when telemetry is stale.

The `platform` event is first-class because it is useful for timing, handoff and debrief even if a particular DCS module exposes it only through pilot voice rather than telemetry.

### Marshal to Approach handoff

Handoff is a transaction with source agency, destination agency, frequency/channel when known, reason, issue time and acknowledgement state. Marshal remains owner until handoff conditions are met. Approach becomes controlling owner only after the handoff transition is accepted/observed.

A radio frequency change alone is not sufficient proof of controller ownership. ORION must avoid simultaneous conflicting ownership.

### Approach-controlled phase

Approach owns separation and procedural guidance from accepted handoff toward final. The session records approach type/capability actually available in DCS/configuration. ICLS/ACLS/PALS-related guidance is capability-gated; ORION never advertises an aid simply because a real carrier would normally have it.

Approach guidance uses live carrier-relative final geometry and final-bearing freshness. If final-bearing/navigation data becomes stale or unavailable, the controller degrades phraseology and may hold/missed-approach/divert according to policy instead of issuing fabricated precision vectors.

### Final and LSO handoff

`APPROACH_CONTROLLED -> FINAL -> LSO_HANDOFF` requires adequate final geometry/approach state. LSO takes the safety-critical final landing guidance path only when the aircraft reaches the configured handoff/groove boundary and required telemetry is fresh enough.

Tower/PriFly continues to own landing-area availability even while LSO owns final guidance. A foul/unknown deck can therefore force waveoff regardless of otherwise valid LSO geometry.

### Bolter, waveoff and missed approach

Case III bolter/waveoff preserves the existing recovery session. It increments counters, enters `MISSED_APPROACH`, updates fuel state, and requests a new slot from the sequencer. Emergency/fuel priority can move the aircraft forward, but resequencing remains explicit and auditable.

A bolter is not automatically classified from a generic airborne state; it requires an arrestment/touchdown/continued-flight signal or explicit event with sufficient confidence.

### Recovery suspension and fouled deck

`CarrierOpsDirector` may suspend recovery. During suspension:

- no new commence authorization is issued
- already committed aircraft are handled by explicit continue/waveoff/missed-approach policy
- EATs and slots are marked delayed rather than silently rewritten
- Marshal receives revised timing only when the new plan is known

Landing-area `UNKNOWN` is not equivalent to `CLEAR`. Precision landing clearance/guidance that depends on a clear deck must be withheld or conservatively qualified according to controller role.

### Emergency and fuel priority

Priority policy remains deterministic:

1. immediate declared emergency/safety condition
2. critically low fuel/bingo state
3. traffic already committed to final/approach
4. assigned EAT/sequence
5. normal arrival order

A priority override records the reason and affected traffic. ORION should be able to explain why an aircraft was advanced or delayed.

### Lost communications

Lost-comms is a real session state, not simply a timeout exception. Detection combines radio/session timeout policy with telemetry evidence. The scheduler reserves/protects traffic space according to configured procedure instead of immediately deleting the aircraft from the plan. Recovery or divert outcome closes the condition explicitly.

### Case III voice behavior

Marshal, Approach, Tower/PriFly and LSO remain distinct voice identities. Routine timing revisions are anti-spam controlled; safety changes, waveoff and emergency instructions can pre-empt normal traffic. Free-form conversation never blocks procedural or LSO calls.

### Case III observability

Status/debug output per aircraft should expose:

- session/recovery case/current state/current controlling agency
- marshal assignment and revision
- EAT and scheduler tolerance/status
- predecessor/successor and commitment state
- current handoff transaction
- approach/nav-aid capabilities actually available
- landing-area state/freshness
- carrier geometry/final-bearing freshness
- fuel/emergency priority
- bolter/waveoff/missed-slot counters
- last scheduler decision and reason

The sequencer also exposes a carrier-wide ordered recovery board so multi-aircraft behavior can be audited.

## Handoff model

Controller ownership is explicit. Launch flows Deck/Catapult -> Departure -> external control as applicable. Case I flows arrival/Marshal as needed -> Tower/PriFly -> LSO. Case II flows Marshal -> Approach -> Tower/PriFly -> LSO. Case III flows Marshal -> Approach/Final -> LSO, while Tower/PriFly retains landing-area authority.

## Launch operations

Carrier launch is first-class state with `CarrierLaunchSession`: `STARTUP -> DECK_MOVE -> CAT_ASSIGNED -> HOOKUP -> TENSION/READY -> LAUNCH_CLEARED -> AIRBORNE -> DEPARTURE -> HANDED_OFF`. Unknown catapult/deck state is never reported as ready. Launch/recovery cycle arbitration belongs to `CarrierOpsDirector`.

## LSO subsystem

LSO is a dedicated low-latency controller. Suggested states: `AWAITING_BALL -> BALL_CALLED -> IN_GROOVE -> CORRECTION_ACTIVE -> TOUCHDOWN | BOLTER | WAVEOFF`. Safety-critical calls pre-empt non-critical ATC speech; precision corrections require fresh geometry; grading remains a debrief artifact.

## Traffic priority

Traffic sequencing is deterministic and explainable: emergency, critical fuel, committed approach/final, EAT/sequence, then normal arrival order. Priority changes are recorded as events.

## Radio and voice behavior

Carrier ATC uses role-specific agents: `CARRIER_AIR_BOSS`, `CARRIER_DEPARTURE`, `CARRIER_MARSHAL`, `CARRIER_APPROACH`, `CARRIER_TOWER`, `CARRIER_LSO`. Stable state is silent; repeated instructions are suppressed until retry policy; LSO safety calls override normal suppression; conversational/free-form responses never pre-empt urgent ATC/LSO calls.

## DCS integration requirements

Desired carrier-side data includes carrier identity/type/live motion, ownship/relevant traffic kinematics, mission/environment time, radio/TACAN/ICLS configuration, landing/deck/catapult state where exposed, and launch/recovery/touchdown/arrestment/bolter/waveoff events where available. The adapter exposes capability/freshness flags rather than pretending all real-world data is available.

## Boundary with Mission Control

Carrier ATC owns traffic control, separation, launch/recovery sequencing and landing safety. Mission Control owns tactical mission reasoning. They may exchange threat-driven routing recommendations, availability and divert/bingo/emergency state, but neither bypasses the other's authority domain.

## Architecture baseline for #61+

Proposed modules/services: `CarrierStateProvider`, `CarrierOpsDirector`, `CarrierTrafficSequencer`, `CarrierRecoverySessionStore`, `CarrierLaunchSessionStore`, `CaseIRecoveryEngine`, `CaseIIRecoveryEngine`, `CaseIIIRecoveryEngine`, `CarrierMarshalController`, `CarrierApproachController`, `CarrierTowerController`, `CarrierDepartureController`, `CarrierLSOController`, `CarrierDeckCoordinator`, `CarrierVoiceRouter`, `CarrierDcsAdapter`.

Virtual ATC Core #61 should provide common session/radio/controller primitives these carrier engines can use, while carrier procedures remain a dedicated domain layer rather than generic airport runway logic.

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

Design is grounded primarily in the DCS Supercarrier Operations Guide (manual updated 20 Nov 2024), official DCS Supercarrier feature documentation, and publicly available U.S. Navy/CNATRA carrier ATC descriptions. Implementation should prefer DCS-observable behavior when simulator behavior differs from real-world procedures, while keeping real-world terminology and control-role separation where feasible.
