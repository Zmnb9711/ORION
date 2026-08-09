# ORION Carrier ATC — Launch and Departure Operations

Status: design detail for the Carrier ATC architecture baseline before Virtual ATC Core (#61)

## Purpose

Carrier launch is a first-class operational domain. It must not be represented as a generic airport takeoff clearance because the aircraft moves through a constrained flight-deck resource system, is assigned to a specific catapult, is launched by deck/catapult coordination, and only then transfers to airborne Departure control.

The design separates three concerns:

- `CarrierOpsDirector`: owns the current launch/recovery cycle and whether launch operations are permitted.
- `CarrierDeckCoordinator`: owns deck movement, catapult allocation/readiness and launch sequencing.
- `CarrierDepartureController`: owns the aircraft after launch/airborne transition and manages departure routing/handoff.

## CarrierLaunchSession

Each launching aircraft receives a mission-scoped `CarrierLaunchSession` containing at least:

- session_id, mission_id, carrier_id
- aircraft_id, callsign, aircraft type
- formation_id/formation role when applicable
- current launch state
- controlling agency
- assigned catapult when known
- catapult assignment revision
- deck queue position / predecessor where known
- launch priority and reason
- launch/departure route or departure instruction set when known
- acknowledgement state for control instructions
- timestamps for state transitions and last radio exchange
- data capability/freshness flags
- abort/retry counters
- airborne/handoff outcome

The launch session is invalidated only by mission/carrier identity change, aircraft destruction/despawn, explicit cancellation, or completed departure handoff. A launch abort normally preserves the same session and enters a retry/requeue path.

## Launch state machine

Baseline state flow:

`STARTUP -> READY_FOR_DECK_MOVE -> DECK_MOVE_AUTHORIZED -> TAXIING_ON_DECK -> CAT_ASSIGNED -> QUEUED_FOR_CAT -> APPROACHING_CAT -> HOOKUP -> CAT_CONNECTED -> TENSION/READY -> FINAL_LAUNCH_CHECK -> LAUNCH_AUTHORIZED -> CATAPULT_STROKE -> AIRBORNE -> DEPARTURE_CONTROLLED -> HANDED_OFF`

Alternative paths:

`* -> HOLD_POSITION`

`CAT_ASSIGNED/QUEUED_FOR_CAT -> CAT_REASSIGNED`

`HOOKUP/CAT_CONNECTED/TENSION/READY/FINAL_LAUNCH_CHECK -> LAUNCH_ABORT -> SAFE/RESET -> REQUEUE`

`LAUNCH_AUTHORIZED -> ABORT_BEFORE_STROKE` only when an authoritative deck/catapult event indicates launch did not occur.

`AIRBORNE/DEPARTURE_CONTROLLED -> EMERGENCY_RETURN`

`* -> CANCELLED`

ORION must never infer catapult attachment, tension, launch authorization or catapult stroke solely from elapsed time.

## CarrierOpsDirector launch/recovery arbitration

`CarrierOpsDirector` publishes an authoritative operational cycle:

- `IDLE`
- `LAUNCH`
- `RECOVERY`
- `MIXED` only when explicitly supported/configured
- `SUSPENDED`

Deck and ATC controllers consume this state; they do not independently decide that launch is available. A recovery-critical or emergency state may suspend new launch releases. Existing aircraft already committed to a catapult are handled by an explicit continue/abort policy rather than silently dropped.

Unknown cycle state is conservative: ORION may discuss status but does not claim a launch clearance is available.

## Deck resource model

The deck is a constrained shared resource. `CarrierDeckCoordinator` maintains an observable resource board with:

- catapult identity
- catapult state: `UNKNOWN`, `UNAVAILABLE`, `AVAILABLE`, `RESERVED`, `OCCUPIED`, `READY`, `LAUNCHING`, `RESETTING`, `FAULT`
- currently assigned aircraft/session
- queue for that catapult where known
- last authoritative update and freshness
- launch-area/deck conflict flags where exposed
- current launch-cycle availability

A catapult may be allocated only when its capability/state supports that decision. `UNKNOWN` is never treated as `AVAILABLE`.

## Catapult allocation

Catapult assignment is deterministic and explainable. Inputs can include:

- actual DCS/Supercarrier catapult/deck state when exposed
- aircraft position and reachability on deck
- aircraft/formation launch order
- current queue lengths
- operational restrictions from mission/carrier configuration
- recovery-cycle conflicts
- emergency/priority overrides

Every assignment carries a revision number and reason. If a catapult becomes unavailable before commitment, the aircraft can be reassigned without creating a new launch session. Once the aircraft is physically committed/connected to a catapult, reassignment requires an explicit abort/reset path.

## Launch sequencing

`CarrierLaunchSequencer` may be implemented as a launch-mode view of the common traffic sequencer or as a carrier-specific component behind a shared sequencing interface. It tracks:

- ordered launch queue
- per-catapult queues
- formation/package relationships
- committed vs uncommitted aircraft
- deck/catapult readiness
- launch spacing policy
- launch-cycle suspension/resumption
- reasons for resequencing

The sequencer must not reorder an aircraft that is already committed to a catapult merely to optimize throughput unless an explicit safety/abort condition exists.

## Formation/package support

A section/division/package may be queued as a related launch group while each aircraft has an individual `CarrierLaunchSession`. Suggested relationship fields:

- `formation_id`
- `formation_role`
- `package_id`
- `planned_launch_order`
- `preceding_aircraft_id`
- `paired_catapult_id` when operationally relevant and known

The group relationship survives launch so Departure can sequence or hand off the formation coherently. ORION must not assume simultaneous or paired launch unless DCS/configuration confirms it.

## Deck movement and authority

Deck movement instructions are not generic airport taxi instructions. They are carrier-deck coordination events and may be partly non-radio/visual in DCS. ORION therefore separates:

- aircraft intent/readiness
- deck movement authorization
- observed movement
- arrival at catapult staging area

An instruction to move does not automatically advance state to `TAXIING_ON_DECK`; telemetry or explicit acknowledgement/event evidence is required when available.

If DCS does not expose safe deck-routing geometry, ORION must not fabricate turn-by-turn deck taxi paths. It may provide high-level catapult assignment/status and rely on native deck crew behavior.

## Hookup, tension and launch readiness

The final catapult sequence is modeled with explicit confidence/capability gates:

`APPROACHING_CAT -> HOOKUP -> CAT_CONNECTED -> TENSION/READY -> FINAL_LAUNCH_CHECK -> LAUNCH_AUTHORIZED`

These states may be collapsed when DCS does not expose enough observability, but ORION must never claim a hidden intermediate state as fact. Coarse mode can retain `ON_CATAPULT_PENDING_LAUNCH` until an authoritative launch event is observed.

`LAUNCH_AUTHORIZED` is an operational state, not a weapons or mission authorization. It indicates only that the carrier launch system has released the aircraft to launch.

## Launch abort and retry

A launch abort is a first-class event. It preserves session identity and records:

- state at abort
- abort reason/source
- catapult identity
- whether the aircraft remains physically committed
- required reset/reposition state
- retry eligibility
- queue impact

A failed/aborted attempt does not increment as a successful launch. Requeue is explicit and may receive a new catapult assignment revision.

If launch status becomes ambiguous after authorization, ORION waits for airborne/catapult evidence instead of assuming success.

## Airborne transition

`CATAPULT_STROKE -> AIRBORNE` requires positive evidence such as aircraft kinematics and/or launch event. At `AIRBORNE`, Deck/Catapult no longer owns the aircraft for flight-control instructions.

A transactional handoff transfers control to `CarrierDepartureController`:

- source: Deck/Catapult or Tower/PriFly policy layer as configured
- destination: Departure
- reason: launch complete / airborne
- departure frequency/channel when known
- issue and acknowledgement timestamps

Departure ownership begins only after the handoff is accepted/observed according to configured capability.

## Carrier Departure controller

Departure is an airborne ATC role with a distinct voice identity. It owns post-launch flight path/separation until the aircraft exits the carrier departure domain or is handed to another controller/mission agency.

The departure session view includes:

- launch origin/carrier
- current aircraft position/altitude/track/speed
- assigned departure route/instruction
- formation relationship
- carrier-relative boundary status
- traffic conflicts where observable
- emergency state
- next controlling agency and handoff status

Departure instructions are capability- and mission-configuration-grounded. ORION must not invent a departure radial, altitude or route if the mission/native DCS procedure does not provide one.

## Departure handoff boundary

Departure handoff is explicit and transactional, using the same common ATC primitive required by recovery:

`source_agency`, `destination_agency`, `reason`, `frequency/channel`, `issued_at`, `acknowledged_at`, `state`.

Potential destinations include another ATC sector/controller, AWACS/mission control, tanker coordination, or a mission-defined agency. Mission Control receiving tactical responsibility does not retroactively own carrier launch/deck operations.

## Emergency after launch

An immediate post-launch emergency creates `EMERGENCY_RETURN` or another mission-configured emergency path while preserving the launch/recovery history. Carrier ATC and Mission Control may share the emergency state, but Carrier ATC owns traffic/recovery sequencing while Mission Control owns tactical consequences.

Emergency return can pre-empt normal departure chatter and can request priority recovery. It does not bypass landing-area or LSO safety authority.

## Launch voice identities and radio behavior

Required audible identities:

- `CARRIER_AIR_BOSS` / PriFly for operational cycle and high-level deck/recovery authority when audible
- `CARRIER_DEPARTURE` for airborne departure control
- optional distinct deck/catapult voice identity only where the implementation intentionally verbalizes deck coordination

Native DCS deck-crew visual behavior should not be duplicated with unnecessary synthetic speech. Stable queue/catapult state is silent. Voice is used for meaningful control instructions, reassignment, suspension, abort, airborne handoff and emergencies.

Launch calls must not collide with LSO safety traffic. LSO/waveoff and immediate flight-safety events have higher priority than routine launch sequencing announcements.

## Launch/recovery conflict policy

Launch and recovery share the deck environment. The architecture therefore forbids independent local assumptions such as "catapult ready means launch now". `CarrierOpsDirector` arbitrates the operation and can block launch authorization due to:

- active/impending recovery window
- emergency inbound traffic
- fouled/unsafe deck state
- carrier operation suspension
- unknown critical deck state

The reason is machine-readable and visible in status/debrief.

## DCS capability degradation

The adapter exposes support separately for:

- deck movement observation
- catapult identity/state
- aircraft-catapult association
- hookup/connection/tension state
- launch authorization/event
- airborne detection
- carrier frequencies/departure data

If only airborne detection is reliable, ORION runs a coarse launch state machine and does not fabricate the missing deck/catapult phases. This is a deliberate supported mode, not an error.

## Observability

Per launch session status should expose:

- current state and controlling agency
- catapult assignment/revision
- queue position/predecessor
- commitment state
- operational cycle state
- capability/freshness summary
- abort/retry counters
- handoff transaction
- last sequencer decision and reason

Carrier-wide status exposes catapult resource board, launch queues, currently committed aircraft, suspension reason and launch/recovery arbitration state.

## Common primitives required from Virtual ATC Core #61

Carrier launch design confirms that #61 needs reusable primitives for:

- `AtcSessionIdentity`
- `ControllerOwnership`
- `ControllerHandoffTransaction`
- `SequencedTrafficEntry`
- `OperationalInstruction` with acknowledgement state
- `CapabilityValue` / freshness/confidence
- `TrafficPriority`
- event history / state-transition reason
- voice priority and duplicate suppression

These primitives must support both fixed-airfield ATC and moving carrier ATC without embedding airport-runway assumptions.

## Safety and authority boundary

Carrier launch clearance is traffic/deck authority only. It does not authorize weapons use, tactical mission execution or target engagement. Mission Control may influence launch priority/routing recommendations but cannot mark a catapult ready or bypass deck safety. Carrier ATC may report aircraft availability and hand off traffic but cannot select combat targets.