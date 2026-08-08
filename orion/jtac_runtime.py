from __future__ import annotations

from enum import StrEnum
from threading import RLock
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class JtacDesignationMethod(StrEnum):
    LASER = "laser"
    SMOKE = "smoke"


class JtacSessionState(StrEnum):
    REQUESTED = "requested"
    ASSIGNED = "assigned"
    MARKING = "marking"
    COMPLETE = "complete"
    FAILED = "failed"


class JtacSessionCreate(BaseModel):
    target_id: str = Field(min_length=1)
    method: JtacDesignationMethod
    laser_code: int | None = Field(default=None, ge=1111, le=1788)
    requested_asset_id: str | None = None


class JtacSession(BaseModel):
    session_id: UUID = Field(default_factory=uuid4)
    target_id: str
    method: JtacDesignationMethod
    state: JtacSessionState = JtacSessionState.REQUESTED
    assigned_asset_id: str | None = None
    laser_code: int | None = None
    marker_active: bool = False
    message: str = "JTAC support requested"


class JtacSessionStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._sessions: dict[UUID, JtacSession] = {}

    def create(self, payload: JtacSessionCreate) -> JtacSession:
        if payload.method is JtacDesignationMethod.SMOKE and payload.laser_code is not None:
            raise ValueError("Laser code is only valid for laser designation")
        session = JtacSession(
            target_id=payload.target_id,
            method=payload.method,
            laser_code=payload.laser_code if payload.method is JtacDesignationMethod.LASER else None,
            assigned_asset_id=payload.requested_asset_id,
        )
        with self._lock:
            self._sessions[session.session_id] = session
            return session.model_copy(deep=True)

    def get(self, session_id: UUID) -> JtacSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            return session.model_copy(deep=True) if session else None

    def list(self) -> list[JtacSession]:
        with self._lock:
            return [item.model_copy(deep=True) for item in self._sessions.values()]

    def transition(
        self,
        session_id: UUID,
        state: JtacSessionState,
        *,
        assigned_asset_id: str | None = None,
        marker_active: bool | None = None,
        message: str | None = None,
    ) -> JtacSession:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError("JTAC session not found")
            _validate_transition(session.state, state)
            session.state = state
            if assigned_asset_id is not None:
                session.assigned_asset_id = assigned_asset_id
            if marker_active is not None:
                session.marker_active = marker_active
            if message is not None:
                session.message = message
            return session.model_copy(deep=True)

    def reset(self) -> None:
        with self._lock:
            self._sessions.clear()


def _validate_transition(current: JtacSessionState, target: JtacSessionState) -> None:
    allowed = {
        JtacSessionState.REQUESTED: {JtacSessionState.ASSIGNED, JtacSessionState.FAILED},
        JtacSessionState.ASSIGNED: {JtacSessionState.MARKING, JtacSessionState.FAILED},
        JtacSessionState.MARKING: {JtacSessionState.COMPLETE, JtacSessionState.FAILED},
        JtacSessionState.COMPLETE: set(),
        JtacSessionState.FAILED: set(),
    }
    if target not in allowed[current]:
        raise ValueError(f"Invalid JTAC transition: {current.value} -> {target.value}")


jtac_sessions = JtacSessionStore()
