# ORION Carrier ATC Cross-Document Audit

Status: complete; design ready to feed Virtual ATC Core (#61)

## Scope

Audited together:

- `carrier_atc_architecture.md`
- `carrier_atc_case_iii.md`
- `carrier_atc_launch_departure.md`
- `carrier_atc_emergency_divert_conflict.md`
- `carrier_atc_design_freeze.md`

The goal was to identify contradictions in controller ownership, handoff timing, abnormal-state modeling, sequencing/resource commitment, and capability/freshness behavior before implementation begins.

## Findings

### 1. Single global controller owner is insufficient

Earlier shorthand such as `current controlling agency` is too coarse for carrier operations. At final approach, Approach can own airborne traffic sequencing, Tower/PriFly can own landing-area safety, and LSO can own final guidance without any of those roles being duplicates.

Resolution: #61 must model `ControllerAuthorityScope` and allow one owner per scope, not one owner for the whole session.

Required scopes include at least:

- `DECK_RESOURCE`
- `FLIGHT_TRAFFIC`
- `LANDING_AREA`
- `FINAL_GUIDANCE`
- `MISSION_TACTICAL`

Same-scope dual ownership is a conflict; different-scope simultaneous authority is valid.

### 2. Launch-to-Departure cannot be purely acknowledgement-gated

The launch document previously described Departure ownership as beginning only after accepted/observed handoff. That is unsafe as a general rule because after positive airborne transition the deck/catapult authority is physically no longer the airborne controller even if radio contact with Departure is pending.

Resolution: #61 must support two handoff modes:

- acknowledgement-gated transfer, e.g. Marshal -> Approach;
- event-gated irreversible transfer, e.g. catapult/airborne -> Departure.

For event-gated launch transition, Departure becomes designated `FLIGHT_TRAFFIC` owner when authoritative airborne evidence occurs; radio contact may remain `CONTACT_PENDING` and be tracked as degraded communications rather than reverting ownership to Deck.

### 3. Emergency/lost-comms must not replace procedural state

Earlier shorthand such as `* -> EMERGENCY_PRIORITY` can be misread as changing the primary state. That would lose critical information such as whether the aircraft is still in marshal, commencing, on final, in groove, queued for a catapult, or already airborne.

Resolution: abnormal conditions are orthogonal operational overlays on a preserved procedural state.

Examples:

- `EMERGENCY`
- `CRITICAL_FUEL`
- `BINGO_DIVERT_REQUIRED`
- `LOST_COMMS_SUSPECTED`
- `LOST_COMMS_CONFIRMED`
- `HANDOFF_DEGRADED`
- `TELEMETRY_STALE`
- `NAV_AID_DEGRADED`
- `RECOVERY_SUSPENDED_AFFECTED`

### 4. Commitment must be explicit

Recovery and launch documents both protect "committed" traffic, but relying on procedure-specific state names would make the common sequencer brittle.

Resolution: #61 requires domain-neutral `CommitmentState`:

- `UNCOMMITTED`
- `RESERVED`
- `PROCEDURALLY_COMMITTED`
- `PHYSICALLY_COMMITTED`
- `IRREVERSIBLE`

Examples: assigned EAT=`RESERVED`; commencement begun=`PROCEDURALLY_COMMITTED`; final/groove=`PHYSICALLY_COMMITTED`; catapult stroke=`IRREVERSIBLE`.

### 5. Capability/freshness rules are consistent and must be central

All documents agree on conservative degradation. The core must encode this once rather than leave it to individual controllers.

Canonical invariant: `UNKNOWN` or stale operational data never silently becomes a safe/available condition. Landing-area UNKNOWN is not CLEAR, catapult UNKNOWN is not AVAILABLE, unknown visual acquisition is not VISUAL_ACQUIRED, and stale carrier/final geometry cannot support precision LSO/approach corrections.

### 6. Instruction speech and state advancement are separate

The documents consistently require acknowledgement/event evidence before many transitions. #61 therefore needs `OperationalInstruction` as a stateful object with semantic action, authority scope, acknowledgement state, retry policy, expiration/stale conditions and voice priority. Speaking the instruction does not by itself prove compliance.

### 7. Sequencing and resource assignment can share common interfaces

Case III EAT sequencing, Case I visual occupancy, catapult queues and emergency insertion use different domain policies but share common needs: priority, commitment, predecessor/successor relation, revision/reason history and conflict detection.

Resolution: common core supplies `SequencedTrafficEntry`, `TrafficPriority`, `CommitmentState`, `ResourceAssignment` and `TrafficConflict`; carrier engines supply procedure-specific scheduling logic.

## Canonical authority examples

### Case III final

- Approach: `FLIGHT_TRAFFIC`
- Tower/PriFly: `LANDING_AREA`
- LSO: `FINAL_GUIDANCE` after the configured handoff boundary

### Case I groove

- Tower/PriFly: `LANDING_AREA`
- LSO: `FINAL_GUIDANCE`
- Tower does not issue LSO correction semantics; LSO does not claim the landing area clear.

### Catapult launch

Before airborne:

- Deck/Catapult: `DECK_RESOURCE`

After authoritative airborne event:

- Departure: `FLIGHT_TRAFFIC`
- radio contact may still be pending/degraded
- Deck no longer has airborne flight-control ownership

### Mission Control interaction

- Mission Control: `MISSION_TACTICAL`
- ATC agencies retain their own traffic/safety scopes
- tactical authority cannot bypass sequencing, landing-area or LSO safety authority

## Canonical common contract for #61

Virtual ATC Core must provide domain-neutral equivalents of:

- `AtcSessionIdentity`
- `ControllerAgency`
- `ControllerAuthorityScope`
- `ControllerOwnership`
- `ControllerHandoffTransaction`
- transfer mode: acknowledgement-gated vs event-gated irreversible
- `OperationalInstruction`
- acknowledgement/retry/contact state
- `TrafficPriority`
- `CommitmentState`
- `SequencedTrafficEntry`
- `OperationalCapability` / freshness / confidence wrapper
- `SafetyEvent`
- `EmergencyState`
- operational overlays
- `DivertPlan`
- `TrafficConflict`
- `ResourceAssignment`
- deterministic event/reason history
- voice priority, pre-emption and duplicate-suppression metadata

The common core must not embed fixed-runway, Case I/II/III, catapult or carrier geometry assumptions.

## Carrier-specific contract after #61

Carrier-only components remain outside generic ATC core:

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

## Implementation gates for #61

#61 is not considered complete unless tests prove at least:

1. two agencies cannot own the same authority scope for one session;
2. different scopes can coexist safely (Tower landing area + LSO final guidance);
3. acknowledgement-gated handoff preserves source ownership until completion;
4. event-gated airborne handoff removes deck flight authority even with contact pending;
5. emergency and lost-comms overlays preserve procedural state;
6. stale/unknown capability cannot produce a positive safety assertion;
7. instruction transmission alone does not advance acknowledgement-gated procedural state;
8. commitment level influences resequencing/conflict resolution deterministically;
9. voice priority cannot confer authority outside the speaker's scope;
10. all session/ownership/instruction transitions retain reasoned event history.

## Audit conclusion

No blocking architecture contradiction remains after applying the canonical rules in `carrier_atc_design_freeze.md` and this audit. Carrier ATC design is frozen as the implementation input to Virtual ATC Core #61.

Simulator-specific phraseology, geometry thresholds and module-specific DCS adapters may be refined later. Authority scopes, handoff transfer modes, procedural-state/overlay separation, commitment semantics and capability/freshness invariants require an explicit architecture revision if changed.
