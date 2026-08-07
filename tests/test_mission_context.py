from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from orion.app import app
from orion.coalition_radio import CoalitionRadioUnit, RadioModulation, coalition_radio
from orion.dcs_capabilities import DcsRecipientType
from orion.live_telemetry_store import live_telemetry
from orion.mission import Coalition, MissionPosition, MissionSnapshot, MissionUnit
from orion.mission_context import build_live_mission_context
from orion.mission_store import mission_store
from orion.models import AircraftState, Position, TelemetryEnvelope


@pytest.fixture(autouse=True)
def reset_context() -> None:
    mission_store._snapshot = None
    live_telemetry.clear()
    coalition_radio.replace([])
    yield
    mission_store._snapshot = None
    live_telemetry.clear()
    coalition_radio.replace([])


def _telemetry() -> TelemetryEnvelope:
    return TelemetryEnvelope(
        timestamp=datetime.now(UTC),
        state=AircraftState(
            aircraft_type="FA-18C_hornet",
            position=Position(latitude=41.0, longitude=41.0, altitude_m=5000),
            heading_deg=90,
            airspeed_mps=200,
        ),
    )


def test_context_combines_ownship_contacts_and_support_assets() -> None:
    live_telemetry.set(_telemetry())
    mission_store.replace(MissionSnapshot(
        mission_id="mission-1",
        name="Test mission",
        theatre="Caucasus",
        units=[
            MissionUnit(unit_id="blue-1", name="Ford 2-1", coalition=Coalition.BLUE, position=MissionPosition(latitude=41.1, longitude=41.0, altitude_m=6000)),
            MissionUnit(unit_id="red-1", name="Bandit 1", coalition=Coalition.RED, position=MissionPosition(latitude=41.0, longitude=41.2, altitude_m=7000)),
        ],
    ))
    coalition_radio.replace([
        CoalitionRadioUnit(unit_id="awacs-1", callsign="Magic", recipient_type=DcsRecipientType.AWACS, coalition="blue", frequency_mhz=251.0, modulation=RadioModulation.AM),
        CoalitionRadioUnit(unit_id="tanker-1", callsign="Texaco", recipient_type=DcsRecipientType.TANKER, coalition="blue", frequency_mhz=251.5, modulation=RadioModulation.AM),
        CoalitionRadioUnit(unit_id="jtac-1", callsign="Axeman", recipient_type=DcsRecipientType.JTAC, coalition="blue", frequency_mhz=133.0, modulation=RadioModulation.AM),
    ])

    context = build_live_mission_context()

    assert context.available is True
    assert context.ownship is not None
    assert context.ownship.aircraft_type == "FA-18C_hornet"
    assert context.friendlies[0].name == "Ford 2-1"
    assert context.friendlies[0].distance_km is not None
    assert context.hostiles[0].name == "Bandit 1"
    assert context.awacs[0].callsign == "Magic"
    assert context.tankers[0].callsign == "Texaco"
    assert context.jtac[0].callsign == "Axeman"


def test_context_reports_missing_sources_without_inventing_data() -> None:
    context = build_live_mission_context()
    assert context.available is False
    assert context.ownship is None
    assert context.friendlies == []
    assert context.hostiles == []
    assert set(context.issues) == {"mission_snapshot_unavailable", "ownship_telemetry_unavailable"}


def test_mission_context_api() -> None:
    mission_store.replace(MissionSnapshot(mission_id="mission-api"))
    client = TestClient(app)
    response = client.get("/v1/mission-context")
    assert response.status_code == 200
    assert response.json()["mission_id"] == "mission-api"
