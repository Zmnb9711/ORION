# ORION Local Protocol v0.1

ORION Build 001 uses two localhost UDP channels and one local REST API.

## Network boundaries

- Telemetry: DCS Export -> ORION Core on `127.0.0.1:45100/udp`
- Commands: ORION Core -> DCS Export on `127.0.0.1:45101/udp`
- REST API: ORION Core on `127.0.0.1:8000`

All default endpoints are bound to loopback. Remote exposure is intentionally out of scope for Build 001.

## Telemetry envelope

```json
{
  "protocol_version": "0.1",
  "source": "dcs-export",
  "state": {
    "aircraft_type": "FA-18C_hornet",
    "callsign": "Enfield 1-1",
    "position": {
      "latitude": 41.6103,
      "longitude": 41.5997,
      "altitude_m": 2500.0
    },
    "heading_deg": 90.0,
    "true_airspeed_mps": 210.0,
    "vertical_speed_mps": 0.0,
    "fuel_fraction": 0.72
  }
}
```

The ORION Core validates latitude, longitude, heading, speed and optional fuel fraction before accepting a record.

## Command envelope

```json
{
  "command": "show_message",
  "arguments": {
    "text": "ORION connected"
  }
}
```

Build 001 allows only:

- `ping`
- `request_status`
- `show_message`

Any other command is rejected by ORION Core before transmission to DCS.

## REST endpoints

- `GET /health`
- `POST /v1/telemetry`
- `GET /v1/telemetry/latest`
- `POST /v1/commands`

## Versioning

Breaking payload changes require a new `protocol_version`. Additive optional fields may remain within version `0.1` while Build 001 is under development.
