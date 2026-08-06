from __future__ import annotations

from enum import StrEnum
from math import hypot
from threading import RLock

from pydantic import BaseModel, Field

from orion.dcs_capabilities import DcsRecipientType


class RadioModulation(StrEnum):
    AM = "AM"
    FM = "FM"


class MissionPoint(BaseModel):
    x_m: float
    z_m: float


class MissionLandmark(BaseModel):
    landmark_id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=160)
    point: MissionPoint
    aliases: list[str] = Field(default_factory=list)


class CoalitionRadioUnit(BaseModel):
    unit_id: str = Field(min_length=1, max_length=160)
    callsign: str = Field(min_length=1, max_length=120)
    recipient_type: DcsRecipientType
    unit_type: str | None = Field(default=None, max_length=160)
    coalition: str = Field(min_length=1, max_length=40)
    frequency_mhz: float | None = Field(default=None, gt=0, lt=1000)
    modulation: RadioModulation | None = None
    preset: str | None = Field(default=None, max_length=40)
    point: MissionPoint | None = None
    available: bool = True

    @property
    def spoken_type(self) -> str:
        """Use the concrete DCS type when available, otherwise the broad recipient class."""
        return self.unit_type or self.recipient_type.value


class RadioLookupQuery(BaseModel):
    text: str = Field(min_length=1, max_length=240)
    coalition: str | None = Field(default=None, max_length=40)
    recipient_type: DcsRecipientType | None = None


class CallsignLookupQuery(BaseModel):
    text: str | None = Field(default=None, max_length=240)
    coalition: str | None = Field(default=None, max_length=40)
    recipient_type: DcsRecipientType | None = None
    available_only: bool = True


class NearbyCallsignQuery(BaseModel):
    landmark: str = Field(min_length=1, max_length=160)
    radius_km: float = Field(default=50.0, gt=0, le=1000)
    coalition: str | None = Field(default=None, max_length=40)
    recipient_type: DcsRecipientType | None = None
    available_only: bool = True


class RadioLookupResult(BaseModel):
    found: bool
    unit: CoalitionRadioUnit | None = None
    message: str


class CallsignLookupResult(BaseModel):
    found: bool
    units: list[CoalitionRadioUnit] = Field(default_factory=list)
    message: str


class NearbyCallsignItem(BaseModel):
    unit: CoalitionRadioUnit
    distance_km: float


class NearbyCallsignResult(BaseModel):
    found: bool
    landmark: MissionLandmark | None = None
    units: list[NearbyCallsignItem] = Field(default_factory=list)
    message: str


class CoalitionRadioDirectory:
    """Directory populated by mission or bridge telemetry; never invents missing data."""

    def __init__(self) -> None:
        self._units: dict[str, CoalitionRadioUnit] = {}
        self._landmarks: dict[str, MissionLandmark] = {}
        self._lock = RLock()

    def replace(self, units: list[CoalitionRadioUnit]) -> list[CoalitionRadioUnit]:
        with self._lock:
            self._units = {unit.unit_id: unit.model_copy(deep=True) for unit in units}
            return self.list()

    def upsert(self, unit: CoalitionRadioUnit) -> CoalitionRadioUnit:
        with self._lock:
            self._units[unit.unit_id] = unit.model_copy(deep=True)
            return unit.model_copy(deep=True)

    def list(self) -> list[CoalitionRadioUnit]:
        with self._lock:
            return [item.model_copy(deep=True) for item in sorted(self._units.values(), key=lambda item: item.callsign)]

    def replace_landmarks(self, landmarks: list[MissionLandmark]) -> list[MissionLandmark]:
        with self._lock:
            self._landmarks = {item.landmark_id: item.model_copy(deep=True) for item in landmarks}
            return self.list_landmarks()

    def upsert_landmark(self, landmark: MissionLandmark) -> MissionLandmark:
        with self._lock:
            self._landmarks[landmark.landmark_id] = landmark.model_copy(deep=True)
            return landmark.model_copy(deep=True)

    def list_landmarks(self) -> list[MissionLandmark]:
        with self._lock:
            return [item.model_copy(deep=True) for item in sorted(self._landmarks.values(), key=lambda item: item.name)]

    def _filter(self, *, text: str | None, coalition: str | None, recipient_type: DcsRecipientType | None, available_only: bool) -> list[CoalitionRadioUnit]:
        needle = text.casefold().strip() if text else None
        return [
            unit
            for unit in self._units.values()
            if (not available_only or unit.available)
            and (coalition is None or unit.coalition.casefold() == coalition.casefold())
            and (recipient_type is None or unit.recipient_type is recipient_type)
            and (
                needle is None
                or needle in unit.callsign.casefold()
                or needle in unit.unit_id.casefold()
                or (unit.unit_type is not None and needle in unit.unit_type.casefold())
            )
        ]

    def _find_landmark(self, text: str) -> MissionLandmark | None:
        needle = text.casefold().strip()
        exact: list[MissionLandmark] = []
        partial: list[MissionLandmark] = []
        for landmark in self._landmarks.values():
            names = [landmark.name, landmark.landmark_id, *landmark.aliases]
            folded = [name.casefold() for name in names]
            if needle in folded:
                exact.append(landmark)
            elif any(needle in name or name in needle for name in folded):
                partial.append(landmark)
        matches = exact or partial
        return sorted(matches, key=lambda item: item.name)[0] if matches else None

    def lookup(self, query: RadioLookupQuery) -> RadioLookupResult:
        with self._lock:
            candidates = self._filter(
                text=query.text,
                coalition=query.coalition,
                recipient_type=query.recipient_type,
                available_only=True,
            )
            if not candidates:
                return RadioLookupResult(found=False, message="No matching friendly unit was found in the current mission data")
            unit = sorted(candidates, key=lambda item: item.callsign)[0].model_copy(deep=True)
            if unit.frequency_mhz is None:
                return RadioLookupResult(
                    found=True,
                    unit=unit,
                    message=f"{unit.callsign}, {unit.spoken_type}: no radio frequency is assigned in the mission data",
                )
            modulation = unit.modulation.value if unit.modulation else "unspecified modulation"
            return RadioLookupResult(
                found=True,
                unit=unit,
                message=f"{unit.callsign}, {unit.spoken_type}: {unit.frequency_mhz:.3f} MHz {modulation}",
            )

    def lookup_callsigns(self, query: CallsignLookupQuery) -> CallsignLookupResult:
        with self._lock:
            units = sorted(
                self._filter(
                    text=query.text,
                    coalition=query.coalition,
                    recipient_type=query.recipient_type,
                    available_only=query.available_only,
                ),
                key=lambda item: item.callsign,
            )
            copies = [unit.model_copy(deep=True) for unit in units]
            if not copies:
                return CallsignLookupResult(found=False, message="No matching friendly callsigns were found in the current mission data")
            names = ", ".join(f"{unit.callsign} ({unit.spoken_type})" for unit in copies)
            return CallsignLookupResult(found=True, units=copies, message=f"Available callsigns: {names}")

    def lookup_near_landmark(self, query: NearbyCallsignQuery) -> NearbyCallsignResult:
        with self._lock:
            landmark = self._find_landmark(query.landmark)
            if landmark is None:
                return NearbyCallsignResult(
                    found=False,
                    message="The requested landmark was not found in the current mission data",
                )
            candidates = self._filter(
                text=None,
                coalition=query.coalition,
                recipient_type=query.recipient_type,
                available_only=query.available_only,
            )
            nearby: list[NearbyCallsignItem] = []
            for unit in candidates:
                if unit.point is None:
                    continue
                distance_km = hypot(
                    unit.point.x_m - landmark.point.x_m,
                    unit.point.z_m - landmark.point.z_m,
                ) / 1000.0
                if distance_km <= query.radius_km:
                    nearby.append(
                        NearbyCallsignItem(
                            unit=unit.model_copy(deep=True),
                            distance_km=round(distance_km, 1),
                        )
                    )
            nearby.sort(key=lambda item: (item.distance_km, item.unit.callsign))
            if not nearby:
                return NearbyCallsignResult(
                    found=False,
                    landmark=landmark.model_copy(deep=True),
                    message=f"No matching friendly units were found within {query.radius_km:g} km of {landmark.name}",
                )
            summary = ", ".join(
                f"{item.unit.callsign}, {item.unit.spoken_type} ({item.distance_km:g} km)"
                for item in nearby
            )
            return NearbyCallsignResult(
                found=True,
                landmark=landmark.model_copy(deep=True),
                units=nearby,
                message=f"Friendly units near {landmark.name}: {summary}",
            )


coalition_radio = CoalitionRadioDirectory()
