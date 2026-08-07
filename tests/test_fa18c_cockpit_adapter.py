from orion.fa18c_cockpit_adapter import cockpit_state_for_voice, normalize_hornet_cockpit_state
from orion.fa18c_live_state import advise_hornet_live_state
from orion.models import TelemetryEnvelope


def test_adapter_preserves_raw_unvalidated_dcs_observations() -> None:
    state = normalize_hornet_cockpit_state(
        {
            "aircraft_id": "fa-18c",
            "mapping_version": "fa18c-clickable-v0",
            "mapping_validated": False,
            "raw_arguments": {
                "tacan_power": 0.5,
                "comm1_selector": 0.2,
                "left_ddi_brightness": 0.75,
            },
        }
    )
    assert state is not None
    assert state.mapping_validated is False
    assert state.raw_arguments["tacan_power"] == 0.5
    assert state.left_ddi_brightness_raw == 0.75
    assert state.tacan_enabled is None
    assert state.tacan_channel is None


def test_adapter_preserves_normalized_and_mission_target_fields() -> None:
    state = cockpit_state_for_voice(
        {
            "aircraft_id": "fa-18c",
            "tacan_enabled": False,
            "tacan_channel": 1,
            "tacan_band": "X",
            "mission_tacan_channel": 31,
            "mission_tacan_band": "X",
            "comm1_preset": 2,
            "requested_comm1_preset": 5,
        }
    )
    assert state is not None
    assert state["tacan_enabled"] is False
    assert state["mission_tacan_channel"] == 31
    assert state["requested_comm1_preset"] == 5


def test_live_advisor_does_not_invent_semantics_from_unvalidated_raw_arguments() -> None:
    advice = advise_hornet_live_state(
        "Как настроить TACAN?",
        {
            "cockpit_state": {
                "aircraft_id": "fa-18c",
                "mapping_version": "fa18c-clickable-v0",
                "mapping_validated": False,
                "raw_arguments": {"tacan_power": 1.0, "tacan_channel_tens": 0.3},
            }
        },
    )
    assert advice is not None
    assert advice.observed["enabled"] is None
    assert advice.observed["channel"] is None
    assert "карта аргументов ещё не подтверждена" in advice.spoken_text


def test_telemetry_envelope_keeps_cockpit_state() -> None:
    envelope = TelemetryEnvelope.model_validate(
        {
            "protocol_version": "0.2",
            "source": "dcs-export",
            "state": {
                "aircraft_type": "FA-18C_hornet",
                "position": {"latitude": 41.0, "longitude": 41.0, "altitude_m": 1000.0},
                "heading_deg": 90.0,
                "true_airspeed_mps": 200.0,
                "vertical_speed_mps": 0.0,
                "cockpit_state": {
                    "aircraft_id": "fa-18c",
                    "mapping_validated": False,
                    "raw_arguments": {"comm1_selector": 0.2},
                },
            },
        }
    )
    assert envelope.protocol_version == "0.2"
    assert envelope.state.cockpit_state is not None
    assert envelope.state.cockpit_state["aircraft_id"] == "fa-18c"
