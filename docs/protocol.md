# ORION bridge protocol

ORION receives flight telemetry from the DCS Export environment over UDP and keeps mission-control traffic separated from the flight bridge.

## Telemetry envelope

The generic flight envelope contains `protocol_version`, `source`, and `state`. Version `0.2` adds the optional `state.cockpit_state` field while remaining compatible with aircraft that only provide generic flight data.

Example shape:

```json
{
  "protocol_version": "0.2",
  "source": "dcs-export",
  "state": {
    "aircraft_type": "FA-18C_hornet",
    "position": {
      "latitude": 41.0,
      "longitude": 41.0,
      "altitude_m": 1000.0
    },
    "heading_deg": 90.0,
    "true_airspeed_mps": 200.0,
    "vertical_speed_mps": 0.0,
    "cockpit_state": {
      "aircraft_id": "fa-18c",
      "mapping_version": "fa18c-clickable-v0",
      "mapping_validated": false,
      "raw_arguments": {
        "comm1_selector": 0.2,
        "tacan_power": 0.5
      }
    }
  }
}
```

## Cockpit-state trust boundary

`raw_arguments` are simulator observations only. A raw clickable value must not be described to the pilot as a semantic state (for example, "TACAN channel 31") until the aircraft-specific argument mapping and decoding rule have been verified against a live DCS module. `mapping_validated=false` explicitly blocks that assumption.

Aircraft-specific adapters normalize the telemetry for Voice Core while preserving mission/requested target values separately from observed cockpit state. Missing values remain unknown rather than being inferred.

## Command channel

The current Export prototype listens for a small allow-listed command set (`ping`, `request_status`, `show_message`) on the command UDP socket. Unsupported commands are rejected and logged.
