# ORION Carrier ATC Design Freeze and Virtual ATC Core Contract

Status: architecture audit complete; implementation contract for Virtual ATC Core (#61)

## Purpose

This document records the final cross-document audit of the Carrier ATC design and defines the canonical invariants that Virtual ATC Core must support. When wording in earlier carrier design notes is ambiguous, this document is authoritative.

## Audit result

The Carrier ATC design is internally viable, but the audit identified two important modeling corrections that must be present in #61 from the beginning:

1. controller authority must be scoped by control domain rather than represented by one global owner;
2. emergency/lost-comms/degraded conditions must be operational overlays on procedural state rather than destructive replacements for that state.

These corrections resolve the remaining apparent contradictions between recovery, LSO/Tower authority, launch-to-Departure handoff and abnormal-operations handling.

## Canonical controller authority model

A session can have multiple agencies with authority at the same time only when their authority scopes do not conflict.

Required common primitive:

`ControllerAuthorityScope`

Baseline scopes:

- `DECK_RESOURCE` — deck movement/catapult resource authority
- `FLIGHT_TRAFFIC` — routing, separation, sequencing and airborne traffic instructions
- `LANDING_AREA` — clear/foul/suspend/landing-area safety authority
- `FINAL_GUIDANCE` — LSO final landing guidance and waveoff authority
- `MISSION_TACTICAL` — tactical mission responsibility outside ATC

Rule: there may be at most one authoritative owner for a given session and authority scope at a time. Different scopes may be owned concurrently by different agencies.

Examples:

- Case III final: Approach may own `FLIGHT_TRAFFIC`, Tower/PriFly owns `LANDING_AREA`, then LSO acquires `FINAL_GUIDANCE` near the groove.
- In groove: LSO owns `FINAL_GUIDANCE`; Tower/PriFly still owns `LANDING_AREA`. Neither may issue instructions outside its scope.
- Carrier launch before stroke: Deck/Catapult owns `DECK_RESOURCE`; an airborne Departure authority may not yet exist.
- After positive airborne transition: Deck/Catapult immediately loses `DECK_RESOURCE` relevance for flight-control purposes and Departure acquires/assumes `FLIGHT_TRAFFIC` according to the launch transition policy.
- Mission Control may own `MISSION_TACTICAL` while Carrier ATC owns `FLIGHT_TRAFFIC`; this does not let Mission Control bypass ATC sequencing.

A conflict exists when two agencies attempt to own the same scope for the same session simultaneously.

## Canonical handoff model

`ControllerHandoffTransaction` transfers one or more explicit authority scopes. It contains:

- session identity
- source agency
- destination agency
- authority scopes being transferred
- reason
- frequency/channel when known
- issued timestamp
- acknowledgement/contact state
- transfer trigger
- retry/timeout policy
- completed/failed/degraded state

There are two transfer modes:

### Acknowledgement-gated transfer

Used where the source can safely retain control until the destination accepts the handoff, e.g. Marshal -> Approach.

The source remains owner of the transferred scope until acknowledgement/accepted transition or a defined safety override.

### Event-gated irreversible transfer

Used where a physical state change makes the old authority invalid, e.g. catapult stroke/airborne transition.

Once authoritative evidence shows the aircraft airborne:

- Deck/Catapult no longer owns any airborne `FLIGHT_TRAFFIC` authority;
- Departure becomes the designated `FLIGHT_TRAFFIC` owner according to configured carrier policy even if radio contact is still `CONTACT_PENDING`;
- lack of radio acknowledgement is represented as degraded/lost-comms contact state, not by pretending Deck still controls airborne flight;
- the handoff transaction remains open until radio/contact completion for observability.

This distinction is mandatory in #61.

## Procedural state vs operational overlays

A session has a primary procedural state plus zero or more orthogonal operational overlays.

Examples of procedural state:

- `EAT_WAIT`
- `COMMENCING`
- `FINAL_APPROACH`
- `IN_GROOVE`
- `QUEUED_FOR_CAT`
- `AIRBORNE`
- `DEPARTURE_CONTROLLED`

Examples of overlays:

- `EMERGENCY`
- `CRITICAL_FUEL`
- `BINGO_DIVERT_REQUIRED`
- `LOST_COMMS_SUSPECTED`
- `LOST_COMMS_CONFIRMED`
- `HANDOFF_DEGRADED`
- `TELEMETRY_STALE`
- `NAV_AID_DEGRADED`
- `RECOVERY_SUSPENDED_AFFECTED`

Therefore earlier shorthand such as `* -> EMERGENCY_PRIORITY` is interpreted as applying an emergency overlay/priority policy while preserving the aircraft's procedural position. The system must still know whether an emergency aircraft is in marshal, on final, in groove, on catapult, or airborne.

## Canonical traffic priority

Priority is common across carrier recovery/launch and later land-based ATC. It is deterministic, explainable and separate from procedural state.

Baseline ordering:

1. immediate life/safety emergency
2. critically low fuel / unable to continue normal sequence
3. physically committed traffic whose interruption would create greater safety risk
4. protected assigned slot/EAT or resource commitment
5. normal sequence/order

Context-specific safety rules may override raw ordering. For example, an emergency arrival does not automatically invalidate an aircraft already in an irreversible catapult stroke or an aircraft already at a critical final-landing point if intervention would be less safe.

Every priority override records reason and displaced/affected traffic.

## Commitment model

`CommitmentState` is required as a shared primitive. Suggested values:

- `UNCOMMITTED`
- `RESERVED`
- `PROCEDURALLY_COMMITTED`
- `PHYSICALLY_COMMITTED`
- `IRREVERSIBLE`

Carrier examples:

- EAT assigned: `RESERVED`
- commencement begun: `PROCEDURALLY_COMMITTED`
- aircraft on final/in groove: `PHYSICALLY_COMMITTED`
- catapult stroke: `IRREVERSIBLE`

Sequencers and emergency arbitration use commitment explicitly rather than inferring it from arbitrary state names.

## Capability and freshness contract

Every DCS-derived operational datum that can be unavailable or stale is represented with capability/freshness metadata. Common primitive should carry at least:

- supported/unsupported/unknown capability
- value when present
- source
- observed_at
- age/freshness classification
- confidence when inferred rather than directly observed

`UNKNOWN` and stale values never silently become safe/available values. In particular:

- landing area UNKNOWN != CLEAR
- catapult UNKNOWN != AVAILABLE
- unknown ICLS/ACLS/PALS != available
- stale carrier geometry cannot support precision approach/LSO corrections
- unknown visual acquisition cannot become VISUAL_ACQUIRED

## Instruction and acknowledgement contract

`OperationalInstruction` is a stateful object, not just generated text. It contains instruction identity, session, issuing agency, authority scope, semantic action, parameters, issue time, acknowledgement requirement/state, retry count/policy, expiration/stale condition and voice priority.

State advancement that requires pilot acknowledgement cannot occur merely because the instruction was spoken. Conversely, authoritative telemetry/events may satisfy transitions where procedure policy explicitly permits event evidence.

## Traffic conflict contract

`TrafficConflict` applies across recovery, launch, missed approach and departure. Conflict classes include marshal/resource collision, insufficient interval, Case I occupancy conflict, final/missed-approach conflict, launch/recovery interaction, duplicate catapult assignment, protected lost-comms path conflict and same-scope controller ownership conflict.

If safe resolution cannot be established, ORION delays/resequences/suspends rather than fabricating separation.

## CarrierOpsDirector contract

`CarrierOpsDirector` is the sole carrier-cycle arbitration authority and publishes versioned state: `IDLE`, `LAUNCH`, `RECOVERY`, `MIXED` only when explicitly supported, or `SUSPENDED`.

Individual Tower, Marshal, Approach, LSO, Deck or Departure controllers may react to this state but cannot independently claim that launch/recovery is available.

## Voice authority and priority

Distinct carrier voices remain mandatory: Air Boss/PriFly, Departure, Marshal, Approach, Tower and LSO. Optional deck/catapult synthetic voice is permitted only when it adds value beyond native DCS deck-crew behavior.

Priority baseline:

1. immediate LSO/Tower safety call
2. emergency flight-control instruction
3. critical fuel/divert instruction
4. mandatory controller handoff/procedural instruction
5. normal sequencing
6. advisory
7. free-form conversation

Voice priority never grants authority outside the issuing agency's scope.

## Common #61 data-model contract

Virtual ATC Core #61 must introduce domain-neutral equivalents of:

- `AtcSessionIdentity`
- `ControllerAgency`
- `ControllerAuthorityScope`
- `ControllerOwnership`
- `ControllerHandoffTransaction`
- `OperationalInstruction`
- acknowledgement/retry state
- `TrafficPriority`
- `CommitmentState`
- `SequencedTrafficEntry`
- `OperationalCapability` / freshness/confidence wrapper
- `SafetyEvent`
- `EmergencyState`
- `DivertPlan`
- `TrafficConflict`
- `ResourceAssignment`
- reasoned event/state history
- voice priority/pre-emption/deduplication metadata

The core must not contain runway-only or carrier-only assumptions. Fixed-airfield ATC and Carrier ATC consume the same common primitives but use separate domain procedure engines.

## Carrier-specific engines after #61

Carrier-specific implementation remains outside generic core:

- `CarrierStateProvider`
- `CarrierOpsDirector`
- `CarrierTrafficSequencer`
- `CarrierRecoverySessionStore`
- `CarrierLaunchSessionStore`
- `CaseIRecoveryEngine`
- `CaseIIRecoveryEngine`
- `CaseIIIRecoveryEngine`
- `CarrierMarshalController`
- `CarrierApproachController`
- `CarrierTowerController`
- `CarrierDepartureController`
- `CarrierLSOController`
- `CarrierDeckCoordinator`
- `CarrierVoiceRouter`
- `CarrierDcsAdapter`

## Design freeze criteria

Carrier ATC architecture is frozen for the start of #61 when all of the following hold:

- Case I, II and III state/ownership models are defined;
- launch/departure/resource model is defined;
- emergency/divert/lost-comms/conflict policy is defined;
- authority scopes remove false Tower/LSO and Deck/Departure ownership conflicts;
- abnormal conditions preserve procedural state as overlays;
- capability/freshness rules prevent invented DCS state;
- common Virtual ATC primitives are explicitly identified;
- Mission Control and Carrier ATC authority boundaries remain separate.

All criteria are satisfied by the current design documents plus this audit contract.

## Design freeze decision

Carrier ATC design is APPROVED FOR FREEZE as the input contract to Virtual ATC Core #61.

Future implementation may refine simulator-specific phraseology, exact geometry thresholds and module-specific DCS adapters, but changes to the authority-scope model, session identity, handoff semantics, safety overlays or capability/freshness invariants require an explicit architecture revision rather than an incidental implementation change.
