from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError


SemanticValue = int | str | bool


class ControlValueProfile(BaseModel):
    control: str
    argument_id: int
    detents: list[float] = Field(default_factory=list)
    semantic_values: list[SemanticValue] = Field(default_factory=list)
    tolerance: float = Field(default=0.03, gt=0, le=0.25)

    def nearest_index(self, value: float | None) -> int | None:
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not self.detents:
            return None
        numeric = float(value)
        distances = [abs(numeric - detent) for detent in self.detents]
        index = min(range(len(distances)), key=distances.__getitem__)
        return index if distances[index] <= self.tolerance else None

    def semantic(self, value: float | None) -> SemanticValue | None:
        index = self.nearest_index(value)
        if index is None or index >= len(self.semantic_values):
            return None
        return self.semantic_values[index]


class HornetValueProfileSet(BaseModel):
    version: str = "fa18c-value-profile-v2"
    mapping_version: str
    controls: dict[str, ControlValueProfile] = Field(default_factory=dict)

    def control(self, name: str) -> ControlValueProfile | None:
        return self.controls.get(name)


@dataclass
class HornetValueProfileRegistry:
    path: Path
    _profiles: HornetValueProfileSet | None = None

    @classmethod
    def default(cls) -> "HornetValueProfileRegistry":
        path = Path(os.getenv("ORION_FA18C_VALUE_PROFILE_PATH", "data/fa18c_value_profiles.json"))
        registry = cls(path=path)
        registry.load()
        return registry

    def load(self) -> HornetValueProfileSet | None:
        if not self.path.exists():
            self._profiles = None
            return None
        try:
            self._profiles = HornetValueProfileSet.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError, json.JSONDecodeError):
            self._profiles = None
        return self._profiles

    def current(self) -> HornetValueProfileSet | None:
        return self._profiles

    def save(self, profiles: HornetValueProfileSet) -> HornetValueProfileSet:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(profiles.model_dump_json(indent=2), encoding="utf-8")
        self._profiles = profiles
        return profiles

    def clear(self) -> None:
        self._profiles = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def calibrated_detents(transitions: list[tuple[float | None, float]], *, epsilon: float = 0.005) -> list[float]:
    return sorted(calibrated_sequence(transitions, epsilon=epsilon))


def calibrated_sequence(transitions: list[tuple[float | None, float]], *, epsilon: float = 0.005) -> list[float]:
    """Return unique observed values in first-seen order.

    Sequential calibration instructions can therefore attach explicit semantic
    labels without assuming that DCS raw values increase with the selector.
    """
    values: list[float] = []
    for previous, current in transitions:
        for value in (previous, current):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            numeric = float(value)
            if all(abs(numeric - known) > epsilon for known in values):
                values.append(numeric)
    return values


hornet_value_profile_registry = HornetValueProfileRegistry.default()
