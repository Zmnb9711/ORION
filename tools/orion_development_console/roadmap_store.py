from __future__ import annotations

from pathlib import Path

from tools.orion_development_console.memory_store import ImmutableRecordStore
from tools.orion_development_console.roadmap_models import RoadmapSnapshot


class RoadmapSnapshotStore(ImmutableRecordStore[RoadmapSnapshot]):
    def __init__(self, console_root: Path) -> None:
        super().__init__(
            console_root / "roadmap" / "snapshots",
            RoadmapSnapshot,
            "snapshot_id",
        )
