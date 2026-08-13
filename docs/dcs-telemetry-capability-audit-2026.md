# DCS Telemetry Capability Audit — 2026

## Purpose

Define what ORION should collect from current DCS before the next large F/A-18C smoke run, so captured telemetry is diagnostically useful rather than merely voluminous.

## Sources and evidence policy

This audit distinguishes three layers:

1. **DCS Export environment** — per-frame data available from `Export.lua` and cockpit devices.
2. **Mission Scripting Engine** — mission/world objects and coalition/group/unit state available inside the mission scripting environment.
3. **Aircraft-specific cockpit layer** — clickable cockpit arguments/indicators and module-specific device data. DCS-BIOS is used as a compatibility/reference implementation for what current clickable modules expose, not as ORION's required runtime dependency.

Current ORION must not assume that every locally available datum is allowed or available on every multiplayer server. Server-side export restrictions and mission design can reduce observability.

## Current ORION baseline

Current `dcs-export/Export.lua` exports only:

- aircraft type via `LoGetSelfData()`;
- latitude/longitude/altitude;
- heading;
- vector-derived true speed;
- vertical speed;
- a small F/A-18C cockpit mapping: COMM1/COMM2 selector, TACAN power/channel/X-Y, DDI/MPCD brightness;
- optional F/A-18C cockpit argument-change diagnostics over a configurable argument range.

Current normalized `AircraftState` additionally has a `fuel_fraction` field, but the current exporter does not populate it.

## Capability matrix

| Domain | Candidate source | Examples | ORION current | Priority | Notes |
|---|---|---|---|---|---|
| Identity | `LoGetSelfData()` | aircraft type/name | Yes | P0 | Proven path; preserve last-known value after DCS exit. |
| Position/orientation | `LoGetSelfData()` | lat/lon/alt, heading; pitch/bank where available | Partial | P0 | Add pitch/bank and distinguish MSL/AGL where obtainable. |
| Velocity | `LoGetVectorVelocity()` and related export data | speed vector, vertical speed | Partial | P0 | Preserve vector components as well as derived scalar speed. |
| Fuel | export engine/mechanical/cockpit data | total/internal/external fuel or normalized fraction | No | P0 | Needed for Mission Control, AAR, bingo/joker logic and debrief. |
| Engines | export engine data / aircraft devices | RPM, temperatures, engine state, fuel flow where exposed | No | P1 | Normalize by engine index; module support varies. |
| Airframe/mechanics | mechanical export / cockpit | gear, flaps, hook, speedbrake, wing fold, refuel probe | No | P0 for F/A-18C | Directly useful to ATC/carrier/AAR and phase-of-flight reasoning. |
| Navigation | export route + cockpit | waypoint/steerpoint, route, TACAN/ILS state | TACAN raw only | P0 | Needed for ATC, tanker, navigation and mission guidance. |
| Radios/comms | cockpit/device data | tuned frequencies, presets, selected radios, volume/squelch where exposed | selectors only | P0 | Critical for Virtual ATC/AWACS/tanker workflows. |
| Weapons/payload | payload export + cockpit | stations, selected weapon, quantities, gun ammo | No | P1 | Needed for Mission Control, attack recommendations and debrief. |
| EW/RWR | RWR/TWS export + cockpit | emitters, bearing, threat state, lock/missile cues | No | P1 | High tactical value; must respect MP restrictions. |
| Sensors | aircraft-specific devices/cockpit | radar modes, sensor selection, targeting state | No | P1/P2 | Highly module-specific; do not block generic schema on Hornet-specific detail. |
| Cautions/advisories | cockpit indicators/strings | master caution, fire, warning lamps, advisories | No | P0/P1 | High value for AI copilot and diagnostics. |
| Displays | aircraft-specific outputs | UFC/DDI/MPCD strings/symbol state where exposed | No | P1 | DCS-BIOS proves that many modules expose integer/string outputs; availability is module-specific. |
| Damage/health | export/mission/cockpit | damage, life, failed systems where available | No | P1 | Useful for emergency ATC and debrief. |
| Mission world | Mission Scripting Engine | coalition groups, units, airbases, positions, velocities, fuel/ammo/sensors where APIs expose them | Separate mission layer | P0 for Mission Control | Keep separate from player telemetry transport; merge in Core mission context. |
| Events | Mission Scripting Engine | birth, takeoff, landing, shot, hit, dead, ejection, refuel-related events where available | Partial elsewhere | P0/P1 | Prefer event stream over inferring every transition from sampled state. |

## F/A-18C specific audit target

The Hornet should be the first deep adapter. Before the next user flight, ORION should attempt to capture a structured subset that is immediately useful and can be validated in one session.

### P0 F/A-18C fields

**Flight/airframe**

- aircraft type;
- lat/lon/altitude;
- heading, pitch, bank;
- velocity vector, TAS/ground-relevant speed where available, vertical speed;
- gear state;
- flap state;
- speedbrake state;
- arresting hook state;
- wing-fold state;
- launch-bar state if exposed;
- refuelling probe state.

**Fuel/engines**

- normalized total fuel fraction at minimum;
- internal/external fuel quantities where reliably exposed;
- left/right engine RPM/state and fuel flow if available.

**Navigation/comms**

- COMM1/COMM2 selected/tuned state or frequency where exposed;
- TACAN power, channel and X/Y;
- ILS state/frequency/channel where exposed;
- current waypoint/steerpoint and route information where available.

**Warnings/operational state**

- master caution / fire warning if exposed;
- WOW/airborne state if directly obtainable or robustly derivable;
- canopy state;
- parking brake/wheel brake state where exposed.

**Weapons/tactical**

- payload/station inventory;
- selected weapon/station where exposed;
- gun ammunition;
- RWR emitter/threat summary where permitted.

### P1 F/A-18C cockpit coverage

Use a named, versioned Hornet mapping instead of shipping only opaque argument IDs. Candidate groups:

- UFC/radios;
- left/right DDI and MPCD power/brightness plus selected pages where obtainable;
- HUD indicators/status;
- master arm / A-A / A-G modes;
- ECM/RWR controls and warning indicators;
- radar/sensor controls;
- INS/navigation controls;
- lighting/electrical/hydraulic/caution panels;
- fuel panel and bingo setting;
- launch-bar/hook/wing-fold controls;
- refuelling probe controls.

DCS-BIOS currently supports F/A-18C and its recent releases continue to receive Hornet-specific fixes/additions, including HUD/launch-bar/laser-status related outputs. This is useful evidence that a substantially richer clickable-cockpit schema is practical, though ORION should own its own normalized schema and validation.

## Proposed ORION telemetry schema v0.3

Do not flatten everything into `AircraftState`. Keep stable generic domains and allow aircraft-specific detail.

```text
TelemetryEnvelope
  protocol_version
  source
  sequence
  captured_at
  state
    identity
    kinematics
    airframe
    propulsion
    fuel
    navigation
    radios
    payload
    warnings
    ew
    sensors
    cockpit
      normalized
      aircraft_specific
```

### Design rules

- Generic fields must have explicit units.
- Unknown/unavailable data must be `null`, not fabricated defaults.
- Aircraft-specific cockpit fields live under a versioned adapter namespace.
- Preserve raw source values when normalization is uncertain.
- Include `sequence` and capture timestamp for packet-loss/rate analysis.
- Split high-rate flight state from lower-rate heavy cockpit/world data where beneficial.
- Do not add mission-world enumeration to the high-rate player UDP packet; keep Mission Context as a separate Core feed/service.
- Diagnostics should retain up to 5,000 validated envelopes plus a bounded sample of raw source payloads when parsing bugs are under investigation.

## Recommended sampling strategy

Not every datum needs frame-rate export.

- Kinematics: 20–50 Hz target, configurable.
- Critical airframe/engine/fuel state: 10–20 Hz or change-driven where safe.
- Cockpit controls/indicators: change-driven plus periodic full snapshot.
- Radios/navigation/payload: change-driven plus 1–2 Hz reconciliation snapshot.
- Mission-world objects: separate lower-rate/event-driven service; frequency depends on mission scale.

This reduces unnecessary JSON/UDP load while preserving enough temporal resolution for AI assistance and debrief.

## Multiplayer/security boundary

ORION must treat multiplayer observability as capability-dependent:

- server export settings may restrict information;
- mission scripting may expose only mission-authorized context;
- data unavailable to the player should not be inferred or bypassed through unsupported mechanisms;
- diagnostics must record capability availability so Core can distinguish `unavailable/restricted` from `sensor says no contacts`.

## Immediate implementation tranche before next F/A-18C smoke

1. Bump telemetry protocol to a backward-compatible v0.3 model in Core while accepting v0.2 during transition.
2. Add sequence/captured timestamp and preserve velocity vector/orientation.
3. Populate fuel fraction from a validated DCS source.
4. Add Hornet airframe state: gear, flaps, hook, speedbrake, wing fold, refuelling probe; launch bar if confirmed.
5. Expand comm/nav state beyond raw selectors where reliable values are exposed.
6. Add payload summary and RWR summary only if the relevant export calls are confirmed stable in the user's current DCS build.
7. Keep the 5,000-packet telemetry recorder and include schema/version metadata in the smoke ZIP.
8. Add a capability snapshot to diagnostics showing each domain as `available`, `restricted`, `unsupported`, or `not_yet_mapped`.
9. Run CI/Windows build.
10. Only then ask for the next large F/A-18C session.

## Validation plan for the next user flight

One flight should deliberately exercise observable transitions:

1. cold/dark or known start state;
2. engines start;
3. radios/TACAN setup;
4. gear/flaps/speedbrake/wing-fold/hook/probe transitions as safe and appropriate;
5. taxi/takeoff/climb/turn/descent;
6. fuel change over time;
7. waypoint/nav changes;
8. payload/weapon selection without requiring weapons employment;
9. RWR contact if naturally available in the mission;
10. close DCS, then save diagnostics.

The resulting `telemetry-history.jsonl` should be sufficient to verify field semantics, rates, nullability, transition timing and post-session retention.
