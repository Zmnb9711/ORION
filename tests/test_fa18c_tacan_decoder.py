from orion.fa18c_cockpit_adapter import normalize_hornet_cockpit_state
from orion.fa18c_mapping_registry import HornetArgumentMapping
from orion.fa18c_tacan_decoder import decode_tacan


ARGUMENTS = {
    "tacan_power": 410,
    "tacan_channel_tens": 411,
    "tacan_channel_ones": 412,
    "tacan_xy": 413,
    "comm1_selector": 133,
    "comm2_selector": 134,
}


def mapping() -> HornetArgumentMapping:
    return HornetArgumentMapping(arguments=ARGUMENTS)


def test_decoder_requires_matching_validated_mapping() -> None:
    result = decode_tacan(
        {"tacan_power": 0.5, "tacan_channel_tens": 0.3, "tacan_channel_ones": 0.1, "tacan_xy": 0.0},
        mapping_version="fa18c-clickable-v0",
        mapping_validated=True,
        mapping=mapping(),
    )
    assert result.enabled is None
    assert result.channel is None
    assert result.band is None


def test_decoder_decodes_discrete_tacan_controls() -> None:
    result = decode_tacan(
        {"tacan_power": 0.5, "tacan_channel_tens": 3 / 9, "tacan_channel_ones": 1 / 9, "tacan_xy": 0.0},
        mapping_version="fa18c-clickable-calibrated-v1",
        mapping_validated=True,
        mapping=mapping(),
    )
    assert result.enabled is True
    assert result.channel == 31
    assert result.band == "X"


def test_decoder_rejects_values_between_detents() -> None:
    result = decode_tacan(
        {"tacan_power": 0.5, "tacan_channel_tens": 0.37, "tacan_channel_ones": 1 / 9, "tacan_xy": 0.0},
        mapping_version="fa18c-clickable-calibrated-v1",
        mapping_validated=True,
        mapping=mapping(),
    )
    assert result.channel is None


def test_adapter_uses_decoder_when_semantics_are_not_exported() -> None:
    state = normalize_hornet_cockpit_state(
        {
            "aircraft_id": "fa-18c",
            "mapping_version": "fa18c-clickable-calibrated-v1",
            "mapping_validated": True,
            "raw_arguments": {
                "tacan_power": 0.5,
                "tacan_channel_tens": 3 / 9,
                "tacan_channel_ones": 1 / 9,
                "tacan_xy": 1.0,
            },
        },
        mapping=mapping(),
    )
    assert state is not None
    assert state.tacan_enabled is True
    assert state.tacan_channel == 31
    assert state.tacan_band == "Y"
