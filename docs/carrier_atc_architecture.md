# ORION Carrier ATC Architecture

Status: design baseline before Virtual ATC Core (#61)

## Goal
Carrier aviation is a first-class ATC domain, not an airport with a moving runway. It supports launch/recovery, sequencing, handoff, moving-reference geometry, distinct controller roles/voices, and safe degradation with incomplete DCS data.

## Control roles
Separate agencies share one operational picture: Air Boss/PriFly, Departure, Marshal, Approach, Tower/PriFly, LSO, and Deck/Catapult coordination. Every audible agency has a distinct voice identity; LSO can pre-empt ordinary ATC chatter.

## Shared carrier operational state
`CarrierOperationalState` is the moving-reference source of truth: mission/carrier identity, live position/heading/velocity, BRC, final bearing, wind/environment, recovery case, launch/recovery cycle, landing-area state, catapult availability, TACAN/ICLS/ACLS/PALS configuration, frequencies, and freshness/capability flags. Unknown stays unknown. All procedural geometry moves with the ship.

## Recovery case selection
Case selection is policy with an explicit reason. Mission-authoritative configuration wins over incomplete auto-detection.

## Aircraft recovery session
Each inbound aircraft has a mission-scoped `CarrierRecoverySession` carrying aircraft/carrier identity, fuel/emergency state, recovery case, marshal/holding assignment, EAT where applicable, traffic relationship, controller/state, timestamps, bolter/waveoff counters, divert/lost-comms state and freshness.

## Common recovery state machine
`INBOUND -> CHECKED_IN -> ASSIGNED -> HOLDING -> COMMENCING -> APPROACH -> FINAL -> LANDING_ATTEMPT -> RECOVERED`, with BOLTER/RESEQUENCE, WAVEOFF/RESEQUENCE, EMERGENCY_PRIORITY, DIVERTED and LOST_COMMS alternatives.

## CASE I engine
Case I is a dedicated visual traffic engine.

`INBOUND -> CHECKED_IN -> VISUAL_HOLDING -> CLEARED_TO_INITIAL -> INITIAL -> BREAK -> DOWNWIND -> ABEAM -> FINAL_TURN_180 -> FINAL_TURN_90 -> GROOVE_ENTRY -> BALL_CALL -> IN_GROOVE -> LANDING_ATTEMPT`

Outcomes: TRAP/RECOVERED, BOLTER/BOLTER_PATTERN/RESEQUENCE, WAVEOFF/WAVEOFF_PATTERN/RESEQUENCE. Tower/PriFly owns visual sequencing through groove entry; LSO owns final landing guidance while Tower retains landing-area authority. Geometry and occupancy are carrier-relative/confidence-rated. Transitions require telemetry or explicit events. Stable geometry is silent. Formation relationships are explicit. Bolter/waveoff preserves the same session. LSO uses a high-priority low-latency voice path.

## CASE II engine
Case II is a true hybrid recovery engine: its outer/instrument portion reuses Case III-style Marshal/Approach primitives, while successful visual acquisition transitions the same recovery session into Case I-style visual control. It is not implemented as a separate canned procedure or by destroying/recreating the session at the visual boundary.

### Case II session states
`INBOUND -> CHECKED_IN -> MARSHAL_ASSIGNED -> PROCEEDING_TO_MARSHAL -> ESTABLISHED -> RELEASED/COMMENCING -> INSTRUMENT_ARRIVAL -> VISUAL_TRANSITION_GATE -> VISUAL_ACQUIRED -> VISUAL_HANDOFF -> CASE_I_PATTERN -> GROOVE_ENTRY -> LSO_HANDOFF -> IN_GROOVE -> LANDING_ATTEMPT`

Alternative branches:
`VISUAL_TRANSITION_GATE -> VISUAL_NOT_ACQUIRED -> INSTRUMENT_CONTINUE | MISSED_APPROACH | RESEQUENCE | DIVERTED`

`LANDING_ATTEMPT -> BOLTER -> RESEQUENCE`

`FINAL/IN_GROOVE -> WAVEOFF -> RESEQUENCE`

`* -> EMERGENCY_PRIORITY | LOST_COMMS | DIVERTED`

### Shared primitives, not duplicated logic
Case II reuses the common `CarrierRecoverySession`, marshal assignment model, controller-ownership transaction, traffic priority, capability/freshness model and moving-reference geometry. Instrument sequencing is supplied by `CarrierTrafficSequencer`; after accepted visual transition, visual pattern occupancy is supplied by the Case I engine/sequencer view. This prevents two independent queues from controlling the same aircraft.

### Visual transition is an explicit gate
The central Case II invariant is: ORION never assumes visual conditions merely because the aircraft reached a nominal range. `VISUAL_TRANSITION_GATE -> VISUAL_ACQUIRED` requires evidence such as an explicit pilot report/acknowledgement or a simulator-supported equivalent. Weather/geometry can establish eligibility for the transition but cannot fabricate pilot visual acquisition.

The gate records:
- carrier-relative position/range/altitude and freshness
- current weather/visibility capability where known
- current controlling agency
- whether visual acquisition was requested/reported/accepted
- timestamp and transition attempt count
- fallback plan if visual contact is not established

### Controller ownership through transition
Before visual acceptance, Approach remains controlling owner. A successful transition creates a handoff transaction from Approach to Tower/PriFly. Tower becomes controlling owner only after handoff acceptance/observation. LSO remains downstream and cannot take control directly from Marshal merely because the aircraft is geographically close to the ship.

Frequency/channel data are advisory fields in the handoff when known; tuning a frequency is not proof of ownership.

### Transition into Case I visual sequencing
Once `VISUAL_HANDOFF` completes, the aircraft joins the existing Case I pattern occupancy model rather than a parallel Case II visual queue. The sequencer determines an appropriate visual entry/recovery slot from current traffic and geometry. Existing Case I traffic is protected from conflicting insertion.

Case II may enter the visual recovery at a procedure/configuration-appropriate point, but ORION only claims a specific pattern leg when telemetry confidence supports it. If detailed geometry is unavailable, the state remains coarse (`CASE_I_PATTERN`) until stronger evidence exists.

### Failure to acquire visual contact
`VISUAL_NOT_ACQUIRED` is a first-class operational result, not an NLP failure. The policy engine selects among continued instrument control, missed approach/resequence, hold, or divert based on available approach capability, traffic, fuel/emergency state, recovery status and mission configuration.

ORION must not issue Case I pattern instructions while the session remains `VISUAL_NOT_ACQUIRED`. Repeated requests for visual confirmation are anti-spam controlled and bounded by retry/timing policy.

### Weather/case changes during Case II
A material weather or mission-authoritative case change may invalidate the planned visual transition. `CarrierOpsDirector` can keep the session instrument-controlled, convert/replan it toward Case III, or suspend recovery. Conversion preserves session identity, fuel/emergency state and traffic history; it records old/new case and reason.

Likewise, improving conditions do not silently convert an active Case III session to Case II. Case changes are explicit operational decisions.

### Bolter/waveoff after visual transition
After transition into the visual pattern, bolter/waveoff behavior follows shared Case I/LSO re-entry semantics while preserving the original Case II recovery session and its history. The sequencer decides whether the next attempt remains visual or requires instrument resequencing based on current case/recovery policy.

### Case II voice behavior
Marshal, Approach, Tower/PriFly and LSO retain distinct voices. The most important radio event is the visual-transition exchange and handoff; ORION must not produce duplicate Approach and Tower instructions around that boundary. Stable instrument tracking and stable visual pattern geometry remain silent unless a procedural report/instruction is due.

### Case II observability
Per-session status exposes current state/owner, instrument assignment, visual-transition eligibility/evidence, attempt count, handoff transaction, current visual pattern slot if transitioned, fallback plan, geometry/weather freshness, fuel/emergency priority and last transition decision/reason.

## CASE III engine
Case III is a timed instrument-recovery system and defines demanding common ATC primitives.

`INBOUND -> CHECKED_IN -> MARSHAL_ASSIGNED -> PROCEEDING_TO_MARSHAL -> ESTABLISHED -> EAT_WAIT -> COMMENCE_AUTHORIZED -> COMMENCING -> PENETRATION -> PLATFORM -> APPROACH_CONTROLLED -> FINAL -> LSO_HANDOFF -> IN_GROOVE -> LANDING_ATTEMPT`

`CarrierTrafficSequencer` owns versioned marshal assignments, EAT, predecessor/successor, separation, commitment state and deterministic resequencing. Triggers include new/cancelled traffic, emergency/fuel changes, missed establishment/commence tolerance, bolter/waveoff, foul deck, suspension, material carrier-motion changes, and capability loss/restoration. Committed traffic is protected unless safety requires intervention.

Marshal occupancy is explicit. Establishment requires explicit or sufficiently confident geometry evidence. Commence is scheduler-gated; a missed slot is recorded and resequenced. Penetration/platform are first-class states. Marshal-to-Approach handoff is transactional; Approach ownership is not inferred from frequency alone. Approach/nav-aid guidance is capability-gated. Tower retains landing-area authority while LSO owns final safety guidance. Bolter/waveoff preserves the session and requests a new slot. Recovery suspension blocks new commence authorizations. Lost-comms reserves/protects traffic space rather than deleting the aircraft. All resequencing is explainable and observable.

## Handoff model
Controller ownership is explicit. Launch: Deck/Catapult -> Departure -> external control. Case I: arrival/Marshal as needed -> Tower/PriFly -> LSO. Case II: Marshal -> Approach -> Tower/PriFly -> LSO. Case III: Marshal -> Approach/Final -> LSO, with Tower/PriFly retaining landing-area authority.

## Launch operations
Carrier launch is first-class state with `CarrierLaunchSession`: `STARTUP -> DECK_MOVE -> CAT_ASSIGNED -> HOOKUP -> TENSION/READY -> LAUNCH_CLEARED -> AIRBORNE -> DEPARTURE -> HANDED_OFF`. Unknown catapult/deck state is never reported as ready. Launch/recovery cycle arbitration belongs to `CarrierOpsDirector`.

## LSO subsystem
LSO is a dedicated low-latency controller: `AWAITING_BALL -> BALL_CALLED -> IN_GROOVE -> CORRECTION_ACTIVE -> TOUCHDOWN | BOLTER | WAVEOFF`. Safety calls pre-empt non-critical speech; precision corrections require fresh geometry; grading is a debrief artifact.

## Traffic priority
Deterministic priority: immediate emergency, critical fuel, committed approach/final, EAT/sequence, normal arrival. Priority changes are events with reasons.

## Radio and voice behavior
Role-specific agents: `CARRIER_AIR_BOSS`, `CARRIER_DEPARTURE`, `CARRIER_MARSHAL`, `CARRIER_APPROACH`, `CARRIER_TOWER`, `CARRIER_LSO`. Stable state is silent; repeats are suppressed until retry policy; LSO safety calls override normal suppression; conversation never pre-empts urgent ATC/LSO calls.

## DCS integration requirements
Desired data: carrier identity/type/live motion, ownship/relevant traffic kinematics, mission/environment time, radio/TACAN/ICLS configuration, landing/deck/catapult state where exposed, and launch/recovery/touchdown/arrestment/bolter/waveoff events. Adapter exposes capability/freshness flags rather than assuming all real-world data exists.

## Boundary with Mission Control
Carrier ATC owns traffic control, separation, launch/recovery sequencing and landing safety. Mission Control owns tactical reasoning. They may exchange threat-driven routing recommendations, availability and divert/bingo/emergency state, but neither bypasses the other's authority.

## Architecture baseline for #61+
Proposed modules/services: `CarrierStateProvider`, `CarrierOpsDirector`, `CarrierTrafficSequencer`, `CarrierRecoverySessionStore`, `CarrierLaunchSessionStore`, `CaseIRecoveryEngine`, `CaseIIRecoveryEngine`, `CaseIIIRecoveryEngine`, `CarrierMarshalController`, `CarrierApproachController`, `CarrierTowerController`, `CarrierDepartureController`, `CarrierLSOController`, `CarrierDeckCoordinator`, `CarrierVoiceRouter`, `CarrierDcsAdapter`.

Virtual ATC Core #61 provides common session/radio/controller/handoff primitives these carrier engines can use, while carrier procedures remain a dedicated domain layer.

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
Design is grounded primarily in the DCS Supercarrier Operations Guide (manual updated 20 Nov 2024), official DCS Supercarrier feature documentation, and publicly available U.S. Navy/CNATRA carrier ATC descriptions. Implementation should prefer DCS-observable behavior when simulator behavior differs from real-world procedures while keeping real-world terminology and role separation where feasible.
