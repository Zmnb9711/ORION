from __future__ import annotations

from enum import StrEnum
from threading import RLock
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from orion.jtac_assets import JtacAsset, select_jtac_asset
from orion.mission_bridge import MissionCommand, MissionCommandType, mission_bridge


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
    smoke_color: str = "red"


class JtacSession(BaseModel):
    session_id: UUID = Field(default_factory=uuid4)
    target_id: str
    method: JtacDesignationMethod
    state: JtacSessionState = JtacSessionState.REQUESTED
    assigned_asset_id: str | None = None
    laser_code: int | None = None
    smoke_color: str | None = None
    marker_active: bool = False
    command_id: UUID | None = None
    message: str = "JTAC support requested"


class JtacSessionStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._sessions: dict[UUID, JtacSession] = {}

    def create(self, payload: JtacSessionCreate) -> JtacSession:
        if payload.method is JtacDesignationMethod.SMOKE and payload.laser_code is not None:
            raise ValueError("Laser code is only valid for laser designation")
        if payload.method is JtacDesignationMethod.LASER and payload.laser_code is None:
            raise ValueError("laser_code is required for laser designation")
        session = JtacSession(
            target_id=payload.target_id,
            method=payload.method,
            laser_code=payload.laser_code if payload.method is JtacDesignationMethod.LASER else None,
            smoke_color=payload.smoke_color if payload.method is JtacDesignationMethod.SMOKE else None,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return self.assign(session.session_id, requested_asset_id=payload.requested_asset_id)

    def assign(self, session_id: UUID, *, requested_asset_id: str | None = None) -> JtacSession:
        asset = select_jtac_asset(requested_asset_id=requested_asset_id)
        if asset is None:
            return self.transition(session_id, JtacSessionState.FAILED, message="No suitable friendly JTAC/designator asset available")
        with self._lock:
            session = self._sessions[session_id]
            if not _supports(asset, session.method):
                return self.transition(session_id, JtacSessionState.FAILED, message="Requested JTAC asset cannot provide the selected designation method")
        return self.transition(session_id, JtacSessionState.ASSIGNED, assigned_asset_id=asset.unit_id, message=f"JTAC asset assigned: {asset.name}")

    def start_marking(self, session_id: UUID) -> JtacSession:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError("JTAC session not found")
            if session.state is not JtacSessionState.ASSIGNED:
                raise ValueError("JTAC session must be assigned before marking")
            command = MissionCommand(
                command=MissionCommandType.LASER if session.method is JtacDesignationMethod.LASER else MissionCommandType.SMOKE,
                target_unit_id=session.target_id,
                provider_unit_id=session.assigned_asset_id,
                laser_code=session.laser_code,
                smoke_color=session.smoke_color,
            )
        result = mission_bridge.send(command)
        return self.transition(
            session_id,
            JtacSessionState.MARKING,
            marker_active=True,
            command_id=command.command_id,
            message=f"JTAC marking command queued: {result.status.value}",
        )

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
        command_id: UUID | None = None,
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
            if command_id is not None:
                session.command_id = command_id
            if message is not None:
                session.message = message
            return session.model_copy(deep=True)

    def reset(self) -> None:
        with self._lock:
            self._sessions.clear()


def _supports(asset: JtacAsset, method: JtacDesignationMethod) -> bool:
    return asset.supports_laser if method is JtacDesignationMethod.LASER else asset.supports_smoke


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
