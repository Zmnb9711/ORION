from datetime import datetime, timezone

from orion.models import AircraftState, Attitude, Position, TelemetryEnvelope, VelocityVector


def test_v02_payload_remains_valid() -> None:
    payload = TelemetryEnvelope.model_validate(
        {
            "protocol_version": "0.2",
            "source": "dcs-export",
            "state": {
                "aircraft_type": "FA-18C_hornet",
                "position": {"latitude": 36.0, "longitude": 30.0, "altitude_m": 1000.0},
                "heading_deg": 90.0,
                "true_airspeed_mps": 150.0,
                "vertical_speed_mps": 5.0,
            },
        }
    )
    assert payload.sequence is None
    assert payload.state.attitude is None
    assert payload.state.airframe is None
    assert payload.state.fuel is None


def test_v03_domains_accept_partial_capability_data() -> None:
    captured = datetime(2026, 8, 13, tzinfo=timezone.utc)
    payload = TelemetryEnvelope(
        protocol_version="0.3",
        source="dcs-export",
        sequence=42,
        captured_at=captured,
        model_time_s=123.5,
        state=AircraftState(
            aircraft_type="FA-18C_hornet",
            position=Position(latitude=36.0, longitude=30.0, altitude_m=1000.0, altitude_agl_m=500.0),
            heading_deg=90.0,
            true_airspeed_mps=150.0,
            vertical_speed_mps=5.0,
            attitude=Attitude(pitch_deg=4.5, bank_deg=-12.0, yaw_deg=90.0),
            velocity_vector=VelocityVector(x_mps=100.0, y_mps=5.0, z_mps=110.0),
            fuel={"internal_raw": 0.72, "external_raw": 0.0, "semantics": "module_dependent"},
            capabilities={"airframe": "available", "fuel": "available", "ew": "restricted"},
        ),
    )
    assert payload.sequence == 42
    assert payload.state.position.altitude_agl_m == 500.0
    assert payload.state.attitude is not None
    assert payload.state.attitude.bank_deg == -12.0
    assert payload.state.fuel == {"internal_raw": 0.72, "external_raw": 0.0, "semantics": "module_dependent"}
    assert payload.state.capabilities == {"airframe": "available", "fuel": "available", "ew": "restricted"}
