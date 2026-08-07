from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from orion.app import app
from orion.dcs_installations import DcsInstallationCreate, dcs_installations
from orion.dcs_readiness import install_export_integration
from orion.models import AircraftState, Position, TelemetryEnvelope
from orion.telemetry_handshake import TelemetryHandshake, telemetry_handshake


RECOMMENDED = ["orion-core", "dcs-integration", "aircraft-fa18c", "online-voice"]


def _telemetry() -> TelemetryEnvelope:
    return TelemetryEnvelope(
        protocol_version="0.2",
        source="dcs-export",
        state=AircraftState(
            aircraft_type="FA-18C_hornet",
            position=Position(latitude=36.0, longitude=30.0, altitude_m=1000.0),
            heading_deg=90.0,
            true_airspeed_mps=150.0,
        ),
    )


def test_handshake_becomes_stale_without_new_packets() -> None:
    handshake = TelemetryHandshake(stale_after_seconds=5)
    observed = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    handshake.observe(_telemetry(), received_at=observed)

    fresh = handshake.snapshot(now=observed + timedelta(seconds=4))
    stale = handshake.snapshot(now=observed + timedelta(seconds=6))

    assert fresh.connected is True
    assert fresh.aircraft_type == "FA-18C_hornet"
    assert fresh.packet_count == 1
    assert stale.connected is False
    assert stale.aircraft_type is None


def test_first_run_api_uses_real_flight_bridge_telemetry(tmp_path: Path) -> None:
    executable = tmp_path / "DCS.exe"
    executable.write_text("stub", encoding="utf-8")
    installation = dcs_installations.create(
        DcsInstallationCreate(name="Handshake DCS", executable_path=str(executable))
    )
    saved_games = tmp_path / "Saved Games" / "DCS"
    install_export_integration(str(saved_games))
    telemetry_handshake.reset()

    client = TestClient(app)
    try:
        waiting = client.post(
            "/v1/first-run/status",
            json={"saved_games_path": str(saved_games), "installed_components": RECOMMENDED},
        )
        assert waiting.status_code == 200
        assert waiting.json()["state"] == "waiting_for_dcs"

        accepted = client.post(
            "/v1/flight-bridge/telemetry",
            json=_telemetry().model_dump(mode="json"),
        )
        assert accepted.status_code == 202

        ready = client.post(
            "/v1/first-run/status",
            json={"saved_games_path": str(saved_games), "installed_components": RECOMMENDED},
        )
        assert ready.status_code == 200
        assert ready.json()["state"] == "ready_to_fly"
        telemetry_check = next(item for item in ready.json()["checks"] if item["key"] == "telemetry")
        assert telemetry_check["passed"] is True
        assert "FA-18C_hornet" in telemetry_check["message"]
    finally:
        telemetry_handshake.reset()
        dcs_installations.delete(installation.installation_id)
