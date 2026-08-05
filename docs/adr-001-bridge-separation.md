# ADR-001: Separate Flight Bridge and Mission Bridge

Status: accepted

## Context

DCS exposes own-aircraft export data and mission scripting through different Lua environments with different responsibilities and permissions. Treating `Export.lua` as a universal bidirectional mission controller would couple unrelated concerns and overstate what the export environment can safely do.

## Decision

ORION uses two explicit integration channels:

- **Flight Bridge**: `Export.lua` integration for own-aircraft telemetry and a very small allowlist of cockpit-local commands.
- **Mission Bridge**: transport for structured mission commands and capability registration.
- **Mission Pack**: a script loaded by the mission that exposes an allowlisted DCS Mission API.

ORION Core must check the registered Mission Pack capabilities before sending a mission command. Unknown capabilities and arbitrary Lua execution are forbidden.

## Initial protocol

Mission Pack registration uses protocol version `0.2` and contains:

- mission identifier;
- Mission Pack version;
- protocol version;
- supported capability names.

Initial mission capabilities are laser, smoke, AWACS, tanker, tasking, artillery and CSAR. Only laser and smoke have Mission Pack handlers in the first implementation.

## Compatibility

Legacy `/v1/telemetry` and `/v1/commands` routes remain as hidden aliases during the transition. New clients should use `/v1/flight-bridge/*` and `/v1/mission-bridge/*`.

## Consequences

The project remains a specialised DCS assistant. This decision does not introduce a general plugin platform or support for unrelated simulators.
