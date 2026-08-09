# ORION Carrier ATC — CASE III Detailed Design

Status: design phase before Virtual ATC Core (#61)

## Purpose

CASE III is modeled as a scheduled instrument-recovery system, not as a sequence of canned radio calls. The design must support multiple inbound aircraft, deterministic marshal assignments, expected approach times (EAT), controller ownership, separation, moving-carrier geometry, landing-area interruptions, bolters/waveoffs, emergencies, and safe degradation when DCS telemetry is incomplete.

This document refines the CASE III portion of `docs/carrier_atc_architecture.md`.

## Core ownership model

The normal controller chain is:

`MARSHAL -> APPROACH/FINAL -> LSO`

Tower/PriFly retains landing-area authority and can suspend or resume recovery. The active controlling agency is explicit session state; a pilot cannot receive conflicting control instructions from Marshal and Approach at the same time.

The handoff object must contain:

- source agency
- destination agency
- session/aircraft identity
- reason
- expected frequency/channel when known
- instruction timestamp
- acknowledgement state
- timeout/retry state

## CASE III recovery session states

Detailed states:

`INBOUND`

`CHECK_IN_PENDING`

`CHECKED_IN`

`MARSHAL_ASSIGNED`

`MARSHAL_READBACK_PENDING`

`MARSHAL_ESTABLISHED`

`EAT_WAIT`

`COMMENCE_WINDOW`

`COMMENCING`

`APPROACH_HANDOFF_PENDING`

`APPROACH_CHECKED_IN`

`DESCENT`

`PLATFORM`

`FINAL_APPROACH`

`LSO_HANDOFF`

`IN_GROOVE`

`LANDING_ATTEMPT`

Terminal/recovery branches:

`LANDING_ATTEMPT -> RECOVERED`

`LANDING_ATTEMPT -> BOLTER -> RESEQUENCE`

`FINAL_APPROACH/LANDING_ATTEMPT -> WAVEOFF -> RESEQUENCE`

`* -> EMERGENCY_PRIORITY`

`* -> DIVERTED`

`* -> LOST_COMMS`

`* -> SUSPENDED`

A bolter or waveoff does not create a new recovery session. The existing session retains identity, fuel history, priority and count of unsuccessful passes.

## Check-in data

A CASE III inbound report should be normalized into structured fields rather than preserved only as text. Desired fields include:

- callsign / aircraft identity
- carrier identity
- bearing/range or other position reference to mother when available
- altitude
- fuel state
- navigation aid availability/marking information when relevant
- emergency, bingo or degraded-aircraft declarations
- aircraft type and section/flight relationship

Missing values stay unknown. The controller must not invent fuel, altitude, weather, navigation-aid status or geometry.

## Marshal assignment

`CarrierTrafficSequencer` produces a `MarshalAssignment` containing at least:

- assignment_id
- mission_id
- carrier_id
- aircraft/session_id
- marshal radial or equivalent carrier-relative reference
- DME/range
- altitude
- holding direction/profile when applicable
- EAT
- sequence index
- assigned_at
- geometry_reference_timestamp
- reason / priority reason

The assignment is carrier-relative. If the carrier moves, the conceptual marshal fix moves with the ship; ORION must recompute geographic coordinates from the current carrier state rather than freeze a world-space point at assignment time.

An assignment becomes active only after the required pilot readback/acknowledgement policy is satisfied. Incorrect or materially incomplete readback keeps the session in `MARSHAL_READBACK_PENDING`.

## Scheduler and EAT

EAT is first-class state.

The sequencer maintains an ordered recovery queue and allocates commencement slots. A slot is not merely a spoken time; it is a scheduling object with:

- target commencement time
- allowable timing tolerance/policy
- predecessor/successor traffic relationship
- minimum separation policy
- deck availability dependency
- priority reason
- revision number

The scheduler is deterministic. Given identical carrier state, traffic list and policy inputs, it should generate the same ordering and slot assignments.

Priority inputs, in order of policy significance, include:

1. declared emergency / immediate safety condition
2. critically low fuel / bingo condition
3. aircraft already committed to final approach
4. previously assigned EAT and sequencing stability
5. normal arrival order

The implementation should avoid needless EAT churn. Small carrier-motion updates or insignificant telemetry noise must not continuously reissue timings.

## Replanning triggers

A full or partial reschedule is triggered only by material events such as:

- new inbound traffic accepted into the recovery queue
- emergency declaration or cancellation
- meaningful fuel-priority change
- landing area becomes FOUL/CLEAR
- recovery cycle suspension/resumption
- missed commencement window beyond tolerance
- bolter or waveoff requiring reinsertion
- aircraft divert/despawn/destruction
- significant carrier course/speed change that invalidates current geometry or timing assumptions
- explicit operator/mission override

Each schedule revision emits an internal event carrying old/new assignment information and reason. Voice output is separately rate-limited and suppressed when the pilot does not need a new instruction.

## Commencement logic

`EAT_WAIT -> COMMENCE_WINDOW` occurs when the assigned slot is approaching and prerequisites remain valid.

`COMMENCE_WINDOW -> COMMENCING` requires either:

- a grounded pilot commencement report/acknowledgement; or
- a DCS-observable event that the implementation explicitly treats as equivalent under the selected procedure policy.

ORION must not infer `COMMENCING` solely because wall-clock time reached EAT if the aircraft is clearly not in the assigned geometry or required state.

On commencement, Marshal can provide the expected final bearing and initiate the handoff to Approach when the simulator/procedure path supports it.

## Approach ownership

Approach receives control only after an explicit handoff transition. Suggested flow:

`COMMENCING -> APPROACH_HANDOFF_PENDING -> APPROACH_CHECKED_IN -> DESCENT -> PLATFORM -> FINAL_APPROACH`

Approach state should track:

- current carrier-relative range/bearing
- altitude and vertical trend
- assigned final bearing/course
- speed if reliably available
- navigation-aid capability status
- approach mode/capability (for example ICLS/ACLS/PALS-like capability if actually exposed or configured)
- landing-area availability
- traffic separation relationship
- telemetry freshness

`PLATFORM` is represented as a procedural/event state rather than a phrase-only marker. If DCS provides no reliable automatic trigger, ORION waits for pilot report or another explicit event instead of fabricating passage of platform.

## Final approach and LSO handoff

Approach retains control until the defined final/LSO handoff boundary. The boundary must be policy-driven and grounded in available telemetry/procedure data.

Once handed to LSO:

- routine Marshal/Approach transmissions to that aircraft are suppressed
- LSO safety calls have higher priority than normal ATC and conversational speech
- precision correction calls require fresh enough carrier/aircraft geometry
- stale/low-confidence geometry suppresses precision corrections rather than guessing

Touchdown/arrestment, bolter and waveoff should preferentially use explicit simulator events where available. Geometry-only inference is a fallback capability with explicit confidence marking.

## Bolter and waveoff resequencing

A bolter/waveoff is a schedule disruption, not a new unrelated arrival.

The session records:

- bolter_count
- waveoff_count
- event timestamp
- fuel state after the event when known
- reason when known
- previous sequence/EAT
- new sequence/EAT when reassigned

Reinsertion policy considers safety first and may preserve near-term priority when practical, but must not create unsafe conflict with already committed traffic.

If landing area is fouled, additional inbound aircraft should not be allowed to cascade toward final merely because their old EATs expire. The scheduler must propagate delay upstream.

## Landing-area interruptions

`CarrierOpsDirector` owns recovery availability. When landing area changes to `FOUL` or recovery becomes `SUSPENDED`:

- new commencement clearances are withheld when necessary
- aircraft already committed to final are handled according to safety policy
- queued EATs are marked impacted
- updated timings are computed only when the interruption duration can be estimated or when recovery resumes
- voice output communicates only actionable changes, not every internal schedule recomputation

Unknown deck state is never treated as CLEAR.

## Emergency handling

Emergency priority is orthogonal to normal CASE III state. A session may enter `EMERGENCY_PRIORITY` while preserving its current procedural position.

The policy layer can:

- move an aircraft ahead in the queue
- reserve an earliest practical approach slot
- delay lower-priority traffic
- recommend divert when recovery is unavailable or fuel state demands it

An emergency declaration does not authorize ORION to invent deck readiness or guarantee landing availability.

## Lost communications

Lost-comms handling must be explicit and configurable rather than improvised by the language model.

Session fields include:

- last pilot transmission time
- last controller transmission time
- outstanding acknowledgement
- retry count
- lost_comms_suspected / confirmed state

The runtime follows a deterministic retry/timeout policy. Free-form conversational behavior is disabled for a lost-comms session until positive communication is restored.

## Moving-reference geometry

All CASE III geometric calculations are relative to `CarrierOperationalState` at a known timestamp. Required primitives for #61+ include:

- bearing/range from aircraft to carrier
- world point from carrier-relative radial/range
- carrier-relative course error
- final-bearing alignment error
- closure/range-rate where telemetry permits
- freshness/age of both aircraft and carrier state

Geometry functions return confidence/freshness metadata. Controllers may not treat stale geometry as current.

## Radio/event suppression

Stable schedule state is silent.

A new transmission is justified by events such as:

- initial marshal assignment
- corrected readback
- revised EAT materially affecting the aircraft
- commencement instruction/window
- controller handoff
- approach correction/instruction
- platform acknowledgement where procedural
- final/LSO transition
- waveoff/bolter/resequence
- emergency or recovery suspension

Repeated identical instructions are suppressed until acknowledgement timeout/retry policy allows a repeat.

## Observability

The runtime should expose a read-only status API suitable for debugging and future UI:

- carrier operational state summary
- active CASE III sessions
- controlling agency per session
- marshal assignment
- EAT and revision
- queue position
- emergency/fuel priority
- outstanding acknowledgement
- telemetry freshness
- landing-area/recovery status
- last scheduler revision reason

No status endpoint may mutate sequencing state.

## DCS-specific baseline

The DCS Supercarrier flow exposes the procedural concepts ORION must model: CASE III inbound/check-in, marshal assignment with radial/range/altitude, EAT, established report, commencing report, expected final bearing, switch/handoff to Approach, Approach check-in, platform report and final recovery flow.

The architecture follows those simulator-visible concepts while keeping exact numbers, frequencies and navigation-aid details data-driven rather than hard-coded into the generic core.

## Required primitives this imposes on Virtual ATC Core #61

CASE III establishes requirements that generic Virtual ATC Core must support from the beginning:

- mission-scoped controller sessions
- explicit controlling agency and handoff state
- acknowledgement/readback transactions
- deterministic timed instructions/deadlines
- controller-owned traffic sequencing
- priority escalation
- stale telemetry/capability handling
- radio deduplication and retry policy
- independent voice identities and priority/pre-emption
- event log suitable for debrief and debugging

Therefore #61 must not be implemented as only `speech -> intent -> response`; its core data model must support scheduled, stateful multi-aircraft control.

## Test obligations for later implementation

At minimum, future implementation must test:

- two or more arrivals receive deterministic non-conflicting marshal/EAT assignments
- readback mismatch blocks assignment acceptance
- stable telemetry does not churn EATs
- emergency traffic causes deterministic resequencing
- fouled deck propagates delay upstream
- missed commencement slot does not silently advance state
- carrier course/speed change recomputes carrier-relative geometry safely
- Approach cannot control a session before handoff
- bolter/waveoff preserves session identity and reinserts traffic
- stale telemetry suppresses precision approach/LSO guidance
- duplicate radio messages are suppressed
- mission/carrier identity change invalidates stale sessions
