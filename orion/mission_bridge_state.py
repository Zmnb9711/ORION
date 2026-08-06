from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock

from pydantic import BaseModel, Field

from orion.coalition_radio import CoalitionRadioUnit, MissionLandmark, coalition_radio


class MissionBridgeSnapshot(BaseModel):
    session_id: str = Field(min_length=1, max_length=160)
    sequence: int = Field(ge=0)
    mission_name: str | None = Field(default=None, max_length=240)
    player_callsign: str | None = Field(default=None, max_length=120)
    units: list[CoalitionRadioUnit] = Field(default_factory=list)
    landmarks: list[MissionLandmark] = Field(default_factory=list)
    generated_at: datetime | None = None


class MissionBridgeStatus(BaseModel):
    connected: bool = False
    session_id: str | None = None
    mission_name: str | None = None
    player_callsign: str | None = None
    last_sequence: int | None = None
    unit_count: int = 0
    landmark_count: int = 0
    last_received_at: datetime | None = None
    message: str = "No Mission Bridge snapshot has been received"


class MissionBridgeApplyResult(BaseModel):
    accepted: bool
    status: MissionBridgeStatus
    message: str


class MissionBridgeState:
    """Applies ordered mission snapshots and rejects stale bridge updates."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._status = MissionBridgeStatus()

    def apply(self, snapshot: MissionBridgeSnapshot) -> MissionBridgeApplyResult:
        with self._lock:
            current = self._status
            same_session = current.session_id == snapshot.session_id
            if same_session and current.last_sequence is not None and snapshot.sequence <= current.last_sequence:
                return MissionBridgeApplyResult(
                    accepted=False,
                    status=current.model_copy(deep=True),
                    message="Snapshot rejected because its sequence is not newer than the active mission state",
                )

            coalition_radio.replace(snapshot.units)
            coalition_radio.replace_landmarks(snapshot.landmarks)
            received_at = datetime.now(UTC)
            self._status = MissionBridgeStatus(
                connected=True,
                session_id=snapshot.session_id,
                mission_name=snapshot.mission_name,
                player_callsign=snapshot.player_callsign,
                last_sequence=snapshot.sequence,
                unit_count=len(snapshot.units),
                landmark_count=len(snapshot.landmarks),
                last_received_at=received_at,
                message="Mission Bridge data is current",
            )
            return MissionBridgeApplyResult(
                accepted=True,
                status=self._status.model_copy(deep=True),
                message="Mission snapshot applied",
            )

    def status(self) -> MissionBridgeStatus:
        with self._lock:
            return self._status.model_copy(deep=True)

    def disconnect(self) -> MissionBridgeStatus:
        with self._lock:
            self._status.connected = False
            self._status.message = "Mission Bridge disconnected"
            return self._status.model_copy(deep=True)

    def reset(self) -> MissionBridgeStatus:
        with self._lock:
            coalition_radio.replace([])
            coalition_radio.replace_landmarks([])
            self._status = MissionBridgeStatus()
            return self._status.model_copy(deep=True)


mission_bridge_state = MissionBridgeState()
