from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock

from pydantic import BaseModel, Field

from orion.coalition_radio import CoalitionRadioUnit, MissionLandmark, coalition_radio


class MissionBridgeSnapshot(BaseModel):
    session_id: str = Field(min_length=1, max_length=160)
    mission_name: str | None = Field(default=None, max_length=240)
    sequence: int = Field(ge=0)
    generated_at: datetime
    units: list[CoalitionRadioUnit] = Field(default_factory=list)
    landmarks: list[MissionLandmark] = Field(default_factory=list)


class MissionBridgeState(BaseModel):
    connected: bool = False
    session_id: str | None = None
    mission_name: str | None = None
    last_sequence: int | None = None
    last_received_at: datetime | None = None
    unit_count: int = 0
    landmark_count: int = 0


class MissionBridgeIngestResult(BaseModel):
    accepted: bool
    duplicate_or_stale: bool = False
    state: MissionBridgeState
    message: str


class MissionBridgeTelemetryStore:
    """Accepts ordered snapshots from Mission Bridge and updates live mission indexes."""

    def __init__(self) -> None:
        self._state = MissionBridgeState()
        self._lock = RLock()

    def ingest(self, snapshot: MissionBridgeSnapshot) -> MissionBridgeIngestResult:
        with self._lock:
            same_session = self._state.session_id == snapshot.session_id
            if same_session and self._state.last_sequence is not None and snapshot.sequence <= self._state.last_sequence:
                return MissionBridgeIngestResult(
                    accepted=False,
                    duplicate_or_stale=True,
                    state=self._state.model_copy(deep=True),
                    message="Snapshot sequence is duplicate or older than the current Mission Bridge state",
                )

            coalition_radio.replace(snapshot.units)
            coalition_radio.replace_landmarks(snapshot.landmarks)
            self._state = MissionBridgeState(
                connected=True,
                session_id=snapshot.session_id,
                mission_name=snapshot.mission_name,
                last_sequence=snapshot.sequence,
                last_received_at=datetime.now(UTC),
                unit_count=len(snapshot.units),
                landmark_count=len(snapshot.landmarks),
            )
            return MissionBridgeIngestResult(
                accepted=True,
                state=self._state.model_copy(deep=True),
                message="Mission Bridge snapshot accepted and live mission indexes updated",
            )

    def state(self) -> MissionBridgeState:
        with self._lock:
            return self._state.model_copy(deep=True)

    def disconnect(self, session_id: str | None = None, clear_indexes: bool = True) -> MissionBridgeState:
        with self._lock:
            if session_id is not None and self._state.session_id not in {None, session_id}:
                return self._state.model_copy(deep=True)
            if clear_indexes:
                coalition_radio.replace([])
                coalition_radio.replace_landmarks([])
            self._state = MissionBridgeState()
            return self._state.model_copy(deep=True)


mission_bridge_telemetry = MissionBridgeTelemetryStore()
