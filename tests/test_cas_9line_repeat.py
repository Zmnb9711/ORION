from orion.cas_9line import Cas9LineBriefCreate, Cas9LineStore
from orion.cas_9line_repeat import Cas9LineRepeatItem, repeat_text


def _brief(language: str = "en"):
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
            remarks="final attack heading 240-300",
            restrictions="remain north",
            language=language,
        )
    )


def test_repeat_line_six_does_not_repeat_entire_brief() -> None:
    text = repeat_text(_brief("en"), Cas9LineRepeatItem.LINE_6)
    assert text == "Line 6, target location N41 E041."
    assert "FORD" not in text
    assert "1200" not in text


def test_repeat_restrictions_in_russian() -> None:
    text = repeat_text(_brief("ru"), Cas9LineRepeatItem.RESTRICTIONS)
    assert text == "Ограничения: remain north."


def test_repeat_target_elevation_is_specific() -> None:
    text = repeat_text(_brief("en"), Cas9LineRepeatItem.TARGET_ELEVATION)
    assert text == "Target elevation 1200 feet."
