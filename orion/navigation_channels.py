from __future__ import annotations

from enum import StrEnum
from threading import RLock

from pydantic import BaseModel, Field


class NavigationChannelSystem(StrEnum):
    RADIO = "radio"
    RSBN = "rsbn"
    ADF = "adf"


class NavigationChannelOwnerType(StrEnum):
    UNIT = "unit"
    AIRFIELD = "airfield"
    BEACON = "beacon"


class NavigationPresetChannel(BaseModel):
    preset_id: str = Field(min_length=1, max_length=160)
    system: NavigationChannelSystem
    owner_type: NavigationChannelOwnerType
    owner_id: str = Field(min_length=1, max_length=160)
    owner_name: str = Field(min_length=1, max_length=160)
    channel: str = Field(min_length=1, max_length=40)
    frequency_mhz: float | None = Field(default=None, gt=0, lt=2000)
    frequency_khz: float | None = Field(default=None, gt=0, lt=5000)
    modulation: str | None = Field(default=None, max_length=20)
    callsign: str | None = Field(default=None, max_length=120)
    purpose: str | None = Field(default=None, max_length=160)
    aircraft_type: str | None = Field(default=None, max_length=160)
    available: bool = True


class NavigationChannelQuery(BaseModel):
    text: str = Field(min_length=1, max_length=240)
    system: NavigationChannelSystem | None = None
    owner_type: NavigationChannelOwnerType | None = None
    aircraft_type: str | None = Field(default=None, max_length=160)
    available_only: bool = True


class NavigationChannelLookupResult(BaseModel):
    found: bool
    channels: list[NavigationPresetChannel] = Field(default_factory=list)
    message: str


class NavigationChannelDirectory:
    """Mission-supplied preset radio, RSBN and ADF channels; never invents missing values."""

    def __init__(self) -> None:
        self._items: dict[str, NavigationPresetChannel] = {}
        self._lock = RLock()

    def replace(self, items: list[NavigationPresetChannel]) -> list[NavigationPresetChannel]:
        with self._lock:
            self._items = {item.preset_id: item.model_copy(deep=True) for item in items}
            return self.list()

    def upsert(self, item: NavigationPresetChannel) -> NavigationPresetChannel:
        with self._lock:
            self._items[item.preset_id] = item.model_copy(deep=True)
            return item.model_copy(deep=True)

    def remove(self, preset_id: str) -> bool:
        with self._lock:
            return self._items.pop(preset_id, None) is not None

    def list(self) -> list[NavigationPresetChannel]:
        with self._lock:
            return [item.model_copy(deep=True) for item in sorted(
                self._items.values(), key=lambda item: (item.system.value, item.owner_name, item.channel)
            )]

    def lookup(self, query: NavigationChannelQuery) -> NavigationChannelLookupResult:
        needle = query.text.casefold().strip()
        with self._lock:
            matches = [
                item.model_copy(deep=True)
                for item in self._items.values()
                if (not query.available_only or item.available)
                and (query.system is None or item.system is query.system)
                and (query.owner_type is None or item.owner_type is query.owner_type)
                and (query.aircraft_type is None or item.aircraft_type is None or item.aircraft_type.casefold() == query.aircraft_type.casefold())
                and any(
                    needle in value.casefold()
                    for value in (
                        item.owner_id,
                        item.owner_name,
                        item.callsign or "",
                        item.purpose or "",
                        item.channel,
                    )
                )
            ]
        matches.sort(key=lambda item: (item.system.value, item.owner_name, item.channel))
        if not matches:
            return NavigationChannelLookupResult(
                found=False,
                message="No matching preset channel was found in the current mission data",
            )
        summary = "; ".join(_describe(item) for item in matches)
        return NavigationChannelLookupResult(found=True, channels=matches, message=summary)


def _describe(item: NavigationPresetChannel) -> str:
    frequency = ""
    if item.frequency_mhz is not None:
        frequency = f", {item.frequency_mhz:.3f} MHz"
    elif item.frequency_khz is not None:
        frequency = f", {item.frequency_khz:g} kHz"
    modulation = f" {item.modulation}" if item.modulation else ""
    purpose = f", {item.purpose}" if item.purpose else ""
    return f"{item.owner_name}: {item.system.value.upper()} channel {item.channel}{frequency}{modulation}{purpose}"


navigation_channels = NavigationChannelDirectory()
