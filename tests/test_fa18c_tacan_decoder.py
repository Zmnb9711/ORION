from orion.fa18c_cockpit_adapter import normalize_hornet_cockpit_state
from orion.fa18c_mapping_registry import HornetArgumentMapping
from orion.fa18c_tacan_decoder import decode_tacan
from orion.fa18c_value_profiles import ControlValueProfile, HornetValueProfileSet


ARGUMENTS = {"tacan_power": 410, "tacan_channel_tens": 411, "tacan_channel_ones": 412, "tacan_xy": 413, "comm1_selector": 133, "comm2_selector": 134}


def mapping() -> HornetArgumentMapping:
    return HornetArgumentMapping(arguments=ARGUMENTS)


def profiles() -> HornetValueProfileSet:
    return HornetValueProfileSet(
        mapping_version="fa18c-clickable-calibrated-v1",
        controls={
            "tacan_power": ControlValueProfile(control="tacan_power", argument_id=410, detents=[0.0, 0.5]),
            "tacan_channel_tens": ControlValueProfile(control="tacan_channel_tens", argument_id=411, detents=[i / 9 for i in range(10)]),
            "tacan_channel_ones": ControlValueProfile(control="tacan_channel_ones", argument_id=412, detents=[i / 9 for i in range(10)]),
            "tacan_xy": ControlValueProfile(control="tacan_xy", argument_id=413, detents=[0.0, 1.0]),
        },
    )


def test_decoder_requires_matching_validated_mapping() -> None:
    result = decode_tacan({"tacan_power": 0.5}, mapping_version="fa18c-clickable-v0", mapping_validated=True, mapping=mapping(), profiles=profiles())
    assert (result.enabled, result.channel, result.band) == (None, None, None)


def test_decoder_requires_calibrated_value_profile() -> None:
    result = decode_tacan({"tacan_power": 0.5}, mapping_version="fa18c-clickable-calibrated-v1", mapping_validated=True, mapping=mapping(), profiles=None)
    assert result.enabled is None


def test_decoder_decodes_profiled_tacan_controls() -> None:
    result = decode_tacan(
        {"tacan_power": 0.5, "tacan_channel_tens": 3 / 9, "tacan_channel_ones": 1 / 9, "tacan_xy": 0.0},
        mapping_version="fa18c-clickable-calibrated-v1", mapping_validated=True, mapping=mapping(), profiles=profiles(),
    )
    assert result.enabled is True
    assert result.channel == 31
    assert result.band == "X"


def test_decoder_rejects_values_outside_profile_tolerance() -> None:
    result = decode_tacan(
        {"tacan_power": 0.5, "tacan_channel_tens": 0.37, "tacan_channel_ones": 1 / 9, "tacan_xy": 0.0},
        mapping_version="fa18c-clickable-calibrated-v1", mapping_validated=True, mapping=mapping(), profiles=profiles(),
    )
    assert result.channel is None


def test_adapter_uses_calibrated_profile() -> None:
    state = normalize_hornet_cockpit_state(
        {"aircraft_id": "fa-18c", "mapping_version": "fa18c-clickable-calibrated-v1", "mapping_validated": True,
         "raw_arguments": {"tacan_power": 0.5, "tacan_channel_tens": 3 / 9, "tacan_channel_ones": 1 / 9, "tacan_xy": 1.0}},
        mapping=mapping(), profiles=profiles(),
    )
    assert state is not None
    assert state.tacan_enabled is True
    assert state.tacan_channel == 31
    assert state.tacan_band == "Y"
