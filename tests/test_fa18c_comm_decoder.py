from orion.fa18c_cockpit_adapter import normalize_hornet_cockpit_state
from orion.fa18c_comm_decoder import decode_comm_presets
from orion.fa18c_mapping_registry import HornetArgumentMapping
from orion.fa18c_value_profiles import ControlValueProfile, HornetValueProfileSet


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


def profiles() -> HornetValueProfileSet:
    # Deliberately descending/nonlinear raw values: semantic decoding must use
    # explicit labels rather than sorted raw-value position.
    return HornetValueProfileSet(
        mapping_version="fa18c-clickable-calibrated-v1",
        controls={
            "comm1_selector": ControlValueProfile(
                control="comm1_selector",
                argument_id=133,
                detents=[0.95, 0.61, 0.22],
                semantic_values=[1, 2, 3],
                tolerance=0.04,
            ),
            "comm2_selector": ControlValueProfile(
                control="comm2_selector",
                argument_id=134,
                detents=[0.10, 0.42, 0.88],
                semantic_values=[1, 2, 3],
                tolerance=0.04,
            ),
        },
    )


def test_comm_decoder_requires_validated_matching_mapping() -> None:
    result = decode_comm_presets(
        {"comm1_selector": 0.61, "comm2_selector": 0.42},
        mapping_version="wrong-version",
        mapping_validated=True,
        mapping=mapping(),
        profiles=profiles(),
    )
    assert result.comm1_preset is None
    assert result.comm2_preset is None


def test_comm_decoder_uses_explicit_semantic_labels() -> None:
    result = decode_comm_presets(
        {"comm1_selector": 0.61, "comm2_selector": 0.88},
        mapping_version="fa18c-clickable-calibrated-v1",
        mapping_validated=True,
        mapping=mapping(),
        profiles=profiles(),
    )
    assert result.comm1_preset == 2
    assert result.comm2_preset == 3


def test_comm_decoder_rejects_value_between_calibrated_detents() -> None:
    result = decode_comm_presets(
        {"comm1_selector": 0.45, "comm2_selector": 0.42},
        mapping_version="fa18c-clickable-calibrated-v1",
        mapping_validated=True,
        mapping=mapping(),
        profiles=profiles(),
    )
    assert result.comm1_preset is None
    assert result.comm2_preset == 2


def test_adapter_populates_comm_presets_without_overriding_explicit_state() -> None:
    state = normalize_hornet_cockpit_state(
        {
            "aircraft_id": "fa-18c",
            "mapping_version": "fa18c-clickable-calibrated-v1",
            "mapping_validated": True,
            "raw_arguments": {"comm1_selector": 0.61, "comm2_selector": 0.88},
            "comm1_preset": 7,
        },
        mapping=mapping(),
        profiles=profiles(),
    )
    assert state is not None
    assert state.comm1_preset == 7
    assert state.comm2_preset == 3
