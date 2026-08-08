from __future__ import annotations

from orion.cas_9line import Cas9LineBrief, Cas9LineState
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommand, VoiceCommandCreate, voice_commands


def _readback_correction_text(brief: Cas9LineBrief, ru: bool) -> str:
    fields = set(brief.readback_mismatches)
    parts: list[str] = []
    if "target elevation" in fields:
        parts.append(f"высота цели {brief.target_elevation_ft} футов" if ru else f"target elevation {brief.target_elevation_ft} feet")
    if "target location" in fields:
        parts.append(f"координаты {brief.target_location}" if ru else f"target location {brief.target_location}")
    if "restrictions" in fields:
        value = brief.restrictions or ("нет" if ru else "none")
        parts.append(f"ограничения {value}" if ru else f"restrictions {value}")
    if "remarks acknowledgement" in fields:
        value = brief.remarks or ("нет" if ru else "none")
        parts.append(f"подтвердите замечания {value}" if ru else f"acknowledge remarks {value}")
    if not parts:
        return "Повторьте обязательные элементы." if ru else "Repeat required readback items."
    joined = "; ".join(parts)
    return f"Неверный повтор. Исправление: {joined}. Повторите исправленные элементы." if ru else f"Readback incorrect. Correction: {joined}. Read back corrected items."


def cas_9line_text(brief: Cas9LineBrief) -> str:
    ru = brief.language.casefold().startswith("ru")
    if brief.state is Cas9LineState.READBACK_PENDING:
        if brief.readback_mismatches:
            return _readback_correction_text(brief, ru)
        restrictions = brief.restrictions or ("нет" if ru else "none")
        remarks = brief.remarks or ("нет" if ru else "none")
        if ru:
            return (
                f"9-line. ИП или БП {brief.ip_or_bp}. Курс {brief.heading_deg}. Дистанция {brief.distance_nm:g} морских миль. "
                f"Высота цели {brief.target_elevation_ft} футов. Цель: {brief.target_description}. Координаты {brief.target_location}. "
                f"Маркировка {brief.mark}. Свои {brief.friendlies}. Выход {brief.egress}. "
                f"Ограничения: {restrictions}. Замечания: {remarks}. "
                "Повторите высоту цели, координаты и ограничения; подтвердите замечания."
            )
        return (
            f"9-line. IP or BP {brief.ip_or_bp}. Heading {brief.heading_deg}. Distance {brief.distance_nm:g} nautical miles. "
            f"Target elevation {brief.target_elevation_ft} feet. Target: {brief.target_description}. Location {brief.target_location}. "
            f"Mark {brief.mark}. Friendlies {brief.friendlies}. Egress {brief.egress}. "
            f"Restrictions: {restrictions}. Remarks: {remarks}. "
            "Read back target elevation, target location, and restrictions; acknowledge remarks."
        )
    if brief.state is Cas9LineState.VERIFIED:
        return "Readback correct. Remarks acknowledged. Stand by for JTAC tasking." if not ru else "Повтор верный. Замечания подтверждены. Ожидайте постановку задачи JTAC."
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
                "remarks_acknowledged": brief.remarks_acknowledged,
                "readback_mismatches": brief.readback_mismatches,
            },
        )
    )
