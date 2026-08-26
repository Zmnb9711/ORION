# IA-2 World Model Query Facade

Status: **IMPLEMENTED — CODE-VALIDATED 2026-08-26**.

Next approved stage: **IA-3 Tool Gateway**.

## Decision

IA-2 adds a provider-neutral, read-only projection over existing authoritative
Core owners. It is not a database, cache, event history, tool API, provider
adapter, or action path.

```text
DCS Export / Mission Bridge / aircraft adapters / domain stores
                              |
                    authoritative owners
                              |
                  WorldModelFacade (read only)
                              |
                    future IA-3 Tool Gateway
                              |
                    future Planner/provider
```

The facade returns immutable typed facts with `known`, `unknown`, `unavailable`,
`stale`, or `restricted` status; source; authority (`authoritative`, `observed`,
or `derived`); timestamp; age; generation; units; and a typed reason. Confidence
is permitted only for uncertain observations. It performs no network call and
has no Yandex, Qwen, OpenAI, SRS, or tool-schema dependency.

## AS-IS ownership audit

| Area | Current owner | IA-2 disposition | Reason |
|---|---|---|---|
| Live ownship telemetry | `LiveTelemetryStore` | KEEP AS-IS | Canonical current payload, receive time and generation. |
| Fresh ownship projection | `FlightContext` | KEEP / EXTEND | Existing five-second freshness behavior remains; World Model reads the underlying owner. |
| Mission truth | `MissionStore` / `MissionSnapshot` | KEEP AS-IS | Canonical unit/world snapshot; never relabelled as detected contacts. |
| Live Mission Bridge session/indexes | `MissionBridgeTelemetryStore`, coalition/navigation indexes | KEEP AS-IS | Owns bridge connectivity, sequence and mission-supplied radio/navigation assets. |
| Legacy bridge state | `mission_bridge_state.py` | DEPRECATE LATER | Still used by coalition-control API; do not merge during IA-2. |
| F/A-18C cockpit observations | adapter + mapping registry | ADAPT | Expose only normalized, validated subset; never raw clickable arguments. |
| ATC/runway/surface/clearance state | ATC domain stores/services | KEEP AS-IS | Domain authority stays with its state machine. |
| JTAC/AAR/Mission Control state | respective domain services/stores | KEEP AS-IS | No responsibility migration in IA-2. |
| Aircraft procedures/capabilities | aircraft knowledge registry | KEEP AS-IS | Knowledge is not live world state. |
| Runtime modules | runtime module registry | KEEP AS-IS | Not a world fact owner. |
| Qwen realtime tool prototype | `realtime_tools.py` | DEPRECATE LATER | Provider-specific prototype; not an IA-2 dependency or IA-3 design. |
| General observed-contact owner | none | GAP | Mission truth cannot prove sensor/AWACS detection. |
| General location/terrain resolver | none | GAP | Coordinate formatting is derivable; terrain, airfield lookup and route remain unavailable. |
| Radio context/selection/PTT owner | future Stage 6B | GAP | Explicitly outside IA-2. |

`MOVE RESPONSIBILITY` is intentionally empty: the audit found no safe ownership
move needed to prove the facade.

## Implemented query surface

- `ownship()` — identity, position, heading, attitude, TAS, Core-derived
  horizontal groundspeed, vertical speed, AGL and normalized fuel fraction.
- `ownship_navigation()` — position/heading/AGL and deterministic coordinate
  formatting; terrain elevation, nearest airfield and route are explicit gaps.
- `aircraft_systems()` — validated normalized F/A-18C TACAN/COMM/display/master
  mode subset; unsupported, missing or unvalidated data fails closed.
- `mission_identity()` — MissionStore identity and Mission Bridge session are
  separate facts with separate provenance and versions.
- `mission_units()` — filtered, bounded mission-truth snapshot. The source
  `detected` flag is intentionally not exposed as observational authority.
- `observed_contacts()` — restricted until a trusted sensor/contact owner and
  visibility policy exist.
- `geometry_to_unit()` — Core-derived great-circle horizontal range, true
  bearing and signed vertical separation from authoritative positions. Closure
  remains unavailable until both velocity vectors share reliable semantics and
  coordinates.

The facade deep-copies only the bounded source snapshot it reads and never
mutates owners. Current targets are local/simple queries well below 100 ms and
small geometry/snapshots below 300 ms; no network latency exists in this layer.

## Authority and freshness rules

- DCS ownship facts and MissionStore truth are authoritative for what those
  owners represent.
- Normalized cockpit state is observed, because it is decoded from validated
  module mappings rather than general simulator truth.
- Formatting and geometry are derived deterministically in Core.
- Live telemetry becomes stale after 5 seconds; MissionStore projections after
  30 seconds. Mission Bridge retains its owner's 10-second liveness rule.
- A stale fact may retain its last value with `source_stale`; unavailable and
  restricted facts never contain a value.
- Planner/provider code may not reinterpret stale mission facts as probably
  current. Future IA-3 policy will decide which task-scoped facts may leave Core.

## DCS and Tacview coverage audit

The installed official DCS script API (`DCSWorld/Scripts/Export.lua`, inspected
2026-08-26) documents ownship export functions, `LoGetWorldObjects`,
`LoGetAltitude(x, z)`, export-permission checks, target position/velocity and
`LoGetMechInfo().controlsurfaces`. The latter exposes independent left/right
`elevator`, left/right `eleron` (the DCS API spelling), and left/right `rudder`
values normalized approximately to `[-1, 1]`.

ORION already calls `LoGetMechInfo`, but its current normalized `airframe` output
drops `controlsurfaces`. It exports ownship AGL, not the general terrain-height
query needed for arbitrary terrain clearance/LOS. These are coverage findings,
not justification for a broad exporter change in IA-2.

Tacview's current DCS controls/terrain work is reference evidence only. Runtime
architecture remains:

Reference sources checked 2026-08-26: the installed official DCS
`DCSWorld/Scripts/Export.lua`, the official
[Tacview 2 product page](https://www.tacview.net/product/tacview2/en/) and
[Tacview release history](https://www.tacview.net/download/latest/en/).

```text
DCS -> ORION
DCS -> Tacview
never Tacview -> ORION
```

Range, bearing and vertical separation belong in Core when authoritative
positions are available. Closure also belongs in Core, but only after reliable,
coordinate-aligned velocity is exposed. Tacview is not a state source or runtime
dependency.

## Ranked gaps

### P0 — before the first Qwen vertical slice

- Preserve the observed-contact restriction; IA-3 must not expose MissionStore
  units through an AWACS/contact query as if detected.
- Add explicit IA-3 task/query allow-lists and bounded serialization; never a
  whole-world dump.
- Resolve ownership/generation policy before exposing any source whose store has
  no native generation counter.

### P1 — early ATC/AWACS/JTAC/AAR

- trusted observed-contact/sensor owner and multiplayer/export restriction policy;
- airfield/runway/weather/traffic/occupancy sources;
- general terrain elevation and LOS inputs from DCS/Core-owned data;
- consistent mission-unit velocity semantics for closure;
- mission event/weapon history, JTAC designation state, and live tanker state.

### P2 — aircraft depth

- export and module-validate independent control surfaces;
- normalize engine, fuel, payload, warnings, navigation, radios, EW and sensors;
- expand validated cockpit mappings by aircraft/module without inventing meaning.

### P3 — later/debrief/analytics

- bounded history, high-volume ballistic/event analytics, terrain cache and
  debrief projections. These do not belong in the live query facade by default.

## Validation classification

| Area | Status |
|---|---|
| Contract validation, serialization, immutability | CODE-VALIDATED |
| Fresh/stale/disconnected and generation behavior | CODE-VALIDATED |
| Mission-truth/observed separation | CODE-VALIDATED |
| Ownship/mission projections and geometry math | CODE-VALIDATED |
| Current ORION DCS/SRS telemetry path | FIELD-VALIDATED by prior Stage 6A/IA-1 evidence, not re-flown for IA-2 |
| General terrain, observed contacts, closure, control surfaces | FIELD VALIDATION REQUIRED only after those sources are implemented |

No new flight is required for IA-2. A flight now could not validate fields the
current exporter does not expose. IA-3 may consume these contracts; it must not
add actions or provider schema to the World Model itself.
