from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MissionSession(BaseModel):
    session_id: UUID = Field(default_factory=uuid4)
    mission_id: str = Field(min_length=1)
    mission_name: str | None = None
    server_name: str | None = None
    multiplayer: bool = False
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    active: bool = True


class MissionSessionManager:
    def __init__(self) -> None:
        self._lock = RLock()
        self._current: MissionSession | None = None

    def start(self, session: MissionSession) -> MissionSession:
        with self._lock:
            if self._current is not None:
                self._current.active = False
            self._current = session
            return session

    def heartbeat(self, session_id: UUID) -> MissionSession | None:
        with self._lock:
            if self._current is None or self._current.session_id != session_id:
                return None
            self._current.last_seen_at = datetime.now(UTC)
            return self._current

    def get(self) -> MissionSession | None:
        with self._lock:
            return self._current

    def end(self, session_id: UUID) -> MissionSession | None:
        with self._lock:
            if self._current is None or self._current.session_id != session_id:
                return None
            self._current.active = False
            return self._current


mission_sessions = MissionSessionManager()
