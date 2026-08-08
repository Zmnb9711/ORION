import pytest
from fastapi.testclient import TestClient

from orion.aar_rendezvous import AarPhase, aar_rendezvous
from orion.app import app
from orion.dcs_capabilities import DcsRecipientType
from orion.dialogue import DialogueIntent, DialogueRequest
from orion.dialogue_runtime import run_dialogue
from orion.mission import Coalition
from orion.mission_context import LiveMissionContext, MissionContact, OwnshipContext, SupportAsset


@pytest.fixture(autouse=True)
def reset_aar() -> None:
    aar_rendezvous.reset()
    yield
    aar_rendezvous.reset()


def _context() -> LiveMissionContext:
    return LiveMissionContext(
        available=True,
        mission_id="mission-runtime",
        ownship=OwnshipContext(
            aircraft_type="FA-18C_hornet",
            latitude=41.0,
            longitude=41.0,
            altitude_m=6096,
            heading_deg=91,
            true_airspeed_mps=205.8,
        ),
        hostiles=[
            MissionContact(
                unit_id="red-1",
                name="Bandit 1",
                coalition=Coalition.RED,
                type_name="MiG-29",
                latitude=41.1,
                longitude=41.0,
                altitude_m=7000,
                distance_km=18.4,
                bearing_deg=12,
            )
        ],
        awacs=[
            SupportAsset(
                unit_id="awacs-1",
                callsign="Magic",
                role=DcsRecipientType.AWACS,
                coalition=Coalition.BLUE,
                available=True,
                frequency_mhz=251.0,
                distance_km=95.2,
                bearing_deg=310,
            )
        ],
        tankers=[
            SupportAsset(
                unit_id="tanker-1",
                callsign="Texaco",
                role=DcsRecipientType.TANKER,
                coalition=Coalition.BLUE,
                available=True,
                aar_available=True,
                frequency_mhz=251.5,
                tacan_channel=31,
                tacan_band="Y",
                distance_km=42.7,
                bearing_deg=275,
            )
        ],
    )


def test_status_is_grounded_in_ownship_telemetry() -> None:
    result = run_dialogue(DialogueRequest(text="Какой у меня статус?"), _context())
    assert result.intent is DialogueIntent.STATUS
    assert result.grounded is True
    assert result.facts["altitude_ft"] == 20000
    assert result.facts["true_airspeed_kt"] == 400
    assert "курс 091" in result.reply


def test_threat_picture_reports_nearest_hostile() -> None:
    result = run_dialogue(DialogueRequest(text="Какие угрозы вокруг?"), _context())
    assert result.intent is DialogueIntent.THREATS
    assert result.grounded is True
    assert result.facts["nearest_name"] == "Bandit 1"
    assert result.facts["hostile_count"] == 1
    assert "018.4" not in result.reply
    assert "18.4 км" in result.reply


def test_tanker_response_contains_frequency_and_tacan_without_starting_aar() -> None:
    result = run_dialogue(DialogueRequest(text="Where is the tanker?"), _context())
    assert result.intent is DialogueIntent.TANKER
    assert result.grounded is True
    assert result.action_executed is False
    assert result.facts["callsign"] == "Texaco"
    assert "251.500 MHz" in result.reply
    assert "TACAN 31Y" in result.reply
    assert aar_rendezvous.snapshot().phase is AarPhase.IDLE


def test_explicit_refueling_request_starts_aar_session() -> None:
    result = run_dialogue(DialogueRequest(text="Request refueling"), _context())
    assert result.intent is DialogueIntent.TANKER
    assert result.action_executed is True
    assert result.action == "aar_start"
    assert result.facts["tanker_callsign"] == "Texaco"
    assert result.facts["aar_phase"] == "rendezvous"
    session = aar_rendezvous.snapshot()
    assert session.phase is AarPhase.RENDEZVOUS
    assert session.tanker_unit_id == "tanker-1"
    assert "Starting rendezvous with Texaco" in result.reply


def test_russian_explicit_refueling_request_starts_aar_session() -> None:
    result = run_dialogue(DialogueRequest(text="Запросить дозаправку"), _context())
    assert result.action_executed is True
    assert result.action == "aar_start"
    assert result.facts["tanker_callsign"] == "Texaco"
    assert "Начинаю сближение с Texaco" in result.reply


def test_active_aar_update_is_read_only_and_keeps_session() -> None:
    run_dialogue(DialogueRequest(text="Start AAR"), _context())
    result = run_dialogue(DialogueRequest(text="AAR status"), _context())
    assert result.intent is DialogueIntent.TANKER
    assert result.action == "aar_update"
    assert result.action_executed is False
    assert result.grounded is True
    assert result.facts["aar_phase"] == "rendezvous"
    assert aar_rendezvous.snapshot().phase is AarPhase.RENDEZVOUS
    assert "Current tanker Texaco" in result.reply


def test_precontact_request_is_rejected_until_joinup_is_stable() -> None:
    run_dialogue(DialogueRequest(text="Start AAR"), _context())
    result = run_dialogue(DialogueRequest(text="Ready for pre-contact"), _context())
    assert result.intent is DialogueIntent.TANKER
    assert result.action == "aar_pre_contact"
    assert result.action_executed is False
    assert result.grounded is False
    assert result.facts["aar_phase"] == "rendezvous"
    assert result.issues == ["aar_pre_contact_failed"]
    assert aar_rendezvous.snapshot().phase is AarPhase.RENDEZVOUS
    assert "Pre-contact is not ready yet" in result.reply


def test_abort_refueling_ends_active_dialogue_session() -> None:
    run_dialogue(DialogueRequest(text="Start AAR"), _context())
    result = run_dialogue(DialogueRequest(text="Abort refueling"), _context())
    assert result.intent is DialogueIntent.TANKER
    assert result.action == "aar_abort"
    assert result.action_executed is True
    assert result.facts["aar_phase"] == "aborted"
    assert aar_rendezvous.snapshot().phase is AarPhase.ABORTED
    assert "Aerial refueling procedure aborted" in result.reply


def test_laser_request_remains_unexecuted_and_requires_confirmation() -> None:
    result = run_dialogue(DialogueRequest(text="Подсвети цель лазером"), _context())
    assert result.intent is DialogueIntent.LASER
    assert result.requires_confirmation is True
    assert result.grounded is False
    assert result.action_executed is False


def test_missing_telemetry_is_reported_without_inventing_status() -> None:
    context = LiveMissionContext(available=True, issues=["ownship_telemetry_unavailable"])
    result = run_dialogue(DialogueRequest(text="status", language="en"), context)
    assert result.grounded is False
    assert result.facts == {}
    assert "No current aircraft telemetry" in result.reply


def test_dialogue_runtime_api(monkeypatch) -> None:
    import orion.dialogue_runtime as runtime_module

    monkeypatch.setattr(runtime_module, "build_live_mission_context", _context)
    with TestClient(app) as client:
        response = client.post("/v1/dialogue-runtime", json={"text": "Request AWACS picture", "language": "auto"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "awacs"
    assert payload["grounded"] is True
    assert payload["facts"]["callsign"] == "Magic"
    assert "251.000 MHz" in payload["reply"]


def test_dialogue_runtime_api_can_start_aar(monkeypatch) -> None:
    import orion.dialogue_runtime as runtime_module

    monkeypatch.setattr(runtime_module, "build_live_mission_context", _context)
    with TestClient(app) as client:
        response = client.post("/v1/dialogue-runtime", json={"text": "Start AAR", "language": "auto"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "tanker"
    assert payload["action_executed"] is True
    assert payload["action"] == "aar_start"
    assert payload["facts"]["aar_phase"] == "rendezvous"
