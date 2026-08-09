# PR #65 — Airport Departure Procedural Engine

## Goal
Build the fixed-airfield departure procedural layer from the departure holding point through runway entry, takeoff, confirmed airborne state, Tower→Departure handoff, and initial departure control.

The engine must sit on top of the Ground/Tower authority and runway-safety contracts already merged in #63/#64. ORION remains the pilot-facing interface; standard DCS ATC menu interaction is not required for the normal ORION workflow.

## Departure state machine
The canonical procedural progression is:

`HOLDING_POINT -> LINE_UP_CLEARED -> LINED_UP -> TAKEOFF_CLEARED -> TAKEOFF_ROLL -> AIRBORNE -> DEPARTURE_CONTROL`

Additional controlled states include:
- `HOLDING_FOR_TRAFFIC`
- `TAKEOFF_CLEARANCE_CANCELLED`
- `REJECTED_TAKEOFF`
- `STOPPED_ON_RUNWAY`
- `RUNWAY_VACATED_AFTER_ABORT`

State changes must be driven by positive procedural/physical evidence; a radio acknowledgement alone cannot imply physical runway entry, takeoff roll, or airborne state.

## Tower departure sequence
Tower must support:
- holding at the runway boundary while landing/crossing/departing traffic conflicts exist;
- `line up and wait` as a distinct clearance;
- takeoff clearance as a distinct acknowledgement-aware clearance;
- cancellation/withholding of a takeoff clearance before physical commitment;
- physical detection/observation of lineup, takeoff roll and `AIRBORNE`;
- runway reservation/occupancy coordination using the existing canonical runway resource contracts;
- no runway entry merely because the taxi route reaches a runway boundary.

## Runway safety invariants
1. `SURFACE_MOVEMENT` taxi authority never implies `LANDING_AREA` runway-entry authority.
2. Tower must own the relevant `LANDING_AREA` authority before issuing lineup/takeoff instructions.
3. A positive takeoff clearance requires runway state sufficiently current and usable under the existing runway safety rules.
4. Crossing/landing/departure conflicts prevent incompatible positive clearances.
5. A physically committed takeoff roll cannot be silently cancelled as though the aircraft had not entered the runway operation.
6. `AIRBORNE` must come from physical evidence and gates Tower→Departure procedural handoff.
7. Duplicate physical events are idempotent and audit-visible without causing duplicate authority transitions.

## Tower -> Departure handoff
Handoff to Departure occurs only after confirmed `AIRBORNE`.

The handoff must:
- transfer the appropriate airborne/control authority from Tower to Departure;
- preserve the session and audit trail;
- expose the next frequency/controller information when available;
- avoid duplicate handoff on repeated `AIRBORNE` observations;
- leave runway-resource cleanup/availability to the canonical runway operation lifecycle rather than inventing a parallel state.

## Departure controller
The first Departure procedural layer must support:
- initial climb clearance;
- assigned heading/track;
- altitude restrictions;
- direct-to fixes when known;
- continuation on an assigned/known departure route;
- acknowledgement-aware amendments;
- free-form pilot questions about current clearance and immediate next action.

Representative questions:
- `какой курс после взлета?`
- `до какой высоты набирать?`
- `можно левым?`
- `когда переходить на Departure?`
- `какая частота Departure?`
- `какое давление поставить?`
- `what heading after departure?`
- `what altitude am I cleared to?`

## SID / departure-route awareness
When a SID/departure procedure is known with sufficient confidence, ORION may represent:
- ordered fixes/legs;
- heading/track constraints;
- altitude constraints;
- speed constraints where available;
- transition/exit fix.

ORION must not fabricate a SID or waypoint sequence when procedure data is unavailable or uncertain. In that case Departure may use explicit vectors/direct-to/altitude clearances based only on reliable data.

A later adapter may supply full DCS/theatre-specific procedure datasets; #65 establishes the generic procedural contracts first.

## Altimeter setting / transition logic
#65 consumes the shared Aerodrome Information layer from #64 rather than creating a new pressure store.

The engine must distinguish:
- aerodrome QNH;
- QFE when explicitly relevant/available;
- STANDARD `1013.25 hPa / 29.92 inHg` for flight-level operations.

Transition-altitude/transition-level data must be represented explicitly when known. ORION may answer `какое давление поставить?` using phase/procedure context, but must not invent a transition rule when the relevant datum is unknown.

## Rejected takeoff / abort
The procedural engine must model at least:
- rejected takeoff before liftoff;
- aircraft stopped on the runway;
- runway remaining occupied after the abort;
- eventual runway vacation;
- re-coordination with Tower/Ground for taxi after abort;
- preservation of safety priority and audit history.

An abort must never automatically jump back to a normal pre-takeoff state without physical runway-vacated evidence.

## Traffic/conflict awareness
Within the reliable traffic/runway data available to ORION, Tower must withhold incompatible lineup/takeoff clearances for:
- landing traffic using the runway resource;
- another departure reservation/operation;
- runway crossing;
- unknown/stale runway state that is insufficient for positive clearance.

#65 establishes generic conflict gating; sophisticated sequencing/spacing optimization may be extended later.

## Free-form / ORION-first interaction
The normal user interaction remains speech/free-form through ORION. Phraseology may be strict or conversational according to the existing Virtual ATC mode, but procedural semantics are canonical underneath.

Examples:
- `ORION, готов к вылету.`
- `Можно занимать?`
- `Почему держишь?`
- `Курс после взлета?`
- `До какой высоты?`
- `Когда переходить на Departure?`

ORION answers from the live procedural state; it must not claim a clearance that has not actually been issued.

## Audit requirements
Audit/history must capture at minimum:
- holding reason;
- lineup clearance issuance/acknowledgement/physical lineup;
- takeoff clearance issuance/acknowledgement;
- takeoff-roll commitment;
- airborne observation;
- Tower→Departure handoff;
- amendments to departure heading/altitude/route;
- rejected-takeoff/abort state changes;
- runway-vacated-after-abort and subsequent Ground handoff.

## Initial implementation boundary
Included in #65:
- generic departure state machine;
- Tower departure runtime and runway gating;
- confirmed-airborne handoff to Departure;
- initial Departure clearance model/runtime;
- generic SID/departure-route contracts;
- transition-pressure decision contract using #64 aerodrome pressure information;
- rejected-takeoff flow;
- free-form departure query hooks;
- deterministic regression tests and audit events.

Explicitly deferred:
- full Approach/Arrival engine (#66);
- exhaustive SID database for every DCS theatre;
- advanced multi-aircraft departure sequencing optimization;
- visual departure-map/UI rendering;
- deep aircraft-specific performance limits beyond generic procedure constraints.
