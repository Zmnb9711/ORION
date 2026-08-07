from pathlib import Path

from orion.fa18c_live_validation import HornetLiveValidator
from orion.fa18c_mapping_registry import HornetMappingRegistry, REQUIRED_KEYS
from orion.fa18c_value_profiles import ControlValueProfile, HornetValueProfileRegistry, HornetValueProfileSet
from orion.models import AircraftState, Position, TelemetryEnvelope


def _registries(tmp_path: Path) -> tuple[HornetMappingRegistry, HornetValueProfileRegistry]:
    mapping_registry = HornetMappingRegistry(path=tmp_path / "mapping.json")
    mapping = mapping_registry.save({key: index + 100 for index, key in enumerate(REQUIRED_KEYS)})
    profile_registry = HornetValueProfileRegistry(path=tmp_path / "profiles.json")
    controls = {
        "tacan_power": ControlValueProfile(control="tacan_power", argument_id=100, detents=[1.0], semantic_values=[True]),
        "tacan_channel_tens": ControlValueProfile(control="tacan_channel_tens", argument_id=101, detents=[0.3], semantic_values=[3]),
        "tacan_channel_ones": ControlValueProfile(control="tacan_channel_ones", argument_id=102, detents=[0.1], semantic_values=[1]),
        "tacan_xy": ControlValueProfile(control="tacan_xy", argument_id=103, detents=[0.0], semantic_values=["X"]),
        "comm1_selector": ControlValueProfile(control="comm1_selector", argument_id=104, detents=[0.2], semantic_values=[4]),
        "comm2_selector": ControlValueProfile(control="comm2_selector", argument_id=105, detents=[0.4], semantic_values=[6]),
    }
    profile_registry.save(HornetValueProfileSet(mapping_version=mapping.version, controls=controls))
    return mapping_registry, profile_registry


def _payload() -> TelemetryEnvelope:
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
                    "comm1_selector": 0.2,
                    "comm2_selector": 0.4,
                },
            },
        )
    )


def test_live_validator_requires_three_consecutive_semantic_samples(tmp_path: Path) -> None:
    mapping_registry, profile_registry = _registries(tmp_path)
    validator = HornetLiveValidator(required_samples=3, mapping_registry=mapping_registry, profile_registry=profile_registry)

    assert validator.observe(_payload()).validated is False
    assert validator.observe(_payload()).validated is False
    final = validator.observe(_payload())

    assert final.validated is True
    assert final.consecutive_valid_samples == 3
    assert final.tacan_valid is True
    assert final.comm1_valid is True
    assert final.comm2_valid is True


def test_invalid_semantic_sample_resets_validation_streak(tmp_path: Path) -> None:
    mapping_registry, profile_registry = _registries(tmp_path)
    validator = HornetLiveValidator(required_samples=3, mapping_registry=mapping_registry, profile_registry=profile_registry)
    validator.observe(_payload())
    validator.observe(_payload())

    broken = _payload()
    assert broken.state.cockpit_state is not None
    broken.state.cockpit_state["raw_arguments"]["comm2_selector"] = 0.9
    result = validator.observe(broken)

    assert result.validated is False
    assert result.consecutive_valid_samples == 0
    assert result.comm2_valid is False
