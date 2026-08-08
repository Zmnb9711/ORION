from __future__ import annotations

from threading import RLock
from uuid import UUID

from orion.jtac_runtime import JtacSessionState, jtac_sessions
from orion.mission import MissionSnapshot
from orion.mission_control_jtac import JtacTargetMode, MissionControlJtacRequest, MissionControlJtacResult, orchestrate_jtac
from orion.mission_control_jtac_cancel import cancel_jtac
from orion.mission_control_runtime import build_mission_control_picture


_lock = RLock()
_pending_retask: dict[UUID, MissionControlJtacRequest] = {}


def observe_snapshot_for_jtac_retask(snapshot: MissionSnapshot) -> list[UUID]:
    """Schedule retask for active JTAC sessions whose target disappeared or died."""
    alive_ids = {unit.unit_id for unit in snapshot.units if unit.alive}
    scheduled: list[UUID] = []
    for session in jtac_sessions.list():
        if session.state not in {JtacSessionState.ASSIGNED, JtacSessionState.MARKING}:
            continue
        if session.target_id in alive_ids:
            continue

        picture = build_mission_control_picture()
        replacement = picture.primary_surface_threat
        if replacement is None or replacement.unit_id == session.target_id:
            continue

        cancelled = cancel_jtac(session.session_id)
        if not cancelled.accepted or cancelled.cancel_command_id is None:
            continue
        request = MissionControlJtacRequest(
            target_mode=JtacTargetMode.EXPLICIT,
            target_id=replacement.unit_id,
            method=session.method,
            laser_code=session.laser_code,
            smoke_color=session.smoke_color or "red",
            language=session.language,
        )
        with _lock:
            _pending_retask[cancelled.cancel_command_id] = request
        scheduled.append(cancelled.cancel_command_id)
    return scheduled


def complete_pending_retask(cancel_command_id: UUID) -> MissionControlJtacResult | None:
    with _lock:
        request = _pending_retask.pop(cancel_command_id, None)
    if request is None:
        return None
    return orchestrate_jtac(request)
