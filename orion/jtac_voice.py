from __future__ import annotations

from orion.jtac_runtime import JtacDesignationMethod, JtacSession, JtacSessionState
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommand, VoiceCommandCreate, voice_commands


def jtac_session_text(session: JtacSession, language: str = "en") -> str:
    ru = language.casefold().startswith("ru")

    if session.state is JtacSessionState.ASSIGNED:
        if session.method is JtacDesignationMethod.LASER:
            return (
                f"JTAC назначен. Лазерный код {session.laser_code}."
                if ru
                else f"JTAC assigned. Laser code {session.laser_code}."
            )
        return "JTAC назначен. Маркировка дымом готова." if ru else "JTAC assigned. Smoke marking ready."

    if session.state is JtacSessionState.MARKING:
        if session.method is JtacDesignationMethod.LASER:
            return (
                f"Лазер включён. Код {session.laser_code}."
                if ru
                else f"Laser on. Code {session.laser_code}."
            )
        color = session.smoke_color or "red"
        return f"Цель отмечена дымом, цвет {color}." if ru else f"Target marked with {color} smoke."

    if session.state is JtacSessionState.COMPLETE:
        return "JTAC задача завершена." if ru else "JTAC task complete."
    if session.state is JtacSessionState.FAILED:
        return f"JTAC запрос не выполнен. {session.message}" if ru else f"JTAC request failed. {session.message}"
    return "JTAC поддержка запрошена." if ru else "JTAC support requested."


def submit_jtac_voice(session: JtacSession, language: str = "en") -> VoiceCommand:
    text = jtac_session_text(session, language)
    priority = CommandPriority.HIGH if session.state in {JtacSessionState.MARKING, JtacSessionState.FAILED} else CommandPriority.NORMAL
    return voice_commands.submit(
        VoiceCommandCreate(
            transcript=text,
            intent="jtac_session_update",
            agent=VoiceAgent.JTAC,
            priority=priority,
            context={
                "session_id": str(session.session_id),
                "state": session.state.value,
                "method": session.method.value,
                "laser_code": session.laser_code,
                "target_id": session.target_id,
                "assigned_asset_id": session.assigned_asset_id,
            },
        )
    )
