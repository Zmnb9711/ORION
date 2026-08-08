from __future__ import annotations

from threading import RLock
from uuid import UUID

from pydantic import BaseModel

from orion.jtac_runtime import JtacDesignationMethod, JtacSession, JtacSessionState, jtac_sessions
from orion.jtac_voice import submit_jtac_voice
from orion.mission_bridge import MissionCommand, MissionCommandType, mission_bridge
from orion.mission_command_status import MissionCommandStatus, mission_command_statuses


class JtacCancellationResult(BaseModel):
    accepted: bool
    session_id: UUID
    cancel_command_id: UUID | None = None
    spoken_text: str


_lock = RLock()
_cancel_to_session: dict[UUID, UUID] = {}


def cancel_jtac(session_id: UUID) -> JtacCancellationResult:
    session = jtac_sessions.get(session_id)
    if session is None:
        raise KeyError("JTAC session not found")
    if session.state in {JtacSessionState.COMPLETE, JtacSessionState.CANCELLED, JtacSessionState.FAILED}:
        return JtacCancellationResult(accepted=False, session_id=session_id, spoken_text=_already_finished_text(session))

    command = MissionCommand(
        command=MissionCommandType.STOP_LASER if session.method is JtacDesignationMethod.LASER else MissionCommandType.STOP_SMOKE,
        target_unit_id=session.target_id,
        provider_unit_id=session.assigned_asset_id,
        laser_code=session.laser_code if session.method is JtacDesignationMethod.LASER else None,
        smoke_color=session.smoke_color if session.method is JtacDesignationMethod.SMOKE else None,
    )
    mission_bridge.send(command)
    with _lock:
        _cancel_to_session[command.command_id] = session_id
    text = "Запрос на прекращение маркировки передан." if session.language.casefold().startswith("ru") else "Request to stop marking sent."
    return JtacCancellationResult(accepted=True, session_id=session_id, cancel_command_id=command.command_id, spoken_text=text)


def observe_cancel_status(command_id: UUID) -> JtacSession | None:
    with _lock:
        session_id = _cancel_to_session.get(command_id)
    if session_id is None:
        return None
    result = mission_command_statuses.get(command_id)
    if result is None or result.status in {MissionCommandStatus.QUEUED, MissionCommandStatus.ACCEPTED}:
        return jtac_sessions.get(session_id)
    session = jtac_sessions.get(session_id)
    if session is None:
        with _lock:
            _cancel_to_session.pop(command_id, None)
        return None
    if result.status is MissionCommandStatus.COMPLETED:
        updated = jtac_sessions.transition(session_id, JtacSessionState.CANCELLED, marker_active=False, message=result.message or "JTAC cancellation confirmed by mission-side")
        submit_jtac_voice(updated, updated.language)
    else:
        updated = session
    with _lock:
        _cancel_to_session.pop(command_id, None)
    return updated


def _already_finished_text(session: JtacSession) -> str:
    if session.language.casefold().startswith("ru"):
        return "JTAC задача уже завершена или неактивна."
    return "JTAC task is already complete or inactive."
