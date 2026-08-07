from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock

from pydantic import BaseModel

from orion.fa18c_cockpit_adapter import normalize_hornet_cockpit_state
from orion.fa18c_mapping_registry import HornetMappingRegistry, hornet_mapping_registry
from orion.fa18c_value_profiles import HornetValueProfileRegistry, hornet_value_profile_registry
from orion.models import TelemetryEnvelope


class HornetLiveValidationSnapshot(BaseModel):
    validated: bool = False
    consecutive_valid_samples: int = 0
    required_samples: int = 3
    mapping_version: str | None = None
    tacan_valid: bool = False
    comm1_valid: bool = False
    comm2_valid: bool = False
    last_issue: str | None = None


@dataclass
class HornetLiveValidator:
    required_samples: int = 3
    mapping_registry: HornetMappingRegistry = field(default_factory=lambda: hornet_mapping_registry)
    profile_registry: HornetValueProfileRegistry = field(default_factory=lambda: hornet_value_profile_registry)

    def __post_init__(self) -> None:
        self._consecutive = 0
        self._snapshot = HornetLiveValidationSnapshot(required_samples=self.required_samples)
        self._lock = RLock()

    def observe(self, payload: TelemetryEnvelope) -> HornetLiveValidationSnapshot:
        aircraft = payload.state.aircraft_type.strip().lower()
        if aircraft not in {"fa-18c", "fa-18c_hornet", "fa-18c lot 20", "fa-18c_hornet lot 20"}:
            return self.reset("Current aircraft is not the F/A-18C")

        mapping = self.mapping_registry.current()
        profiles = self.profile_registry.current()
        cockpit_payload = payload.state.cockpit_state
        if mapping is None or not mapping.validated or not mapping.complete():
            return self.reset("Validated cockpit mapping is missing")
        if profiles is None or profiles.mapping_version != mapping.version:
            return self.reset("Calibrated cockpit value profile is missing or outdated")
        if not isinstance(cockpit_payload, dict):
            return self.reset("Cockpit state is not present in telemetry")

        state = normalize_hornet_cockpit_state(cockpit_payload, mapping=mapping, profiles=profiles)
        if state is None:
            return self.reset("Hornet cockpit state could not be normalized")

        tacan_valid = state.tacan_enabled is not None and state.tacan_channel is not None and state.tacan_band in {"X", "Y"}
        comm1_valid = state.comm1_preset is not None
        comm2_valid = state.comm2_preset is not None
        valid = tacan_valid and comm1_valid and comm2_valid

        with self._lock:
            self._consecutive = self._consecutive + 1 if valid else 0
            validated = self._consecutive >= self.required_samples
            issue = None if valid else "TACAN/COMM semantic state is incomplete"
            self._snapshot = HornetLiveValidationSnapshot(
                validated=validated,
                consecutive_valid_samples=self._consecutive,
                required_samples=self.required_samples,
                mapping_version=mapping.version,
                tacan_valid=tacan_valid,
                comm1_valid=comm1_valid,
                comm2_valid=comm2_valid,
                last_issue=issue,
            )
            return self._snapshot

    def snapshot(self) -> HornetLiveValidationSnapshot:
        with self._lock:
            return self._snapshot.model_copy()

    def reset(self, issue: str | None = None) -> HornetLiveValidationSnapshot:
        with self._lock:
            self._consecutive = 0
            self._snapshot = HornetLiveValidationSnapshot(required_samples=self.required_samples, last_issue=issue)
            return self._snapshot


hornet_live_validator = HornetLiveValidator()
