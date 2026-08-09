from __future__ import annotations

from pydantic import BaseModel, Field

from orion.airport_taxi_navigation import AirportSurfaceGraph, SurfaceNodeKind


class ParkingStand(BaseModel):
    stand_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)
    label: str | None = Field(default=None, max_length=160)
    available: bool = True
    priority: int = Field(default=100, ge=0)


class ParkingSelection(BaseModel):
    stand: ParkingStand
    requested: bool = False
    reason: str = Field(min_length=1, max_length=500)


class ParkingStandCatalog:
    """Deterministic stand registry used by Ground taxi-in planning."""

    def __init__(self, graph: AirportSurfaceGraph) -> None:
        self.graph = graph
        self._stands: dict[str, ParkingStand] = {}

    def add(self, stand: ParkingStand) -> None:
        if stand.stand_id in self._stands:
            raise ValueError(f"Duplicate parking stand {stand.stand_id}")
        node = self.graph.node(stand.node_id)
        if node.kind is not SurfaceNodeKind.PARKING:
            raise ValueError("Parking stand must reference a PARKING surface node")
        self._stands[stand.stand_id] = stand.model_copy(deep=True)

    def get_by_node(self, node_id: str) -> ParkingStand | None:
        for stand in self._stands.values():
            if stand.node_id == node_id:
                return stand.model_copy(deep=True)
        return None

    def select(self, requested_stand_id: str | None = None) -> ParkingSelection:
        if requested_stand_id is not None:
            stand = self._stands.get(requested_stand_id)
            if stand is None:
                raise ValueError("Requested parking stand is unknown")
            if not stand.available:
                raise ValueError("Requested parking stand is unavailable")
            return ParkingSelection(stand=stand, requested=True, reason="pilot-requested parking stand accepted")

        available = [stand for stand in self._stands.values() if stand.available]
        if not available:
            raise ValueError("No available parking stand is known")
        selected = min(available, key=lambda item: (item.priority, item.stand_id))
        return ParkingSelection(stand=selected, requested=False, reason="Ground selected available parking stand")
