from __future__ import annotations

from uuid import UUID

from orion.jtac_runtime import JtacSession, JtacSessionState, jtac_sessions
from orion.jtac_voice import submit_jtac_voice
from orion.mission_control_jtac import retry_failed_jtac


def observe_mission_command_status(command_id: UUID) -> JtacSession | None:
    """Reconcile JTAC state and let Mission Control recover failed designators."""
    linked = jtac_sessions.find_by_command_id(command_id)
    if linked is None:
        return None
    previous_state = linked.state
    updated = jtac_sessions.reconcile(linked.session_id)
    if updated.state is previous_state:
        return updated

    if updated.state is JtacSessionState.FAILED:
        retry = retry_failed_jtac(updated)
        if retry is not None:
            return retry.session

    submit_jtac_voice(updated, updated.language)
    return updated
