from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from pydantic import BaseModel, Field


REQUIRED_KEYS = (
    "tacan_power",
    "tacan_channel_tens",
    "tacan_channel_ones",
    "tacan_xy",
    "comm1_selector",
    "comm2_selector",
)
OPTIONAL_KEYS = (
    "left_ddi_brightness",
    "right_ddi_brightness",
    "mpcd_brightness",
)
ALLOWED_KEYS = set(REQUIRED_KEYS + OPTIONAL_KEYS)


class HornetArgumentMapping(BaseModel):
    version: str = "fa18c-clickable-calibrated-v1"
    validated: bool = True
    arguments: dict[str, int] = Field(default_factory=dict)
    confidence: dict[str, float] = Field(default_factory=dict)

    def complete(self) -> bool:
        return all(key in self.arguments for key in REQUIRED_KEYS)

    def dcs_command(self) -> dict[str, object]:
        return {
            "command": "set_cockpit_mapping",
            "mapping_version": self.version,
            **{f"{key}_id": value for key, value in self.arguments.items()},
        }


@dataclass
class HornetMappingRegistry:
    path: Path
    _mapping: HornetArgumentMapping | None = None

    @classmethod
    def default(cls) -> "HornetMappingRegistry":
        path = Path(os.getenv("ORION_FA18C_MAPPING_PATH", "data/fa18c_cockpit_mapping.json"))
        registry = cls(path=path)
        registry.load()
        return registry

    def load(self) -> HornetArgumentMapping | None:
        if not self.path.exists():
            self._mapping = None
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._mapping = HornetArgumentMapping.model_validate(raw)
        except Exception:
            self._mapping = None
        return self._mapping

    def current(self) -> HornetArgumentMapping | None:
        return self._mapping

    def save(self, arguments: Mapping[str, int], confidence: Mapping[str, float] | None = None) -> HornetArgumentMapping:
        cleaned = {str(key): int(value) for key, value in arguments.items() if key in ALLOWED_KEYS and isinstance(value, int)}
        if not all(key in cleaned for key in REQUIRED_KEYS):
            missing = [key for key in REQUIRED_KEYS if key not in cleaned]
            raise ValueError(f"Incomplete Hornet mapping; missing: {', '.join(missing)}")
        mapping = HornetArgumentMapping(arguments=cleaned, confidence=dict(confidence or {}))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(mapping.model_dump_json(indent=2), encoding="utf-8")
        self._mapping = mapping
        return mapping

    def clear(self) -> None:
        self._mapping = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


hornet_mapping_registry = HornetMappingRegistry.default()
