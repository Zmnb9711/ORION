from __future__ import annotations

from enum import StrEnum
from threading import RLock
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from orion.jtac_assets import JtacAsset, select_jtac_asset
from orion.mission_bridge import MissionCommand, MissionCommandType, mission_bridge
from orion.mission_command_status import MissionCommandStatus, mission_command_statuses
from orion.mission_store import mission_store


class JtacDesignationMethod(StrEnum):
    LASER = "laser"
    SMOKE = "smoke"


class JtacSessionState(StrEnum):
    REQUESTED = "requested"
    ASSIGNED = "assigned"
    MARKING = "marking"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    FAILED = "failed"


class JtacSessionCreate(BaseModel):
    target_id: str = Field(min_length=1)
    method: JtacDesignationMethod
    laser_code: int | None = Field(default=None, ge=1111, le=1788)
    requested_asset_id: str | None = None
    smoke_color: str = "red"


class JtacSession(BaseModel):
    session_id: UUID = Field(default_factory=uuid4)
    mission_id: str | None = None
    target_id: str
    method: JtacDesignationMethod
    state: JtacSessionState = JtacSessionState.REQUESTED
    assigned_asset_id: str | None = None
    laser_code: int | None = None
    smoke_color: str | None = None
    marker_active: bool = False
    command_id: UUID | None = None
    language: str = "en"
    message: str = "JTAC support requested"


class JtacSessionStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._sessions: dict[UUID, JtacSession] = {}
        self._mission_id: str | None = None

    def create(self, payload: JtacSessionCreate, *, language: str = "en") -> JtacSession:
        if payload.method is JtacDesignationMethod.SMOKE and payload.laser_code is not None:
            raise ValueError("Laser code is only valid for laser designation")
        if payload.method is JtacDesignationMethod.LASER and payload.laser_code is None:
            raise ValueError("laser_code is required for laser designation")
        mission_id = self._current_mission_id()
        with self._lock:
            self._bind_mission(mission_id)
            session = JtacSession(
                mission_id=mission_id,
                target_id=payload.target_id,
                method=payload.method,
                laser_code=payload.laser_code if payload.method is JtacDesignationMethod.LASER else None,
                smoke_color=payload.smoke_color if payload.method is JtacDesignationMethod.SMOKE else None,
                language=language,
            )
            self._sessions[session.session_id] = session
        return self.assign(session.session_id, requested_asset_id=payload.requested_asset_id)

    def assign(self, session_id: UUID, *, requested_asset_id: str | None = None) -> JtacSession:
        self._sync_mission()
        asset = select_jtac_asset(requested_asset_id=requested_asset_id)
        if asset is None:
            return self.transition(session_id, JtacSessionState.FAILED, message="No suitable friendly JTAC/designator asset available")
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError("JTAC session not found")
            if not _supports(asset, session.method):
                return self.transition(session_id, JtacSessionState.FAILED, message="Requested JTAC asset cannot provide the selected designation method")
        return self.transition(session_id, JtacSessionState.ASSIGNED, assigned_asset_id=asset.unit_id, message=f"JTAC asset assigned: {asset.name}")

    def start_marking(self, session_id: UUID) -> JtacSession:
        self._sync_mission()
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError("JTAC session not found")
            if session.state is not JtacSessionState.ASSIGNED:
                raise ValueError("JTAC session must be assigned before marking")
            if session.command_id is not None:
                raise ValueError("JTAC marking command is already pending")
            command = MissionCommand(
                command=MissionCommandType.LASER if session.method is JtacDesignationMethod.LASER else MissionCommandType.SMOKE,
                target_unit_id=session.target_id,
                provider_unit_id=session.assigned_asset_id,
                laser_code=session.laser_code,
                smoke_color=session.smoke_color,
            )
        result = mission_bridge.send(command)
        with self._lock:
            session = self._sessions[session_id]
            session.command_id = command.command_id
            session.marker_active = False
            session.message = f"JTAC marking command queued: {result.status.value}"
            return session.model_copy(deep=True)

    def reconcile(self, session_id: UUID) -> JtacSession:
        self._sync_mission()
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError("JTAC session not found")
            command_id = session.command_id
            state = session.state
        if command_id is None:
            return self.get(session_id)  # type: ignore[return-value]
        result = mission_command_statuses.get(command_id)
        if result is None or result.status is MissionCommandStatus.QUEUED:
            return self.get(session_id)  # type: ignore[return-value]
        if result.status is MissionCommandStatus.ACCEPTED:
            if state is JtacSessionState.ASSIGNED:
                return self.transition(session_id, JtacSessionState.MARKING, marker_active=True, message=result.message or "JTAC marking confirmed by mission-side")
            return self.get(session_id)  # type: ignore[return-value]
        if result.status is MissionCommandStatus.COMPLETED:
            if state is JtacSessionState.ASSIGNED:
                self.transition(session_id, JtacSessionState.MARKING, marker_active=True, message="JTAC marking confirmed by mission-side")
            current = self.get(session_id)
            if current is not None and current.state is JtacSessionState.MARKING:
                return self.transition(session_id, JtacSessionState.COMPLETE, marker_active=False, message=result.message or "JTAC marking complete")
            return self.get(session_id)  # type: ignore[return-value]
        if result.status is MissionCommandStatus.FAILED and state not in {JtacSessionState.COMPLETE, JtacSessionState.CANCELLED, JtacSessionState.FAILED}:
            return self.transition(session_id, JtacSessionState.FAILED, marker_active=False, message=result.message or "JTAC marking failed")
        return self.get(session_id)  # type: ignore[return-value]

    def find_by_command_id(self, command_id: UUID) -> JtacSession | None:
        self._sync_mission()
        with self._lock:
            for session in self._sessions.values():
                if session.command_id == command_id:
                    return session.model_copy(deep=True)
        return None

    def get(self, session_id: UUID) -> JtacSession | None:
        self._sync_mission()
        with self._lock:
            session = self._sessions.get(session_id)
            return session.model_copy(deep=True) if session else None

    def list(self) -> list[JtacSession]:
        self._sync_mission()
        with self._lock:
            return [item.model_copy(deep=True) for item in self._sessions.values()]

    def transition(self, session_id: UUID, state: JtacSessionState, *, assigned_asset_id: str | None = None, marker_active: bool | None = None, command_id: UUID | None = None, message: str | None = None) -> JtacSession:
        self._sync_mission()
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
            self._mission_id = None

    def _sync_mission(self) -> None:
        mission_id = self._current_mission_id()
        with self._lock:
            self._bind_mission(mission_id)

    def _bind_mission(self, mission_id: str | None) -> None:
        if mission_id is None:
            return
        if self._mission_id is None:
            self._mission_id = mission_id
            return
        if mission_id != self._mission_id:
            self._sessions.clear()
            self._mission_id = mission_id

    @staticmethod
    def _current_mission_id() -> str | None:
        snapshot = mission_store.get()
        return snapshot.mission_id if snapshot is not None else None


def _supports(asset: JtacAsset, method: JtacDesignationMethod) -> bool:
    return asset.supports_laser if method is JtacDesignationMethod.LASER else asset.supports_smoke


def _validate_transition(current: JtacSessionState, target: JtacSessionState) -> None:
    allowed = {
        JtacSessionState.REQUESTED: {JtacSessionState.ASSIGNED, JtacSessionState.CANCELLED, JtacSessionState.FAILED},
        JtacSessionState.ASSIGNED: {JtacSessionState.MARKING, JtacSessionState.CANCELLED, JtacSessionState.FAILED},
        JtacSessionState.MARKING: {JtacSessionState.COMPLETE, JtacSessionState.CANCELLED, JtacSessionState.FAILED},
        JtacSessionState.COMPLETE: set(),
        JtacSessionState.CANCELLED: set(),
        JtacSessionState.FAILED: set(),
    }
    if target not in allowed[current]:
        raise ValueError(f"Invalid JTAC transition: {current.value} -> {target.value}")


jtac_sessions = JtacSessionStore()
