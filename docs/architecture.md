# ORION architecture

## Build 001 scope

The initial build establishes a local integration boundary between DCS World and ORION Core.

```text
DCS World
  -> Saved Games/DCS/Scripts/Export.lua
  -> UDP JSON telemetry on 127.0.0.1:45100
  -> ORION Core telemetry bridge
  -> validated aircraft state
  -> REST API on 127.0.0.1:8000
```

## Components

### DCS exporter

`dcs-export/Export.lua` reads the player's own-aircraft data through the DCS export API and emits a small versioned JSON envelope. It chains any previously installed `LuaExportAfterNextFrame` callback rather than replacing it.

### Telemetry bridge

`orion/udp_bridge.py` receives local UDP datagrams, decodes JSON and validates every message with Pydantic before accepting it.

### ORION Core API

`orion/app.py` exposes health and telemetry endpoints. The in-memory latest-state store is intentionally minimal for Build 001 and will later be replaced by a mission-state service.

## Security boundary

Build 001 binds both telemetry and API services to localhost. Network exposure, authentication and remote-control commands are deliberately outside this milestone.

## Next milestones

1. Configuration and structured logging.
2. Mission-state store and event history.
3. DCS command channel with an explicit allowlist.
4. Speech-to-text and text-to-speech adapters.
5. Russian/English Virtual ATC dialogue engine.
6. AWACS, tanker and target-designation workflows.
