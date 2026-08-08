from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from orion.jtac_runtime import JtacDesignationMethod, JtacSession, JtacSessionCreate, JtacSessionState, jtac_sessions
from orion.jtac_voice import jtac_session_text, submit_jtac_voice
from orion.mission_control_runtime import build_mission_control_picture


class JtacTargetMode(StrEnum):
    EXPLICIT = "explicit"
    PRIMARY_SURFACE_THREAT = "primary_surface_threat"


class MissionControlJtacRequest(BaseModel):
    target_mode: JtacTargetMode = JtacTargetMode.EXPLICIT
    target_id: str | None = None
    method: JtacDesignationMethod = JtacDesignationMethod.LASER
    laser_code: int | None = Field(default=1688, ge=1111, le=1788)
    smoke_color: str = "red"
    requested_asset_id: str | None = None
    language: str = "en"


class MissionControlJtacResult(BaseModel):
    accepted: bool
    target_id: str | None = None
    target_name: str | None = None
    session: JtacSession | None = None
    spoken_text: str


def orchestrate_jtac(request: MissionControlJtacRequest) -> MissionControlJtacResult:
    target_id, target_name = _resolve_target(request)
    if target_id is None:
        text = (
            "Подходящая цель для JTAC не найдена."
            if request.language.casefold().startswith("ru")
            else "No suitable JTAC target was found."
        )
        return MissionControlJtacResult(accepted=False, spoken_text=text)

    laser_code = request.laser_code if request.method is JtacDesignationMethod.LASER else None
    session = jtac_sessions.create(
        JtacSessionCreate(
            target_id=target_id,
            method=request.method,
            laser_code=laser_code,
            requested_asset_id=request.requested_asset_id,
            smoke_color=request.smoke_color,
        ),
        language=request.language,
    )
    submit_jtac_voice(session, request.language)
    if session.state is JtacSessionState.FAILED:
        return MissionControlJtacResult(
            accepted=False,
            target_id=target_id,
            target_name=target_name,
            session=session,
            spoken_text=jtac_session_text(session, request.language),
        )

    pending = jtac_sessions.start_marking(session.session_id)
    return MissionControlJtacResult(
        accepted=True,
        target_id=target_id,
        target_name=target_name,
        session=pending,
        spoken_text=_queued_text(pending, target_name, request.language),
    )


def _resolve_target(request: MissionControlJtacRequest) -> tuple[str | None, str | None]:
    if request.target_mode is JtacTargetMode.EXPLICIT:
        return request.target_id, request.target_id
    picture = build_mission_control_picture()
    target = picture.primary_surface_threat
    if target is None:
        return None, None
    return target.unit_id, target.name


def _queued_text(session: JtacSession, target_name: str | None, language: str) -> str:
    ru = language.casefold().startswith("ru")
    target = target_name or session.target_id
    if session.method is JtacDesignationMethod.LASER:
        return (
            f"JTAC назначен на цель {target}. Код лазера {session.laser_code}. Запрос на подсветку передан."
            if ru
            else f"JTAC assigned to {target}. Laser code {session.laser_code}. Marking request sent."
        )
    color = session.smoke_color or "red"
    return (
        f"JTAC назначен на цель {target}. Запрос на маркировку дымом, цвет {color}, передан."
        if ru
        else f"JTAC assigned to {target}. {color.capitalize()} smoke marking request sent."
    )
