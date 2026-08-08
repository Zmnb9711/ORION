from __future__ import annotations

from enum import StrEnum
from threading import RLock
from uuid import UUID

from pydantic import BaseModel, Field

from orion.jtac_assets import available_jtac_assets
from orion.jtac_runtime import JtacDesignationMethod, JtacSession, JtacSessionCreate, JtacSessionState, jtac_sessions
from orion.jtac_voice import jtac_session_text, submit_jtac_voice
from orion.mission_control_runtime import build_mission_control_picture
from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommandCreate, voice_commands


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
    max_attempts: int = Field(default=3, ge=1, le=5)


class MissionControlJtacResult(BaseModel):
    accepted: bool
    target_id: str | None = None
    target_name: str | None = None
    session: JtacSession | None = None
    spoken_text: str
    attempt: int = 1
    reassigned: bool = False


class _FallbackContext(BaseModel):
    target_name: str | None = None
    used_asset_ids: list[str] = Field(default_factory=list)
    attempt: int = 1
    max_attempts: int = 3


_fallback_lock = RLock()
_fallback_by_session: dict[UUID, _FallbackContext] = {}


def orchestrate_jtac(request: MissionControlJtacRequest) -> MissionControlJtacResult:
    target_id, target_name = _resolve_target(request)
    if target_id is None:
        text = "Подходящая цель для JTAC не найдена." if request.language.casefold().startswith("ru") else "No suitable JTAC target was found."
        return MissionControlJtacResult(accepted=False, spoken_text=text)

    requested_asset_id = request.requested_asset_id or _next_asset_id(request.method, excluded=set())
    return _start_attempt(
        target_id=target_id,
        target_name=target_name,
        method=request.method,
        laser_code=request.laser_code,
        smoke_color=request.smoke_color,
        requested_asset_id=requested_asset_id,
        language=request.language,
        attempt=1,
        max_attempts=request.max_attempts,
        used_asset_ids=set(),
        reassigned=False,
    )


def retry_failed_jtac(session: JtacSession) -> MissionControlJtacResult | None:
    """Retry a failed Mission Control JTAC task with the next compatible asset."""
    with _fallback_lock:
        context = _fallback_by_session.pop(session.session_id, None)
    if context is None:
        return None

    used = set(context.used_asset_ids)
    if session.assigned_asset_id:
        used.add(session.assigned_asset_id)
    next_attempt = context.attempt + 1
    if next_attempt > context.max_attempts:
        result = MissionControlJtacResult(
            accepted=False,
            target_id=session.target_id,
            target_name=context.target_name,
            session=session,
            spoken_text=_exhausted_text(session, context.target_name, session.language),
            attempt=context.attempt,
        )
        _submit_orchestration_voice(result.spoken_text, session)
        return result

    next_asset_id = _next_asset_id(session.method, excluded=used)
    if next_asset_id is None:
        result = MissionControlJtacResult(
            accepted=False,
            target_id=session.target_id,
            target_name=context.target_name,
            session=session,
            spoken_text=_exhausted_text(session, context.target_name, session.language),
            attempt=context.attempt,
        )
        _submit_orchestration_voice(result.spoken_text, session)
        return result

    return _start_attempt(
        target_id=session.target_id,
        target_name=context.target_name,
        method=session.method,
        laser_code=session.laser_code,
        smoke_color=session.smoke_color or "red",
        requested_asset_id=next_asset_id,
        language=session.language,
        attempt=next_attempt,
        max_attempts=context.max_attempts,
        used_asset_ids=used,
        reassigned=True,
    )


def _start_attempt(
    *,
    target_id: str,
    target_name: str | None,
    method: JtacDesignationMethod,
    laser_code: int | None,
    smoke_color: str,
    requested_asset_id: str | None,
    language: str,
    attempt: int,
    max_attempts: int,
    used_asset_ids: set[str],
    reassigned: bool,
) -> MissionControlJtacResult:
    code = laser_code if method is JtacDesignationMethod.LASER else None
    session = jtac_sessions.create(
        JtacSessionCreate(
            target_id=target_id,
            method=method,
            laser_code=code,
            requested_asset_id=requested_asset_id,
            smoke_color=smoke_color,
        ),
        language=language,
    )
    if session.assigned_asset_id:
        used_asset_ids.add(session.assigned_asset_id)

    if session.state is JtacSessionState.FAILED:
        return MissionControlJtacResult(
            accepted=False,
            target_id=target_id,
            target_name=target_name,
            session=session,
            spoken_text=jtac_session_text(session, language),
            attempt=attempt,
            reassigned=reassigned,
        )

    pending = jtac_sessions.start_marking(session.session_id)
    with _fallback_lock:
        _fallback_by_session[pending.session_id] = _FallbackContext(
            target_name=target_name,
            used_asset_ids=sorted(used_asset_ids),
            attempt=attempt,
            max_attempts=max_attempts,
        )

    text = _reassigned_text(pending, target_name, language, attempt) if reassigned else _queued_text(pending, target_name, language)
    if reassigned:
        _submit_orchestration_voice(text, pending)
    else:
        submit_jtac_voice(session, language)
    return MissionControlJtacResult(
        accepted=True,
        target_id=target_id,
        target_name=target_name,
        session=pending,
        spoken_text=text,
        attempt=attempt,
        reassigned=reassigned,
    )


def _next_asset_id(method: JtacDesignationMethod, *, excluded: set[str]) -> str | None:
    assets = available_jtac_assets()
    assets.sort(key=lambda item: (not item.explicit_fac_role, item.category.value, item.name.casefold()))
    for asset in assets:
        if asset.unit_id in excluded:
            continue
        if method is JtacDesignationMethod.LASER and asset.supports_laser:
            return asset.unit_id
        if method is JtacDesignationMethod.SMOKE and asset.supports_smoke:
            return asset.unit_id
    return None


def _resolve_target(request: MissionControlJtacRequest) -> tuple[str | None, str | None]:
    if request.target_mode is JtacTargetMode.EXPLICIT:
        return request.target_id, request.target_id
    picture = build_mission_control_picture()
    target = picture.primary_surface_threat
    if target is None:
        return None, None
    return target.unit_id, target.name


def _submit_orchestration_voice(text: str, session: JtacSession) -> None:
    voice_commands.submit(
        VoiceCommandCreate(
            transcript=text,
            intent="mission_control_jtac_orchestration",
            agent=VoiceAgent.JTAC,
            priority=CommandPriority.HIGH,
            context={
                "session_id": str(session.session_id),
                "target_id": session.target_id,
                "assigned_asset_id": session.assigned_asset_id,
                "method": session.method.value,
                "laser_code": session.laser_code,
            },
        )
    )


def _queued_text(session: JtacSession, target_name: str | None, language: str) -> str:
    ru = language.casefold().startswith("ru")
    target = target_name or session.target_id
    if session.method is JtacDesignationMethod.LASER:
        return f"JTAC назначен на цель {target}. Код лазера {session.laser_code}. Запрос на подсветку передан." if ru else f"JTAC assigned to {target}. Laser code {session.laser_code}. Marking request sent."
    color = session.smoke_color or "red"
    return f"JTAC назначен на цель {target}. Запрос на маркировку дымом, цвет {color}, передан." if ru else f"JTAC assigned to {target}. {color.capitalize()} smoke marking request sent."


def _reassigned_text(session: JtacSession, target_name: str | None, language: str, attempt: int) -> str:
    ru = language.casefold().startswith("ru")
    target = target_name or session.target_id
    if session.method is JtacDesignationMethod.LASER:
        return f"Предыдущий целеуказатель недоступен. JTAC переназначен на цель {target}, попытка {attempt}. Код лазера {session.laser_code}." if ru else f"Previous designator unavailable. JTAC reassigned to {target}, attempt {attempt}. Laser code {session.laser_code}."
    return f"Предыдущий целеуказатель недоступен. JTAC переназначен на цель {target}, попытка {attempt}." if ru else f"Previous designator unavailable. JTAC reassigned to {target}, attempt {attempt}."


def _exhausted_text(session: JtacSession, target_name: str | None, language: str) -> str:
    target = target_name or session.target_id
    if language.casefold().startswith("ru"):
        return f"JTAC не смог выполнить задачу по цели {target}. Доступных резервных целеуказателей нет."
    return f"JTAC could not complete the task on {target}. No backup designators are available."
