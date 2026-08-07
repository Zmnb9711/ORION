from pathlib import Path

from orion.dcs_connection_diagnostics import ConnectionState, DcsConnectionReport
from orion.fa18c_live_validation import HornetLiveValidator
from orion.fa18c_mapping_registry import HornetMappingRegistry, REQUIRED_KEYS
from orion.fa18c_value_profiles import ControlValueProfile, HornetValueProfileRegistry, HornetValueProfileSet
from orion.first_run_wizard import FirstRunReport, FirstRunState
from orion.models import AircraftState, Position, TelemetryEnvelope
from orion.preflight_orchestrator import PreflightRequest, PreflightState, evaluate_preflight
from orion.telemetry_handshake import TelemetryHandshake


def _payload(cockpit: bool = False) -> TelemetryEnvelope:
    cockpit_state = None
    if cockpit:
        cockpit_state = {
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
        }
    return TelemetryEnvelope(
        state=AircraftState(
            aircraft_type="FA-18C_hornet",
            position=Position(latitude=0, longitude=0, altitude_m=0),
            heading_deg=0,
            true_airspeed_mps=0,
            cockpit_state=cockpit_state,
        )
    )


def _handshake() -> TelemetryHandshake:
    handshake = TelemetryHandshake()
    handshake.observe(_payload())
    return handshake


def _mock_ready_dependencies(monkeypatch) -> None:
    monkeypatch.setattr(
        "orion.preflight_orchestrator.evaluate_first_run",
        lambda payload: FirstRunReport(
            state=FirstRunState.WAITING_FOR_DCS,
            headline="Setup complete",
            checks=[],
            next_action="Start DCS",
        ),
    )
    monkeypatch.setattr(
        "orion.preflight_orchestrator.diagnose_dcs_connection",
        lambda **kwargs: DcsConnectionReport(
            state=ConnectionState.HEALTHY,
            connected=True,
            aircraft_type="FA-18C_hornet",
            packet_count=2,
            packet_rate_hz=10,
            age_seconds=0,
            message="healthy",
        ),
    )


def _calibrated_registries(tmp_path: Path) -> tuple[HornetMappingRegistry, HornetValueProfileRegistry]:
    mapping_registry = HornetMappingRegistry(path=tmp_path / "mapping.json")
    mapping = mapping_registry.save({key: index + 100 for index, key in enumerate(REQUIRED_KEYS)})
    profile_registry = HornetValueProfileRegistry(path=tmp_path / "profiles.json")
    profile_registry.save(
        HornetValueProfileSet(
            mapping_version=mapping.version,
            controls={
                "tacan_power": ControlValueProfile(control="tacan_power", argument_id=100, detents=[1.0], semantic_values=[True]),
                "tacan_channel_tens": ControlValueProfile(control="tacan_channel_tens", argument_id=101, detents=[0.3], semantic_values=[3]),
                "tacan_channel_ones": ControlValueProfile(control="tacan_channel_ones", argument_id=102, detents=[0.1], semantic_values=[1]),
                "tacan_xy": ControlValueProfile(control="tacan_xy", argument_id=103, detents=[0.0], semantic_values=["X"]),
                "comm1_selector": ControlValueProfile(control="comm1_selector", argument_id=104, detents=[0.2], semantic_values=[4]),
                "comm2_selector": ControlValueProfile(control="comm2_selector", argument_id=105, detents=[0.4], semantic_values=[6]),
            },
        )
    )
    return mapping_registry, profile_registry


def test_hornet_requires_calibration_when_mapping_missing(tmp_path: Path, monkeypatch) -> None:
    _mock_ready_dependencies(monkeypatch)
    mapping_registry = HornetMappingRegistry(path=tmp_path / "mapping.json")
    profile_registry = HornetValueProfileRegistry(path=tmp_path / "profiles.json")
    validator = HornetLiveValidator(mapping_registry=mapping_registry, profile_registry=profile_registry)
    report = evaluate_preflight(
        PreflightRequest(installed_components=["orion-core", "dcs-integration", "aircraft-fa18c"]),
        handshake=_handshake(),
        mapping_registry=mapping_registry,
        profile_registry=profile_registry,
        live_validator=validator,
    )
    assert report.state is PreflightState.CALIBRATION_REQUIRED
    assert report.aircraft.detected_aircraft == "FA-18C_hornet"
    assert report.next_action == "Start F/A-18C Calibration Wizard"


def test_hornet_requires_live_validation_after_complete_calibration(tmp_path: Path, monkeypatch) -> None:
    _mock_ready_dependencies(monkeypatch)
    mapping_registry, profile_registry = _calibrated_registries(tmp_path)
    validator = HornetLiveValidator(mapping_registry=mapping_registry, profile_registry=profile_registry)
    report = evaluate_preflight(
        PreflightRequest(installed_components=["orion-core", "dcs-integration", "aircraft-fa18c"]),
        handshake=_handshake(),
        mapping_registry=mapping_registry,
        profile_registry=profile_registry,
        live_validator=validator,
    )
    assert report.state is PreflightState.LIVE_VALIDATION_REQUIRED
    assert report.aircraft.mapping_complete is True
    assert report.aircraft.value_profiles_complete is True


def test_hornet_is_ready_only_after_live_tacan_comm_validation(tmp_path: Path, monkeypatch) -> None:
    _mock_ready_dependencies(monkeypatch)
    mapping_registry, profile_registry = _calibrated_registries(tmp_path)
    validator = HornetLiveValidator(mapping_registry=mapping_registry, profile_registry=profile_registry)
    for _ in range(3):
        validator.observe(_payload(cockpit=True))

    report = evaluate_preflight(
        PreflightRequest(installed_components=["orion-core", "dcs-integration", "aircraft-fa18c"]),
        handshake=_handshake(),
        mapping_registry=mapping_registry,
        profile_registry=profile_registry,
        live_validator=validator,
    )
    assert report.state is PreflightState.READY_TO_FLY
    assert report.live_validation is not None
    assert report.live_validation.validated is True
    assert report.next_action is None
