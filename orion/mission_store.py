from __future__ import annotations

from threading import RLock

from orion.mission import Coalition, MissionSnapshot, MissionUnit


class MissionStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._snapshot: MissionSnapshot | None = None

    def replace(self, snapshot: MissionSnapshot) -> MissionSnapshot:
        with self._lock:
            self._snapshot = snapshot
        self._notify_jtac_target_changes(snapshot)
        self._notify_proactive_mission_control(snapshot)
        self._notify_coordination_mission_control(snapshot)
        return snapshot

    @staticmethod
    def _notify_jtac_target_changes(snapshot: MissionSnapshot) -> None:
        # Lazy import avoids coupling the core mission store to Mission Control at import time.
        try:
            from orion.mission_control_jtac_retask import observe_snapshot_for_jtac_retask
        except ImportError:
            return
        observe_snapshot_for_jtac_retask(snapshot)

    @staticmethod
    def _notify_proactive_mission_control(snapshot: MissionSnapshot) -> None:
        # Keep proactive supervision optional at import time and downstream from snapshot storage.
        try:
            from orion.mission_control_proactive import observe_snapshot_for_proactive_mission_control
        except ImportError:
            return
        observe_snapshot_for_proactive_mission_control(snapshot)

    @staticmethod
    def _notify_coordination_mission_control(snapshot: MissionSnapshot) -> None:
        # Multi-threat coordination is another optional post-store observer.
        try:
            from orion.mission_control_coordination_runtime import observe_snapshot_for_coordination_mission_control
        except ImportError:
            return
        observe_snapshot_for_coordination_mission_control(snapshot)

    def get(self) -> MissionSnapshot | None:
        with self._lock:
            return self._snapshot

    def units(self, coalition: Coalition | None = None, alive_only: bool = True) -> list[MissionUnit]:
        with self._lock:
            if self._snapshot is None:
                return []
            units = self._snapshot.units
            if coalition is not None:
                units = [unit for unit in units if unit.coalition == coalition]
            if alive_only:
                units = [unit for unit in units if unit.alive]
            return list(units)


mission_store = MissionStore()
