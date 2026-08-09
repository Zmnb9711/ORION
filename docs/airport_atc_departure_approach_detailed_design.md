# ORION Fixed-Airfield ATC — Departure / Approach / Arrival Detailed Design

Status: detailed design before merging Virtual ATC Core #61

## Purpose
Define the airborne terminal-control domain for fixed airfields before implementation. Departure, Approach/Arrival and Tower remain distinct logical agencies even when a DCS mission exposes only one frequency or simplified native ATC behavior.

## Core invariants
1. Tower takeoff clearance does not grant Departure authority before the aircraft is airborne.
2. Departure owns post-takeoff terminal traffic only after an explicit/event-gated handoff.
3. Approach clearance is not landing clearance; Tower retains runway/landing authority.
4. Frequency tuning alone never proves controller ownership.
5. Visual acquisition is evidence-based; geometry alone cannot fabricate "field in sight" or traffic-in-sight reports.
6. Instrument approach capability is capability/freshness-gated; ORION never advertises an aid or procedure only because the real airfield would normally have it.
7. Go-around/missed approach preserves the same ATC session and creates explicit downstream coordination.
8. A runway/configuration change never silently mutates an issued approach or landing clearance.
9. Committed traffic is protected unless safety/emergency policy requires intervention.
10. All sequencing/handoff decisions are deterministic, explainable and auditable.

## Terminal operational picture
`TerminalAirspaceState` should contain, when known:
- facility/mission identity
- terminal airspace bounds/sectors
- active runway configuration/version
- departure/arrival routes and fixes
- traffic picture with position, velocity, altitude and freshness
- weather/visibility/cloud information
- approach/navigation capabilities (ILS/TACAN/NDB/RNAV/visual/PAR where modeled)
- missed-approach/go-around routing capability
- frequencies/controller availability
- restricted/no-fly/mission constraints
- confidence/capability/freshness for all externally sourced data

Unknown or stale data does not become positive clearance evidence.

## Departure flow
Normal departure session:
`AIRBORNE -> DEPARTURE_HANDOFF_PENDING -> DEPARTURE_CONTROLLED -> INITIAL_CLIMB -> TERMINAL_DEPARTURE -> EXITING_TERMINAL -> HANDED_OFF`

Possible branches:
`AIRBORNE -> IMMEDIATE_RETURN`
`* -> EMERGENCY_PRIORITY`
`* -> LOST_COMMS`
`* -> HOLD/DELAY`
`* -> NATIVE_FALLBACK`

### Tower to Departure handoff
The handoff is normally event-gated by reliable `AIRBORNE` evidence. Tower may retain runway/local authority while `FLIGHT_TRAFFIC` transfers to Departure. The destination controller does not issue conflicting post-takeoff instructions before authority transfer.

The transaction records source/destination, scopes, event evidence, frequency/channel if known, contact state, issue/complete timestamps and reason.

### Departure guidance
Departure may issue headings, climb/altitude instructions, route joins, departure sequencing and traffic advisories only when corresponding state/capability is available. If precise radar-like traffic geometry is unavailable, phraseology degrades instead of fabricating vectors or separation.

Departure sequencing uses shared priority/commitment primitives. Emergency/critical-fuel traffic can advance ahead of non-committed normal traffic; physically committed conflicts remain protected.

### Immediate return after takeoff
An immediate return is first-class. The session retains identity/history and can be re-routed into Approach/Tower coordination without closing/recreating the session. Priority can be raised for emergency or technical return. Runway selection and pattern/approach choice remain explicit and capability-gated.

## Arrival / Approach flow
Normal arrival session:
`INBOUND -> APPROACH_CHECKED_IN -> ARRIVAL_SEQUENCED -> APPROACH_ASSIGNED -> APPROACH_CLEARED -> FINAL_APPROACH -> TOWER_HANDOFF -> LANDING_CLEARED -> LANDING_ATTEMPT`

Alternative branches:
`APPROACH_ASSIGNED -> VISUAL_APPROACH`
`APPROACH_ASSIGNED -> OVERHEAD_PATTERN`
`APPROACH_ASSIGNED -> INSTRUMENT_APPROACH`
`FINAL_APPROACH -> GO_AROUND/MISSED_APPROACH -> RESEQUENCE`
`* -> HOLDING`
`* -> DIVERTED`
`* -> EMERGENCY_PRIORITY`
`* -> LOST_COMMS`

## Arrival sequencing
`AirportTrafficSequencer` owns the ordered terminal arrival plan. It tracks sequence position, predecessor/successor, priority, commitment, runway/configuration version, approach type, expected merge/final timing where modeled and any hold/resequence reason.

Recalculation triggers include:
- new inbound/cancelled/diverting traffic
- emergency/critical-fuel changes
- runway/configuration change
- weather/capability change
- missed approach/go-around
- failed visual acquisition
- traffic failing to progress within tolerance
- loss/restoration of terminal sensor/nav capability

Committed traffic is not casually reordered. Every resequence records old/new position and machine-readable reason.

## Visual approach
A visual approach requires explicit visual evidence from the pilot or equivalent simulator-supported confirmation. Geometry/weather may establish eligibility but cannot fabricate visual acquisition.

Suggested states:
`VISUAL_OFFERED -> VISUAL_REQUESTED/ACCEPTED -> VISUAL_ACQUIRED -> VISUAL_SEQUENCED -> TOWER_HANDOFF -> FINAL`

If visual contact is not established:
`VISUAL_NOT_ACQUIRED -> INSTRUMENT_CONTINUE | VECTOR/HOLD | RESEQUENCE | DIVERT`

Traffic-in-sight claims are also evidence-based. ORION does not transfer separation responsibility implicitly unless the procedure/policy explicitly models it.

## Standard traffic pattern
The airport visual-pattern engine should support configurable left/right patterns with coarse states such as:
`INITIAL/ENTRY -> CROSSWIND -> DOWNWIND -> BASE -> FINAL`

Pattern entry, sequencing and runway ownership are distinct. Tower controls local pattern/runway activity; Approach may deliver aircraft to the pattern boundary depending on airfield complexity.

Touch-and-go, stop-and-go, low approach and full-stop are separate requested/cleared outcomes and must not be inferred from aircraft motion alone.

## Military overhead pattern
Overhead is a dedicated military procedure adapter, not a civilian visual pattern with renamed legs.

Suggested states:
`OVERHEAD_INBOUND -> INITIAL -> BREAK -> DOWNWIND -> ABEAM -> BASE/FINAL_TURN -> FINAL -> LANDING_ATTEMPT`

The engine preserves formation/section relationships and can split aircraft into individual landing sequence slots. Pattern altitude, break point, interval and side are configuration/policy data, not universal constants hard-coded into generic ATC core.

A late break, insufficient spacing, runway conflict or emergency may produce `EXTEND`, `GO_AROUND`, `RESEQUENCE` or a revised break instruction. Stable geometry is silent unless a report/instruction is due.

## Instrument approach
Instrument approach is represented as structured procedure state rather than a single "cleared approach" phrase.

Suggested generic states:
`APPROACH_ASSIGNED -> INTERCEPT/INITIAL_SEGMENT -> ESTABLISHED -> DESCENT -> FINAL_APPROACH -> MINIMUMS/DECISION_GATE -> LANDING_ATTEMPT`

The actual procedure can be ILS, TACAN, NDB, RNAV-like mission route, PAR-guided or mission-defined. ORION advertises only procedures/capabilities confirmed by mission configuration/DCS adapter.

Clearance data should include approach identifier/type, runway, transition/fix if known, altitude/constraints when available, missed-approach policy, revision/configuration version and capability source/freshness.

## Missed approach / go-around
Missed approach and go-around are first-class and preserve session identity.

State branch:
`FINAL_APPROACH/LANDING_ATTEMPT -> GO_AROUND_DECLARED/ORDERED -> MISSED_APPROACH -> CLIMBOUT -> APPROACH/DEPARTURE_COORDINATION -> RESEQUENCE | DIVERT`

Possible triggers include pilot action, Tower instruction, runway conflict/occupancy, unstable approach policy, runway/configuration change, weather/capability loss or traffic conflict.

Authority after go-around is explicit. Tower may initially issue the immediate safety instruction, while FLIGHT_TRAFFIC authority is then transferred to Approach/Departure according to configured local procedure. Dual ownership of the same scope is forbidden.

## Approach to Tower handoff
Approach retains flight-traffic authority until handoff conditions are met. Tower takes local/runway-facing control through an acknowledgement/event transaction. A tuned Tower frequency alone is not proof of handoff.

Tower may hold `LANDING_AREA` while Approach still owns `FLIGHT_TRAFFIC` during early final; scope-based authority therefore remains essential.

## Runway/configuration changes while airborne
A versioned runway change triggers re-evaluation of non-committed approach assignments and terminal queues. Issued clearances are superseded explicitly, never silently rewritten.

Physically committed aircraft on short final or already in a go-around safety maneuver are protected unless a safety condition requires intervention. The engine records why traffic was retained, re-cleared, resequenced or diverted.

## Holding
Holding is first-class where needed for traffic, weather, runway closure or lost approach capacity. A holding assignment is structured with fix/reference, altitude/block, direction/profile when known, expected delay/release condition if available, revision and freshness.

If precise holding geometry is unavailable, ORION may use coarse mission-defined hold instructions but must not fabricate navaid radials/distances.

## Separation / conflict classes
Terminal conflict detection should cover at least:
- converging arrivals
- arrival vs departure paths
- go-around vs departing traffic
- visual-pattern occupancy conflicts
- overhead-break spacing conflicts
- final approach vs runway occupancy
- duplicate approach slot/resource assignment
- altitude/route crossing where geometry permits
- controller ownership conflicts
- holding-stack/slot conflicts where modeled

Conservative rule: when safe separation cannot be established from available state, suspend/restrict the affected clearance rather than assuming safety.

## Precision Approach / PAR
PAR is a separate controller/procedure adapter layered above the common terminal engine. It may issue high-frequency heading/glideslope corrections only when fresh precision geometry is available. Loss/staleness of precision data immediately degrades guidance and can trigger missed-approach policy.

PAR should have its own voice identity where configured, but shares session identity, priority, handoff and audit primitives.

## Lost communications
Lost comms is an overlay, not a replacement procedural state. Detection combines communication timeout policy with telemetry/session evidence. The aircraft remains in sequence/protected airspace according to configured procedure. Re-established communications remove the overlay explicitly; they do not rewind procedural state.

## Voice behavior
Departure, Approach/Arrival, Tower and PAR can use distinct voices. Safety-critical heading/altitude/runway/go-around instructions pre-empt casual speech. Readback/acknowledgement policy applies to material control instructions. Free-form pilot language is normalized to structured intents rather than requiring exact phraseology.

## DCS adapter boundary
`AirportDcsAdapter` supplies observations and optionally mirrors native ATC actions. It does not decide sequencing or authority. Unsupported native behavior uses ORION's richer internal state with explicit simulator-sync capability/result and fallback/degraded mode when required.

## Required pre-implementation tests
1. Tower -> Departure authority cannot transfer before airborne evidence.
2. Departure cannot issue scope-conflicting instructions before handoff.
3. Approach clearance never grants landing authority.
4. Frequency tuning alone cannot complete handoff.
5. Visual approach cannot enter VISUAL_ACQUIRED without evidence.
6. Traffic-in-sight is not inferred from geometry alone.
7. Instrument approach cannot advertise unsupported nav capability.
8. Runway change supersedes non-committed approach assignments explicitly.
9. Go-around preserves session identity/history.
10. Tower go-around instruction leads to explicit downstream authority transfer.
11. Overhead pattern preserves formation relationship while creating individual sequence slots.
12. Touch-and-go/stop-and-go/full-stop remain distinct clearances.
13. Emergency can resequence non-committed arrivals/departures.
14. Physically committed traffic is not displaced by ordinary priority.
15. Holding assignments cannot fabricate unavailable geometry.
16. PAR guidance degrades immediately when precision data is stale.
17. Lost-comms overlay preserves current procedural state.
18. Every resequence/handoff/go-around decision produces a reasoned audit event.

## Implementation boundary
These are airport-domain procedure rules above Virtual ATC Core. Generic authority, instructions, acknowledgements, priority, commitment, overlays, event history, conflicts/resources and simulator-sync remain domain-neutral in #61.
