from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from orion.aar_events import AarEvent, AarEventResult, AarEventSource, AarEventType, aar_events


class AarRawSource(StrEnum):
    EXPORT_LUA = "export_lua"
    MISSION_PACK = "mission_pack"
    TEST = "test"


class AarRawObservation(BaseModel):
    """Aircraft-agnostic AAR facts extracted from DCS-facing adapters.

    Aircraft-specific cockpit arguments or mission callbacks must be converted into
    these semantic booleans outside the AAR core. The AAR state machine therefore
    never depends on F/A-18C, F-16C, boom, or probe/drogue implementation details.
    """

    observation_id: str = Field(min_length=1)
    source: AarRawSource
    tanker_unit_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    pre_contact_cleared: bool | None = None
    physical_contact: bool | None = None
    fuel_transfer_active: bool | None = None
    refueling_complete: bool | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class AarAdapterResult(BaseModel):
    observation_id: str
    generated_events: list[AarEvent] = Field(default_factory=list)
    event_results: list[AarEventResult] = Field(default_factory=list)

    @property
    def all_accepted(self) -> bool:
        return all(result.accepted for result in self.event_results)


class _ObservationState(BaseModel):
    pre_contact_cleared: bool | None = None
    physical_contact: bool | None = None
    fuel_transfer_active: bool | None = None
    refueling_complete: bool | None = None


class AarDcsEventAdapter:
    """Converts raw DCS/Mission Pack AAR facts into normalized edge events."""

    def __init__(self) -> None:
        self._last_by_stream: dict[tuple[AarRawSource, str | None], _ObservationState] = {}
        self._seen_observations: set[str] = set()

    def reset(self) -> None:
        self._last_by_stream.clear()
        self._seen_observations.clear()

    def ingest(self, observation: AarRawObservation) -> AarAdapterResult:
        if observation.observation_id in self._seen_observations:
            return AarAdapterResult(observation_id=observation.observation_id)

        key = (observation.source, observation.tanker_unit_id)
        previous = self._last_by_stream.get(key, _ObservationState())
        generated = self._detect_edges(observation, previous)
        results = [aar_events.ingest(event) for event in generated]

        # Raw observations describe DCS state even when the AAR session rejects an
        # event. Keep the detector baseline current to avoid replaying stale edges.
        self._last_by_stream[key] = _merge_state(previous, observation)
        self._seen_observations.add(observation.observation_id)
        return AarAdapterResult(
            observation_id=observation.observation_id,
            generated_events=generated,
            event_results=results,
        )

    def _detect_edges(self, current: AarRawObservation, previous: _ObservationState) -> list[AarEvent]:
        events: list[AarEvent] = []

        # Order is deliberate. A single DCS frame may establish CONTACT and fuel
        # flow together, so CONTACT must reach the normalized processor first.
        if _rising(previous.pre_contact_cleared, current.pre_contact_cleared):
            events.append(self._event(current, AarEventType.PRE_CONTACT))

        if _rising(previous.physical_contact, current.physical_contact):
            events.append(self._event(current, AarEventType.CONTACT))
        elif previous.physical_contact is True and current.physical_contact is False:
            events.append(self._event(current, AarEventType.DISCONNECT))

        if _rising(previous.fuel_transfer_active, current.fuel_transfer_active):
            events.append(self._event(current, AarEventType.REFUELING))

        if _rising(previous.refueling_complete, current.refueling_complete):
            events.append(self._event(current, AarEventType.COMPLETE))

        return events

    @staticmethod
    def _event(observation: AarRawObservation, event_type: AarEventType) -> AarEvent:
        source = AarEventSource.MISSION_PACK if observation.source is AarRawSource.MISSION_PACK else AarEventSource.DCS
        if observation.source is AarRawSource.TEST:
            source = AarEventSource.TEST
        return AarEvent(
            event_id=f"{observation.observation_id}:{event_type.value}",
            event_type=event_type,
            source=source,
            tanker_unit_id=observation.tanker_unit_id,
            timestamp=observation.timestamp,
            metadata={
                **observation.metadata,
                "raw_source": observation.source.value,
                "observation_id": observation.observation_id,
            },
        )


def _rising(previous: bool | None, current: bool | None) -> bool:
    return current is True and previous is not True


def _merge_state(previous: _ObservationState, current: AarRawObservation) -> _ObservationState:
    return _ObservationState(
        pre_contact_cleared=current.pre_contact_cleared if current.pre_contact_cleared is not None else previous.pre_contact_cleared,
        physical_contact=current.physical_contact if current.physical_contact is not None else previous.physical_contact,
        fuel_transfer_active=current.fuel_transfer_active if current.fuel_transfer_active is not None else previous.fuel_transfer_active,
        refueling_complete=current.refueling_complete if current.refueling_complete is not None else previous.refueling_complete,
    )


aar_dcs_adapter = AarDcsEventAdapter()
