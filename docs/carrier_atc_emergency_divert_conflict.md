# ORION Carrier ATC Emergency, Divert, Lost-Comms and Conflict Policy

Status: final carrier-ATC design block before Virtual ATC Core (#61)

## Purpose

This document defines the common safety policy joining carrier recovery, launch/departure, fuel priority, landing-area state, controller ownership and multi-aircraft sequencing. The goal is deterministic and auditable behavior when normal carrier procedures are disrupted.

## Safety event model

Every abnormal condition is represented as structured state, not merely free-form voice text. Suggested common event types:

- DECLARED_EMERGENCY
- CRITICAL_FUEL
- BINGO / DIVERT_REQUIRED
- LANDING_AREA_FOUL
- RECOVERY_SUSPENDED
- LAUNCH_SUSPENDED
- CATAPULT_UNAVAILABLE
- MISSED_APPROACH
- BOLTER
- WAVEOFF
- LOST_COMMS
- TELEMETRY_STALE
- CONTROLLER_HANDOFF_FAILED
- TRAFFIC_CONFLICT
- NAV_AID_CAPABILITY_LOST

Each event records mission/session identity, source, severity, timestamp, freshness, affected aircraft/resources and machine-readable reason.

## Emergency priority

Emergency handling is a policy overlay on an existing `CarrierRecoverySession` or `CarrierLaunchSession`; it must not create an unrelated session unless the original identity is genuinely gone.

Baseline priority order:

1. immediate life/safety emergency
2. critically low fuel / unable to continue normal sequence
3. aircraft already committed to final/landing attempt or catapult stroke
4. traffic with an existing protected slot/EAT
5. normal sequence

An emergency override can advance one aircraft but must explicitly record which traffic was delayed or displaced and why. ORION should be able to answer: "why was aircraft X moved ahead of aircraft Y?"

## Critical fuel and bingo

Fuel is treated as a graded input rather than a single boolean when data is available. Suggested normalized states:

- NORMAL
- LOW
- CRITICAL
- BINGO / DIVERT_REQUIRED
- UNKNOWN

Fuel reports from the pilot can update session priority even if DCS telemetry is unavailable. Telemetry and pilot report are retained as separate evidence fields with timestamps; conflicting evidence is surfaced rather than silently overwritten.

Critical fuel can trigger:

- higher recovery sequencing priority
- reduced holding/EAT delay where operationally safe
- immediate divert recommendation if carrier recovery cannot be provided in time
- suppression of optional chatter
- explicit Mission Control visibility, without giving Mission Control authority over ATC sequencing

## Divert model

Divert is a first-class transaction, not simply session deletion.

Suggested `DivertPlan` fields:

- source carrier/session
- reason
- recommended divert airfield/carrier when known
- routing/frequency/TACAN data only when grounded in mission data
- fuel state at decision time
- acceptance/acknowledgement state
- controlling agency before and after divert handoff
- timestamp/revision

ORION must never invent a suitable divert field or navigation aid. If a safe divert destination cannot be established from mission data, the system reports that limitation and keeps the emergency visible.

A divert transition preserves the original recovery/departure history for debrief and closes the carrier session only when control has actually transferred or the aircraft outcome is otherwise known.

## Lost communications

Lost-comms is modeled as operational state with configurable detection policy. A radio timeout alone is insufficient when the aircraft is still visibly complying with instructions. Inputs may include:

- expected acknowledgement timeout
- absence of pilot voice response
- telemetry showing continued compliance/non-compliance
- explicit DCS radio/connectivity state where exposed

On suspected lost-comms:

- retain the aircraft in the traffic picture
- protect its expected path/slot conservatively
- avoid assigning conflicting traffic into that protected space
- retry only according to bounded radio policy
- surface the condition to the controlling agency
- do not let conversational agents consume the radio channel

Recovered communications returns the same session to normal control. Persistent lost-comms can lead to procedural hold, missed approach, divert or other mission-configured policy without silently removing the aircraft.

## Controller handoff failure

A controller handoff is not complete until the ownership transaction is accepted/observed. Failure modes include no acknowledgement, stale frequency data, unavailable destination agency or conflicting ownership state.

Policy:

- source controller remains owner until explicit completion or a safety override
- destination controller must not issue conflicting routine instructions before ownership
- safety-critical calls may still be emitted by an agency with independent authority, e.g. LSO waveoff or Tower landing-area warning
- failed handoff is observable and retry-bounded
- after retry exhaustion, the session enters HANDOFF_DEGRADED and follows a configured hold/continue/divert policy

## Landing-area foul and recovery suspension

Landing-area state is `CLEAR`, `FOUL`, or `UNKNOWN`; UNKNOWN is never treated as CLEAR.

When FOUL or recovery is suspended:

- no new landing clearance/commence authorization that depends on a clear deck
- traffic already on final/landing attempt follows explicit continue/waveoff policy
- waiting traffic remains sequenced but delayed
- EAT/slots are marked affected; revisions are versioned rather than silently overwritten
- emergency/critical-fuel traffic is reevaluated for immediate recovery vs divert

When the deck becomes clear, resumption is explicit and may trigger deterministic resequencing.

## Launch emergency and abort

Launch sessions support abnormal branches before and after catapult commitment.

Before catapult stroke:

`CAT_ASSIGNED/HOOKUP/READY -> LAUNCH_ABORTED -> HOLD | REASSIGN_CAT | RETURN_TO_DECK_QUEUE | SESSION_CANCELLED`

After catapult stroke the aircraft is treated as airborne; failures transition to Departure/emergency control rather than trying to roll back deck state.

A catapult becoming unavailable invalidates only assignments that depend on that resource. Other catapults may continue if `CarrierOpsDirector` and deck state permit. Resource reassignment is explicit and versioned.

## Multi-aircraft conflict model

Carrier ATC maintains one shared `TrafficConflictDetector` over launch, departure, recovery and missed-approach traffic. It does not replace DCS collision logic; it prevents ORION from issuing mutually incompatible instructions.

Conflict classes include:

- same marshal slot/altitude conflict
- insufficient sequencing interval
- conflicting Case I pattern occupancy
- final/missed-approach conflict
- launch path vs recovery traffic conflict
- duplicate catapult assignment
- simultaneous controller ownership conflict
- protected lost-comms path conflict
- emergency priority insertion conflict

Each detected conflict records involved sessions, class, severity, evidence and recommended resolution.

## Conflict resolution policy

Resolution is deterministic:

1. protect traffic already physically committed where safe
2. protect immediate emergency/critical-fuel requirements
3. preserve valid controller ownership
4. delay/resequence uncommitted traffic
5. reassign resources when possible
6. if safe resolution cannot be proven, stop issuing new clearances and enter conservative hold/suspend behavior

ORION must prefer delaying a clearance over fabricating separation.

## Launch/recovery arbitration

`CarrierOpsDirector` is the sole owner of carrier cycle arbitration. Controllers consume its state; they do not independently assume launch/recovery availability.

Suggested cycle states:

- IDLE
- LAUNCH
- RECOVERY
- MIXED when explicitly supported by configuration/telemetry
- SUSPENDED

Cycle changes are versioned operational events. A switch to recovery can freeze new launch assignments; a switch to launch can prevent new recovery releases as configured. Already committed catapult/landing traffic is handled by explicit safety policy rather than being cancelled blindly.

## Voice priority under abnormal conditions

Suggested priority ladder:

1. LSO/Tower immediate safety call: waveoff, foul deck, imminent conflict
2. emergency control instruction
3. critical fuel/divert instruction
4. controller handoff / mandatory procedural instruction
5. normal sequencing
6. advisory
7. free-form conversation

Routine duplicate suppression remains active, but safety messages bypass ordinary cooldown when the underlying condition changes materially or acknowledgement is overdue.

## Mission Control interaction

Carrier ATC publishes emergency, bingo/divert and carrier availability state to Mission Control. Mission Control may recommend tactical rerouting or mission abort but cannot reorder carrier traffic, clear a landing, issue a catapult launch, or override LSO/Tower safety authority.

Carrier ATC can consume threat-risk input from Mission Control as one policy input. A threat warning alone does not silently invalidate a safe ATC procedure; any resulting reroute/suspension is an explicit operational decision with reason.

## Common Virtual ATC primitives required by #61

The carrier design now establishes the following primitives as mandatory in Virtual ATC Core:

- `AtcSessionIdentity`
- `ControllerAgency`
- `ControllerOwnership`
- `ControllerHandoffTransaction`
- `OperationalInstruction` with acknowledgement/retry state
- `TrafficPriority`
- `SequencedTrafficEntry`
- `OperationalCapability` + freshness/confidence
- `SafetyEvent`
- `EmergencyState`
- `DivertPlan`
- `TrafficConflict`
- `ResourceAssignment`
- deterministic reason/event history
- voice priority and duplicate-suppression metadata

These primitives must be domain-neutral enough for land-based ATC, while carrier-specific procedure engines remain separate.

## Required stress tests after implementation

Carrier ATC implementation must eventually cover at least:

- multiple Case III aircraft with EAT resequencing after a bolter
- Case I pattern traffic plus emergency insertion
- Case II visual transition failure followed by missed approach
- foul deck with one aircraft on final and others in marshal
- critical-fuel aircraft during recovery suspension
- lost-comms aircraft retaining protected traffic space
- catapult failure and reassignment without duplicate resource allocation
- simultaneous launch/recovery cycle transition
- failed controller handoff without dual ownership
- stale carrier telemetry causing conservative degradation
- mission change invalidating all old operational sessions safely

## Design completion criterion

Carrier ATC design is considered ready for freeze when the architecture document, launch/departure document and this abnormal-operations policy are mutually consistent, common #61 primitives are identified, and no carrier procedure depends on invented DCS state.