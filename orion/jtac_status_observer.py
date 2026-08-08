from __future__ import annotations

from uuid import UUID

from orion.jtac_runtime import JtacSession, jtac_sessions
from orion.jtac_voice import submit_jtac_voice


def observe_mission_command_status(command_id: UUID) -> JtacSession | None:
    """Reconcile and announce a JTAC session when its mission command changes state."""
    linked = jtac_sessions.find_by_command_id(command_id)
    if linked is None:
        return None
    previous_state = linked.state
    updated = jtac_sessions.reconcile(linked.session_id)
    if updated.state is not previous_state:
        submit_jtac_voice(updated, updated.language)
    return updated
