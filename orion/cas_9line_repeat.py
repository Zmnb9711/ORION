from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from orion.cas_9line import Cas9LineBrief
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommand, VoiceCommandCreate, voice_commands


class Cas9LineRepeatItem(StrEnum):
    LINE_1 = "line_1"
    LINE_2 = "line_2"
    LINE_3 = "line_3"
    LINE_4 = "line_4"
    LINE_5 = "line_5"
    LINE_6 = "line_6"
    LINE_7 = "line_7"
    LINE_8 = "line_8"
    LINE_9 = "line_9"
    REMARKS = "remarks"
    RESTRICTIONS = "restrictions"
    TARGET_LOCATION = "target_location"
    TARGET_ELEVATION = "target_elevation"
    MARK = "mark"


class Cas9LineRepeatRequest(BaseModel):
    item: Cas9LineRepeatItem


class Cas9LineRepeatResult(BaseModel):
    item: Cas9LineRepeatItem
    spoken_text: str


def repeat_text(brief: Cas9LineBrief, item: Cas9LineRepeatItem) -> str:
    ru = brief.language.casefold().startswith("ru")
    values = {
        Cas9LineRepeatItem.LINE_1: (f"Линия 1, ИП или БП {brief.ip_or_bp}.", f"Line 1, IP or BP {brief.ip_or_bp}."),
        Cas9LineRepeatItem.LINE_2: (f"Линия 2, курс {brief.heading_deg}.", f"Line 2, heading {brief.heading_deg}."),
        Cas9LineRepeatItem.LINE_3: (f"Линия 3, дистанция {brief.distance_nm:g} морских миль.", f"Line 3, distance {brief.distance_nm:g} nautical miles."),
        Cas9LineRepeatItem.LINE_4: (f"Линия 4, высота цели {brief.target_elevation_ft} футов.", f"Line 4, target elevation {brief.target_elevation_ft} feet."),
        Cas9LineRepeatItem.LINE_5: (f"Линия 5, цель {brief.target_description}.", f"Line 5, target {brief.target_description}."),
        Cas9LineRepeatItem.LINE_6: (f"Линия 6, координаты {brief.target_location}.", f"Line 6, target location {brief.target_location}."),
        Cas9LineRepeatItem.LINE_7: (f"Линия 7, маркировка {brief.mark}.", f"Line 7, mark {brief.mark}."),
        Cas9LineRepeatItem.LINE_8: (f"Линия 8, свои {brief.friendlies}.", f"Line 8, friendlies {brief.friendlies}."),
        Cas9LineRepeatItem.LINE_9: (f"Линия 9, выход {brief.egress}.", f"Line 9, egress {brief.egress}."),
        Cas9LineRepeatItem.REMARKS: (f"Замечания: {brief.remarks or 'нет'}.", f"Remarks: {brief.remarks or 'none'}."),
        Cas9LineRepeatItem.RESTRICTIONS: (f"Ограничения: {brief.restrictions or 'нет'}.", f"Restrictions: {brief.restrictions or 'none'}."),
        Cas9LineRepeatItem.TARGET_LOCATION: (f"Координаты цели {brief.target_location}.", f"Target location {brief.target_location}."),
        Cas9LineRepeatItem.TARGET_ELEVATION: (f"Высота цели {brief.target_elevation_ft} футов.", f"Target elevation {brief.target_elevation_ft} feet."),
        Cas9LineRepeatItem.MARK: (f"Маркировка {brief.mark}.", f"Mark {brief.mark}."),
    }
    pair = values[item]
    return pair[0] if ru else pair[1]


def submit_repeat_voice(brief: Cas9LineBrief, item: Cas9LineRepeatItem) -> VoiceCommand:
    text = repeat_text(brief, item)
    return voice_commands.submit(
        VoiceCommandCreate(
            transcript=text,
            intent="cas_9line_say_again",
            agent=VoiceAgent.JTAC,
            priority=CommandPriority.NORMAL,
            context={"brief_id": str(brief.brief_id), "repeat_item": item.value},
        )
    )
