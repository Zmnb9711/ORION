from __future__ import annotations

from enum import StrEnum
from threading import RLock

from pydantic import BaseModel, Field

from orion.dcs_capabilities import DcsRecipientType


class RadioModulation(StrEnum):
    AM = "AM"
    FM = "FM"


class CoalitionRadioUnit(BaseModel):
    unit_id: str = Field(min_length=1, max_length=160)
    callsign: str = Field(min_length=1, max_length=120)
    recipient_type: DcsRecipientType
    coalition: str = Field(min_length=1, max_length=40)
    frequency_mhz: float | None = Field(default=None, gt=0, lt=1000)
    modulation: RadioModulation | None = None
    preset: str | None = Field(default=None, max_length=40)
    available: bool = True


class RadioLookupQuery(BaseModel):
    text: str = Field(min_length=1, max_length=240)
    coalition: str | None = Field(default=None, max_length=40)
    recipient_type: DcsRecipientType | None = None


class RadioLookupResult(BaseModel):
    found: bool
    unit: CoalitionRadioUnit | None = None
    message: str


class CoalitionRadioDirectory:
    """Session-independent directory populated later by Mission Bridge telemetry."""

    def __init__(self) -> None:
        self._units: dict[str, CoalitionRadioUnit] = {}
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

    def lookup(self, query: RadioLookupQuery) -> RadioLookupResult:
        needle = query.text.casefold().strip()
        with self._lock:
            candidates = [
                unit
                for unit in self._units.values()
                if unit.available
                and (query.coalition is None or unit.coalition.casefold() == query.coalition.casefold())
                and (query.recipient_type is None or unit.recipient_type is query.recipient_type)
                and (needle in unit.callsign.casefold() or needle in unit.unit_id.casefold())
            ]
            if not candidates:
                return RadioLookupResult(found=False, message="No matching friendly unit was found in the current mission data")
            unit = sorted(candidates, key=lambda item: item.callsign)[0].model_copy(deep=True)
            if unit.frequency_mhz is None:
                return RadioLookupResult(
                    found=True,
                    unit=unit,
                    message="The unit exists, but no radio frequency is assigned in the mission data",
                )
            modulation = unit.modulation.value if unit.modulation else "unspecified modulation"
            return RadioLookupResult(
                found=True,
                unit=unit,
                message=f"{unit.callsign}: {unit.frequency_mhz:.3f} MHz {modulation}",
            )


coalition_radio = CoalitionRadioDirectory()
