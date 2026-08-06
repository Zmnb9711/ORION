from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock

from pydantic import BaseModel, Field

from orion.coalition_radio import CoalitionRadioUnit, MissionLandmark, coalition_radio


DEFAULT_STALE_AFTER_SECONDS = 10.0


class MissionBridgeSnapshot(BaseModel):
    session_id: str = Field(min_length=1, max_length=160)
    mission_name: str | None = Field(default=None, max_length=240)
    player_callsign: str | None = Field(default=None, max_length=120)
    sequence: int = Field(ge=0)
    generated_at: datetime
    units: list[CoalitionRadioUnit] = Field(default_factory=list)
    landmarks: list[MissionLandmark] = Field(default_factory=list)


class MissionBridgeHeartbeat(BaseModel):
    session_id: str = Field(min_length=1, max_length=160)
    sequence: int = Field(ge=0)
    generated_at: datetime


class MissionBridgeDelta(BaseModel):
    session_id: str = Field(min_length=1, max_length=160)
    sequence: int = Field(ge=0)
    generated_at: datetime
    mission_name: str | None = Field(default=None, max_length=240)
    player_callsign: str | None = Field(default=None, max_length=120)
    upsert_units: list[CoalitionRadioUnit] = Field(default_factory=list)
    remove_unit_ids: list[str] = Field(default_factory=list)
    upsert_landmarks: list[MissionLandmark] = Field(default_factory=list)
    remove_landmark_ids: list[str] = Field(default_factory=list)


class MissionBridgeState(BaseModel):
    connected: bool = False
    stale: bool = False
    session_id: str | None = None
    mission_name: str | None = None
    player_callsign: str | None = None
    last_sequence: int | None = None
    last_received_at: datetime | None = None
    age_seconds: float | None = None
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS
    unit_count: int = 0
    landmark_count: int = 0


class MissionBridgeIngestResult(BaseModel):
    accepted: bool
    duplicate_or_stale: bool = False
    state: MissionBridgeState
    message: str


class MissionBridgeTelemetryStore:
    """Accepts ordered snapshots, deltas and heartbeats from Mission Bridge."""

    def __init__(self) -> None:
        self._state = MissionBridgeState()
        self._lock = RLock()

    def _is_newer(self, session_id: str, sequence: int) -> bool:
        same_session = self._state.session_id == session_id
        return not (
            same_session
            and self._state.last_sequence is not None
            and sequence <= self._state.last_sequence
        )

    def _rejected(self) -> MissionBridgeIngestResult:
        return MissionBridgeIngestResult(
            accepted=False,
            duplicate_or_stale=True,
            state=self._live_state(),
            message="Mission Bridge sequence is duplicate or older than the current state",
        )

    def _live_state(self) -> MissionBridgeState:
        state = self._state.model_copy(deep=True)
        if state.last_received_at is None:
            return state
        age = max(0.0, (datetime.now(UTC) - state.last_received_at).total_seconds())
        state.age_seconds = round(age, 3)
        state.stale = age > state.stale_after_seconds
        state.connected = not state.stale
        return state

    def _commit(
        self,
        *,
        session_id: str,
        sequence: int,
        mission_name: str | None,
        player_callsign: str | None,
    ) -> MissionBridgeState:
        self._state = MissionBridgeState(
            connected=True,
            stale=False,
            session_id=session_id,
            mission_name=mission_name,
            player_callsign=player_callsign,
            last_sequence=sequence,
            last_received_at=datetime.now(UTC),
            age_seconds=0.0,
            stale_after_seconds=self._state.stale_after_seconds,
            unit_count=len(coalition_radio.list()),
            landmark_count=len(coalition_radio.list_landmarks()),
        )
        return self._state.model_copy(deep=True)

    def ingest(self, snapshot: MissionBridgeSnapshot) -> MissionBridgeIngestResult:
        with self._lock:
            if not self._is_newer(snapshot.session_id, snapshot.sequence):
                return self._rejected()
            coalition_radio.replace(snapshot.units)
            coalition_radio.replace_landmarks(snapshot.landmarks)
            state = self._commit(
                session_id=snapshot.session_id,
                sequence=snapshot.sequence,
                mission_name=snapshot.mission_name,
                player_callsign=snapshot.player_callsign,
            )
            return MissionBridgeIngestResult(
                accepted=True,
                state=state,
                message="Mission Bridge snapshot accepted and live mission indexes replaced",
            )

    def apply_delta(self, delta: MissionBridgeDelta) -> MissionBridgeIngestResult:
        with self._lock:
            if not self._is_newer(delta.session_id, delta.sequence):
                return self._rejected()
            if self._state.session_id not in {None, delta.session_id}:
                return MissionBridgeIngestResult(
                    accepted=False,
                    state=self._live_state(),
                    message="A delta cannot start a different mission session; send a full snapshot first",
                )

            units = {item.unit_id: item for item in coalition_radio.list()}
            for unit_id in delta.remove_unit_ids:
                units.pop(unit_id, None)
            for unit in delta.upsert_units:
                units[unit.unit_id] = unit

            landmarks = {item.landmark_id: item for item in coalition_radio.list_landmarks()}
            for landmark_id in delta.remove_landmark_ids:
                landmarks.pop(landmark_id, None)
            for landmark in delta.upsert_landmarks:
                landmarks[landmark.landmark_id] = landmark

            coalition_radio.replace(list(units.values()))
            coalition_radio.replace_landmarks(list(landmarks.values()))
            state = self._commit(
                session_id=delta.session_id,
                sequence=delta.sequence,
                mission_name=delta.mission_name or self._state.mission_name,
                player_callsign=delta.player_callsign or self._state.player_callsign,
            )
            return MissionBridgeIngestResult(
                accepted=True,
                state=state,
                message="Mission Bridge delta accepted and live mission indexes updated",
            )

    def heartbeat(self, heartbeat: MissionBridgeHeartbeat) -> MissionBridgeIngestResult:
        with self._lock:
            if self._state.session_id != heartbeat.session_id:
                return MissionBridgeIngestResult(
                    accepted=False,
                    state=self._live_state(),
                    message="Heartbeat session does not match the active mission",
                )
            if not self._is_newer(heartbeat.session_id, heartbeat.sequence):
                return self._rejected()
            state = self._commit(
                session_id=heartbeat.session_id,
                sequence=heartbeat.sequence,
                mission_name=self._state.mission_name,
                player_callsign=self._state.player_callsign,
            )
            return MissionBridgeIngestResult(
                accepted=True,
                state=state,
                message="Mission Bridge heartbeat accepted",
            )

    def state(self) -> MissionBridgeState:
        with self._lock:
            return self._live_state()

    def configure_stale_timeout(self, seconds: float) -> MissionBridgeState:
        if seconds <= 0:
            raise ValueError("Stale timeout must be greater than zero")
        with self._lock:
            self._state.stale_after_seconds = seconds
            return self._live_state()

    def disconnect(self, session_id: str | None = None, clear_indexes: bool = True) -> MissionBridgeState:
        with self._lock:
            if session_id is not None and self._state.session_id not in {None, session_id}:
                return self._live_state()
            if clear_indexes:
                coalition_radio.replace([])
                coalition_radio.replace_landmarks([])
            stale_after = self._state.stale_after_seconds
            self._state = MissionBridgeState(stale_after_seconds=stale_after)
            return self._state.model_copy(deep=True)


mission_bridge_telemetry = MissionBridgeTelemetryStore()
