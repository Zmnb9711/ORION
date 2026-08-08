from unittest.mock import patch

import pytest

from orion.cas_9line import Cas9LineBriefCreate, Cas9LineReadback, Cas9LineState, Cas9LineStore
from orion.jtac_runtime import JtacDesignationMethod
from orion.mission_control_jtac import MissionControlJtacResult


def _payload(language: str = "en") -> Cas9LineBriefCreate:
    return Cas9LineBriefCreate(
        target_id="sam-1",
        ip_or_bp="FORD",
        heading_deg=270,
        distance_nm=6.5,
        target_elevation_ft=1200,
        target_description="SA-11 TELAR",
        target_location="N41 10.200 E041 20.300",
        mark="laser",
        friendlies="south 2 km",
        egress="east",
        remarks="final attack heading 240-300",
        restrictions="remain north of river",
        method=JtacDesignationMethod.LASER,
        laser_code=1688,
        language=language,
    )


def test_issue_requires_readback_before_tasking() -> None:
    store = Cas9LineStore()
    brief = store.create(_payload())
    issued = store.issue(brief.brief_id)
    assert issued.state is Cas9LineState.READBACK_PENDING
    with pytest.raises(ValueError, match="verified readback"):
        store.task(brief.brief_id)


def test_correct_readback_verifies_critical_fields() -> None:
    store = Cas9LineStore()
    brief = store.create(_payload())
    store.issue(brief.brief_id)
    verified = store.verify_readback(
        brief.brief_id,
        Cas9LineReadback(
            target_elevation_ft=1200,
            target_location="N41 10.200 E041 20.300",
            restrictions="remain north of river",
        ),
    )
    assert verified.state is Cas9LineState.VERIFIED
    assert verified.readback_verified is True


def test_readback_mismatch_is_rejected() -> None:
    store = Cas9LineStore()
    brief = store.create(_payload())
    store.issue(brief.brief_id)
    with pytest.raises(ValueError, match="target elevation"):
        store.verify_readback(
            brief.brief_id,
            Cas9LineReadback(
                target_elevation_ft=1300,
                target_location="N41 10.200 E041 20.300",
                restrictions="remain north of river",
            ),
        )
    pending = store.get(brief.brief_id)
    assert pending is not None
    assert pending.state is Cas9LineState.READBACK_PENDING


def test_verified_brief_hands_off_to_jtac_orchestration() -> None:
    store = Cas9LineStore()
    brief = store.create(_payload("ru"))
    store.issue(brief.brief_id)
    store.verify_readback(
        brief.brief_id,
        Cas9LineReadback(
            target_elevation_ft=1200,
            target_location="N41 10.200 E041 20.300",
            restrictions="remain north of river",
        ),
    )
    result = MissionControlJtacResult(accepted=True, target_id="sam-1", spoken_text="queued")
    with patch("orion.cas_9line.orchestrate_jtac", return_value=result) as orchestrate:
        tasked = store.task(brief.brief_id)
    request = orchestrate.call_args.args[0]
    assert request.target_id == "sam-1"
    assert request.method is JtacDesignationMethod.LASER
    assert request.laser_code == 1688
    assert request.language == "ru"
    assert tasked.state is Cas9LineState.TASKED


def test_smoke_brief_drops_laser_code() -> None:
    store = Cas9LineStore()
    payload = _payload().model_copy(update={"method": JtacDesignationMethod.SMOKE, "laser_code": 1688, "smoke_color": "orange"})
    brief = store.create(payload)
    assert brief.laser_code is None
