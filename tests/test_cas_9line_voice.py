from orion.cas_9line import Cas9LineBriefCreate, Cas9LineState, Cas9LineStore
from orion.cas_9line_voice import cas_9line_text


def _brief(language: str):
    return Cas9LineStore().create(
        Cas9LineBriefCreate(
            target_id="target-1",
            ip_or_bp="FORD",
            heading_deg=270,
            distance_nm=6,
            target_elevation_ft=1200,
            target_description="armor",
            target_location="N41 E041",
            mark="laser",
            friendlies="south",
            egress="east",
            restrictions="remain north",
            language=language,
        )
    )


def test_english_issue_requests_critical_readback() -> None:
    brief = _brief("en").model_copy(update={"state": Cas9LineState.READBACK_PENDING})
    text = cas_9line_text(brief)
    assert "Target elevation 1200 feet" in text
    assert "Location N41 E041" in text
    assert "Read back target elevation" in text


def test_russian_issue_requests_critical_readback() -> None:
    brief = _brief("ru").model_copy(update={"state": Cas9LineState.READBACK_PENDING})
    text = cas_9line_text(brief)
    assert "Высота цели 1200 футов" in text
    assert "Координаты N41 E041" in text
    assert "Повторите высоту цели" in text
