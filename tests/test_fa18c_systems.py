from fastapi.testclient import TestClient

from orion.app import app
from orion.fa18c_systems import (
    HornetProcedureId,
    HornetSystemId,
    OFFICIAL_GUIDE_SOURCE_ID,
    fa18c_knowledge_pack,
)


client = TestClient(app)


def test_hornet_system_pack_contains_core_systems() -> None:
    systems = fa18c_knowledge_pack.list_systems()
    ids = {item.system_id for item in systems}

    assert HornetSystemId.COMMUNICATIONS in ids
    assert HornetSystemId.TACAN in ids
    assert HornetSystemId.INS_NAVIGATION in ids
    assert HornetSystemId.AIR_TO_AIR_RADAR in ids
    assert HornetSystemId.CARRIER_OPERATIONS in ids


def test_hornet_systems_are_source_traceable() -> None:
    tacan = fa18c_knowledge_pack.get_system(HornetSystemId.TACAN)

    assert tacan is not None
    assert tacan.references
    assert tacan.references[0].source_id == OFFICIAL_GUIDE_SOURCE_ID
    assert "TCN" in tacan.references[0].section or "TACAN" in tacan.references[0].section
    assert "tacan_channel" in tacan.live_data_preferred


def test_tacan_lookup_returns_system_and_procedure() -> None:
    result = fa18c_knowledge_pack.find("tacan")

    assert any(item.system_id is HornetSystemId.TACAN for item in result["systems"])
    assert any(item.procedure_id is HornetProcedureId.TACAN_NAVIGATION for item in result["procedures"])


def test_radio_preset_procedure_is_live_data_aware() -> None:
    procedure = fa18c_knowledge_pack.get_procedure(HornetProcedureId.RADIO_PRESET_USE)

    assert procedure is not None
    assert procedure.state_aware is True
    assert any("mission data" in item for item in procedure.ordered_phases)


def test_fa18c_systems_api_is_mounted() -> None:
    response = client.get("/v1/aircraft-knowledge/fa-18c/systems")

    assert response.status_code == 200
    body = response.json()
    assert any(item["system_id"] == "communications" for item in body)
    assert any(item["system_id"] == "tacan" for item in body)


def test_fa18c_lookup_api_resolves_comm1() -> None:
    response = client.get("/v1/aircraft-knowledge/fa-18c/lookup", params={"q": "comm1"})

    assert response.status_code == 200
    body = response.json()
    assert any(item["system_id"] == "communications" for item in body["systems"])


def test_fa18c_procedure_api_exposes_ordered_phases() -> None:
    response = client.get("/v1/aircraft-knowledge/fa-18c/procedures/tacan_navigation")

    assert response.status_code == 200
    body = response.json()
    assert body["procedure_id"] == "tacan_navigation"
    assert len(body["ordered_phases"]) >= 4
