from __future__ import annotations

from orion.cas_9line import Cas9LineBrief, Cas9LineState
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommand, VoiceCommandCreate, voice_commands


def cas_9line_text(brief: Cas9LineBrief) -> str:
    ru = brief.language.casefold().startswith("ru")
    if brief.state is Cas9LineState.READBACK_PENDING:
        if ru:
            return (
                f"9-line. ИП или БП {brief.ip_or_bp}. Курс {brief.heading_deg}. Дистанция {brief.distance_nm:g} морских миль. "
                f"Высота цели {brief.target_elevation_ft} футов. Цель: {brief.target_description}. Координаты {brief.target_location}. "
                f"Маркировка {brief.mark}. Свои {brief.friendlies}. Выход {brief.egress}. "
                f"Повторите высоту цели, координаты и ограничения."
            )
        return (
            f"9-line. IP or BP {brief.ip_or_bp}. Heading {brief.heading_deg}. Distance {brief.distance_nm:g} nautical miles. "
            f"Target elevation {brief.target_elevation_ft} feet. Target: {brief.target_description}. Location {brief.target_location}. "
            f"Mark {brief.mark}. Friendlies {brief.friendlies}. Egress {brief.egress}. "
            "Read back target elevation, target location, and restrictions."
        )
    if brief.state is Cas9LineState.VERIFIED:
        return "Readback correct. Stand by for JTAC tasking." if not ru else "Повтор верный. Ожидайте постановку задачи JTAC."
    if brief.state is Cas9LineState.TASKED:
        return "9-line verified. JTAC tasking initiated." if not ru else "9-line подтверждён. Задача JTAC передана."
    if brief.state is Cas9LineState.ABORTED:
        return "CAS 9-line aborted." if not ru else "CAS 9-line отменён."
    return "CAS 9-line draft created." if not ru else "Черновик CAS 9-line создан."


def submit_cas_9line_voice(brief: Cas9LineBrief) -> VoiceCommand:
    return voice_commands.submit(
        VoiceCommandCreate(
            transcript=cas_9line_text(brief),
            intent="cas_9line_update",
            agent=VoiceAgent.JTAC,
            priority=CommandPriority.HIGH if brief.state in {Cas9LineState.READBACK_PENDING, Cas9LineState.TASKED} else CommandPriority.NORMAL,
            context={
                "brief_id": str(brief.brief_id),
                "state": brief.state.value,
                "target_id": brief.target_id,
                "laser_code": brief.laser_code,
                "readback_verified": brief.readback_verified,
            },
        )
    )
