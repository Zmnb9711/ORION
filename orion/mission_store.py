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
            return snapshot

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
