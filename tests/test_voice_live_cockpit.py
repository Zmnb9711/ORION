from orion.fa18c_mapping_registry import HornetArgumentMapping, hornet_mapping_registry
from orion.fa18c_value_profiles import ControlValueProfile, HornetValueProfileSet, hornet_value_profile_registry
from orion.live_telemetry_store import live_telemetry
from orion.models import AircraftState, Position, TelemetryEnvelope
from orion.voice_cockpit_queries import execute_cockpit_query
from orion.voice_understanding import parse_transcript


def _telemetry() -> TelemetryEnvelope:
    return TelemetryEnvelope(
        state=AircraftState(
            aircraft_type="FA-18C_hornet",
            position=Position(latitude=0, longitude=0, altitude_m=0),
            heading_deg=0,
            true_airspeed_mps=0,
            cockpit_state={
                "aircraft_id": "fa-18c",
                "mapping_version": "fa18c-clickable-calibrated-v1",
                "mapping_validated": True,
                "raw_arguments": {
                    "tacan_power": 1.0,
                    "tacan_channel_tens": 0.3,
                    "tacan_channel_ones": 0.1,
                    "tacan_xy": 0.0,
                    "comm1_selector": 0.1,
                    "comm2_selector": 0.2,
                },
            },
        )
    )


def _install_profiles() -> None:
    hornet_mapping_registry._mapping = HornetArgumentMapping(arguments={
        "tacan_power": 1,
        "tacan_channel_tens": 2,
        "tacan_channel_ones": 3,
        "tacan_xy": 4,
        "comm1_selector": 5,
        "comm2_selector": 6,
    })
    hornet_value_profile_registry._profiles = HornetValueProfileSet(
        mapping_version="fa18c-clickable-calibrated-v1",
        controls={
            "tacan_power": ControlValueProfile(control="tacan_power", argument_id=1, detents=[0.0, 1.0], semantic_values=[False, True]),
            "tacan_channel_tens": ControlValueProfile(control="tacan_channel_tens", argument_id=2, detents=[0.0, 0.3], semantic_values=[0, 3]),
            "tacan_channel_ones": ControlValueProfile(control="tacan_channel_ones", argument_id=3, detents=[0.0, 0.1], semantic_values=[0, 1]),
            "tacan_xy": ControlValueProfile(control="tacan_xy", argument_id=4, detents=[0.0, 1.0], semantic_values=["X", "Y"]),
            "comm1_selector": ControlValueProfile(control="comm1_selector", argument_id=5, detents=[0.1], semantic_values=[4]),
            "comm2_selector": ControlValueProfile(control="comm2_selector", argument_id=6, detents=[0.2], semantic_values=[7]),
        },
    )


def test_parser_routes_live_cockpit_queries() -> None:
    assert parse_transcript("Какой у меня TACAN?").commands[0].intent == "cockpit_tacan_query"
    assert parse_transcript("Какой у меня COMM1?").commands[0].intent == "cockpit_comm1_query"
    assert parse_transcript("What is my COMM2?").commands[0].intent == "cockpit_comm2_query"
    assert parse_transcript("Почему я ещё не Ready to Fly?").commands[0].intent == "cockpit_readiness_query"


def test_live_tacan_and_comm_queries_use_cockpit_telemetry() -> None:
    previous_mapping = hornet_mapping_registry._mapping
    previous_profiles = hornet_value_profile_registry._profiles
    try:
        _install_profiles()
        telemetry = _telemetry()
        live_telemetry.set(telemetry)
        tacan = execute_cockpit_query("cockpit_tacan_query", live_telemetry.get())
        comm1 = execute_cockpit_query("cockpit_comm1_query", live_telemetry.get())
        comm2 = execute_cockpit_query("cockpit_comm2_query", live_telemetry.get())
        assert tacan.completed is True
        assert "31 X" in tacan.spoken_text
        assert "preset 4" in comm1.spoken_text
        assert "preset 7" in comm2.spoken_text
    finally:
        live_telemetry.clear()
        hornet_mapping_registry._mapping = previous_mapping
        hornet_value_profile_registry._profiles = previous_profiles


def test_cockpit_query_rejects_missing_live_telemetry() -> None:
    live_telemetry.clear()
    result = execute_cockpit_query("cockpit_tacan_query", None)
    assert result.completed is False
    assert "телеметрии" in result.spoken_text
