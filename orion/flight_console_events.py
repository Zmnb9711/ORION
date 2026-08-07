from __future__ import annotations

from datetime import UTC, datetime
from threading import Condition, RLock
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class FlightConsoleEvent(BaseModel):
    sequence: int
    launch_id: UUID
    event_type: str
    state: dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("state", mode="before")
    @classmethod
    def serialize_state_model(cls, value: Any) -> Any:
        # Flight Console publishes Pydantic state objects, while the event
        # envelope deliberately stores an immutable JSON-ready snapshot.
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        return value


class FlightConsoleEventStream:
    def __init__(self, max_events: int = 500) -> None:
        self._events: list[FlightConsoleEvent] = []
        self._sequence = 0
        self._max_events = max_events
        self._lock = RLock()
        self._condition = Condition(self._lock)

    def publish(self, event_type: str, launch_id: UUID, state: dict[str, Any] | BaseModel) -> FlightConsoleEvent:
        with self._condition:
            self._sequence += 1
            event = FlightConsoleEvent(
                sequence=self._sequence,
                launch_id=launch_id,
                event_type=event_type,
                state=state,
            )
            self._events.append(event)
            if len(self._events) > self._max_events:
                self._events = self._events[-self._max_events :]
            self._condition.notify_all()
            return event

    def read_after(
        self,
        sequence: int = 0,
        launch_id: UUID | None = None,
        limit: int = 100,
    ) -> list[FlightConsoleEvent]:
        with self._lock:
            events = [event for event in self._events if event.sequence > sequence]
            if launch_id is not None:
                events = [event for event in events if event.launch_id == launch_id]
            return events[:limit]

    @property
    def latest_sequence(self) -> int:
        with self._lock:
            return self._sequence


flight_console_events = FlightConsoleEventStream()
