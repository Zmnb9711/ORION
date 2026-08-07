from pathlib import Path

from orion.dcs_connection_diagnostics import ConnectionState, DcsConnectionReport
from orion.fa18c_mapping_registry import HornetMappingRegistry, REQUIRED_KEYS
from orion.first_run_wizard import FirstRunReport, FirstRunState
from orion.models import AircraftState, Position, TelemetryEnvelope
from orion.preflight_orchestrator import PreflightRequest, PreflightState, evaluate_preflight
from orion.telemetry_handshake import TelemetryHandshake


def _handshake() -> TelemetryHandshake:
    handshake = TelemetryHandshake()
    payload = TelemetryEnvelope(
        state=AircraftState(
            aircraft_type="FA-18C_hornet",
            position=Position(latitude=0, longitude=0, altitude_m=0),
            heading_deg=0,
            true_airspeed_mps=0,
        )
    )
    handshake.observe(payload)
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


def test_hornet_requires_calibration_when_mapping_missing(tmp_path: Path, monkeypatch) -> None:
    _mock_ready_dependencies(monkeypatch)
    registry = HornetMappingRegistry(path=tmp_path / "mapping.json")
    report = evaluate_preflight(
        PreflightRequest(installed_components=["orion-core", "dcs-integration", "aircraft-fa18c"]),
        handshake=_handshake(),
        mapping_registry=registry,
    )
    assert report.state is PreflightState.CALIBRATION_REQUIRED
    assert report.aircraft.detected_aircraft == "FA-18C_hornet"
    assert report.next_action == "Start F/A-18C Calibration Wizard"


def test_hornet_is_ready_with_validated_complete_mapping(tmp_path: Path, monkeypatch) -> None:
    _mock_ready_dependencies(monkeypatch)
    registry = HornetMappingRegistry(path=tmp_path / "mapping.json")
    registry.save({key: index + 100 for index, key in enumerate(REQUIRED_KEYS)})
    report = evaluate_preflight(
        PreflightRequest(installed_components=["orion-core", "dcs-integration", "aircraft-fa18c"]),
        handshake=_handshake(),
        mapping_registry=registry,
    )
    assert report.state is PreflightState.READY_TO_FLY
    assert report.aircraft.mapping_complete is True
    assert report.aircraft.mapping_version == "fa18c-clickable-calibrated-v1"
    assert report.next_action is None
