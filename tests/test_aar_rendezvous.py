from __future__ import annotations

import pytest

import orion.aar_rendezvous as aar_module
from orion.aar_rendezvous import AarPhase, aar_rendezvous
from orion.dcs_capabilities import DcsRecipientType
from orion.mission import Coalition
from orion.mission_context import LiveMissionContext, OwnshipContext, SupportAsset


@pytest.fixture(autouse=True)
def reset_aar() -> None:
    aar_rendezvous.reset()
    yield
    aar_rendezvous.reset()


def _context(distance_km: float = 18.52, *, ownship_speed_mps: float | None = 250.0, tanker_longitude: float = 41.2) -> LiveMissionContext:
    return LiveMissionContext(
        available=True,
        ownship=OwnshipContext(
            aircraft_type="FA-18C_hornet",
            latitude=41.0,
            longitude=41.0,
            altitude_m=5000,
            heading_deg=90,
            true_airspeed_mps=ownship_speed_mps,
        ),
        tankers=[
            SupportAsset(
                unit_id="tanker-1",
                callsign="Texaco",
                role=DcsRecipientType.TANKER,
                coalition=Coalition.BLUE,
                available=True,
                aar_available=True,
                latitude=41.0,
                longitude=tanker_longitude,
                altitude_m=7000,
                distance_km=distance_km,
                bearing_deg=90,
                heading_deg=0,
                speed_mps=150,
                frequency_mhz=251.5,
                modulation="AM",
                tacan_channel=31,
                tacan_band="Y",
            )
        ],
    )


def _stable_precontact_context() -> LiveMissionContext:
    context = _context(0.5, ownship_speed_mps=151.0, tanker_longitude=41.005)
    context.ownship.altitude_m = 7000
    context.tankers[0].heading_deg = 90
    return context


def test_start_selects_nearest_available_tanker(monkeypatch) -> None:
    monkeypatch.setattr(aar_module, "build_live_mission_context", _context)
    result = aar_rendezvous.execute("aar_start", "Начать дозаправку")
    assert result.completed is True
    assert result.session.phase == AarPhase.RENDEZVOUS
    assert result.session.tanker_callsign == "Texaco"
    assert "10.0 морских миль" in result.spoken_text
    assert "22966 футов" in result.spoken_text
    assert "292 узлов" in result.spoken_text
    assert "251.500" in result.spoken_text
    assert "TACAN 31 Y" in result.spoken_text
    assert "Рекомендуемый курс перехвата" in result.spoken_text
    assert result.data["intercept_guidance"] is not None


def test_status_recomputes_intercept_guidance(monkeypatch) -> None:
    contexts = [_context(18.52, tanker_longitude=41.2), _context(9.26, tanker_longitude=41.1)]
    monkeypatch.setattr(aar_module, "build_live_mission_context", lambda: contexts.pop(0))
    started = aar_rendezvous.execute("aar_start", "Начать дозаправку")
    first_eta = started.data["intercept_guidance"]["eta_s"]
    status = aar_rendezvous.execute("aar_status", "Статус сближения")
    second_eta = status.data["intercept_guidance"]["eta_s"]
    assert second_eta < first_eta


def test_guidance_is_omitted_when_ownship_speed_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(aar_module, "build_live_mission_context", lambda: _context(18.52, ownship_speed_mps=None))
    result = aar_rendezvous.execute("aar_start", "Начать дозаправку")
    assert result.completed is True
    assert result.data["intercept_guidance"] is None
    assert "Рекомендуемый курс перехвата" not in result.spoken_text


def test_range_drives_only_rendezvous_and_join_up(monkeypatch) -> None:
    monkeypatch.setattr(aar_module, "build_live_mission_context", lambda: _context(9.26))
    aar_rendezvous.execute("aar_start", "Start refueling")
    assert aar_rendezvous.snapshot().phase == AarPhase.RENDEZVOUS

    monkeypatch.setattr(aar_module, "build_live_mission_context", lambda: _context(3.704))
    result = aar_rendezvous.execute("aar_status", "Статус дозаправки")
    assert result.session.phase == AarPhase.JOIN_UP


def test_pre_contact_is_gated_by_stabilized_join_up(monkeypatch) -> None:
    unstable = _context(0.5)
    monkeypatch.setattr(aar_module, "build_live_mission_context", lambda: unstable)
    aar_rendezvous.execute("aar_start", "Начать дозаправку")
    rejected = aar_rendezvous.execute("aar_pre_contact", "Pre-contact")
    assert rejected.completed is False
    assert rejected.session.phase == AarPhase.JOIN_UP
    assert rejected.data["precontact_readiness"]["ready_for_precontact"] is False

    stable = _stable_precontact_context()
    monkeypatch.setattr(aar_module, "build_live_mission_context", lambda: stable)
    pre = aar_rendezvous.execute("aar_pre_contact", "Pre-contact")
    assert pre.completed is True
    assert pre.session.phase == AarPhase.PRE_CONTACT
    assert pre.data["intercept_guidance"] is None
    assert pre.data["precontact_readiness"]["ready_for_precontact"] is True

    status = aar_rendezvous.execute("aar_status", "Status")
    assert status.session.phase == AarPhase.PRE_CONTACT
    contact = aar_rendezvous.execute("aar_contact", "Contact with tanker")
    assert contact.session.phase == AarPhase.CONTACT


def test_abort_and_complete_are_explicit(monkeypatch) -> None:
    monkeypatch.setattr(aar_module, "build_live_mission_context", _context)
    aar_rendezvous.execute("aar_start", "Start refueling")
    aborted = aar_rendezvous.execute("aar_abort", "Abort refueling")
    assert aborted.session.phase == AarPhase.ABORTED

    aar_rendezvous.reset()
    aar_rendezvous.execute("aar_start", "Start refueling")
    completed = aar_rendezvous.execute("aar_complete", "Refueling complete")
    assert completed.session.phase == AarPhase.COMPLETE


def test_missing_mission_context_does_not_invent_tanker(monkeypatch) -> None:
    monkeypatch.setattr(aar_module, "build_live_mission_context", lambda: LiveMissionContext(available=False, issues=["mission_snapshot_unavailable"]))
    result = aar_rendezvous.execute("aar_start", "Начать дозаправку")
    assert result.completed is False
    assert result.session.phase == AarPhase.IDLE
    assert result.data["issues"] == ["mission_snapshot_unavailable"]
