# PR #63 — Airport ATC Orchestration

Status: implementation scope for the next fixed-airfield ATC slice after PR #62.

## Scope

This PR connects the runway procedure state machines merged in #62 to inter-controller authority orchestration.

Included:
- Tower -> Departure transfer after confirmed AIRBORNE
- Tower -> Ground transition after confirmed RUNWAY_VACATED
- event-gated handoff semantics using Virtual ATC Core
- integration of airport procedural state with the application-level Virtual ATC service/runtime
- audit-visible controller transitions
- regression tests for premature/duplicate/invalid transitions

Explicitly excluded from this PR:
- full Departure procedural engine
- full Approach/Arrival procedural engine
- visual pattern / overhead / PAR implementations
- DCS-specific airport phraseology expansion

## Required invariants

1. AIRBORNE is the physical gate for Tower -> Departure traffic authority transfer.
2. RUNWAY_VACATED is the physical gate for return to Ground surface workflow.
3. Frequency changes or pilot contact alone never transfer authority.
4. Handoffs are idempotent at the application boundary; duplicate physical events cannot create duplicate ownership transitions.
5. A failed or degraded simulator sync does not erase the procedural state or audit trail.
6. Tower LANDING_AREA and Ground SURFACE_MOVEMENT remain distinct authority scopes.
7. Departure receives only the scope required for post-takeoff traffic control.
8. The same ATC session identity survives all controller transitions.
9. Every handoff records source, destination, gate event and reason.
10. Invalid transitions fail closed and never silently synthesize authority.

## Initial implementation order

1. Introduce airport orchestration facade over `AirportTowerController` and `AtcIntegratedRuntime`/application service.
2. Add AIRBORNE-gated Tower -> Departure handoff.
3. Add RUNWAY_VACATED-gated Tower -> Ground continuation.
4. Add status snapshot fields for current airport controller/procedural phase where appropriate.
5. Add integration tests covering normal, premature, duplicate and degraded-mode transitions.

## Exit criteria

PR #63 is complete when the airport runway state machines can drive safe, auditable controller transitions without embedding Departure or Approach procedural logic into this PR.
