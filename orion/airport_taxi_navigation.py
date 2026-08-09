from __future__ import annotations

from enum import StrEnum
from heapq import heappop, heappush
from math import hypot
from uuid import UUID

from pydantic import BaseModel, Field

from orion.airport_surface import SurfaceSegment, TaxiRoute
from orion.atc_operations import FreshnessClass


class SurfaceNodeKind(StrEnum):
    PARKING = "parking"
    APRON = "apron"
    INTERSECTION = "intersection"
    HOLDING_POINT = "holding_point"
    RUNWAY_BOUNDARY = "runway_boundary"
    RUNWAY_EXIT = "runway_exit"


class SurfaceEdgeKind(StrEnum):
    TAXIWAY = "taxiway"
    APRON = "apron"
    RUNWAY_CROSSING = "runway_crossing"


class SurfacePosition(BaseModel):
    x_m: float
    z_m: float


class SurfaceNode(BaseModel):
    node_id: str = Field(min_length=1, max_length=160)
    kind: SurfaceNodeKind
    position: SurfacePosition
    label: str | None = Field(default=None, max_length=160)
    runway_id: str | None = Field(default=None, max_length=80)


class SurfaceEdge(BaseModel):
    edge_id: str = Field(min_length=1, max_length=160)
    start_node_id: str = Field(min_length=1, max_length=160)
    end_node_id: str = Field(min_length=1, max_length=160)
    kind: SurfaceEdgeKind = SurfaceEdgeKind.TAXIWAY
    label: str | None = Field(default=None, max_length=160)
    length_m: float = Field(gt=0)
    bidirectional: bool = True
    runway_id: str | None = Field(default=None, max_length=80)
    blocked: bool = False


class PositionMatch(BaseModel):
    node_id: str | None = None
    distance_m: float | None = None
    confidence: float = Field(ge=0, le=1)
    freshness: FreshnessClass = FreshnessClass.UNKNOWN
    sufficiently_known: bool = False
    reason: str = Field(min_length=1, max_length=500)


class PlannedTaxiPath(BaseModel):
    node_ids: list[str]
    edge_ids: list[str]
    total_distance_m: float = Field(ge=0)


class AirportSurfaceGraph:
    """Versioned, deterministic airport surface topology used by Ground navigation."""

    def __init__(self, *, facility_id: str, version: int = 1) -> None:
        if not facility_id:
            raise ValueError("facility_id is required")
        if version < 1:
            raise ValueError("surface graph version must be positive")
        self.facility_id = facility_id
        self.version = version
        self._nodes: dict[str, SurfaceNode] = {}
        self._edges: dict[str, SurfaceEdge] = {}
        self._adjacency: dict[str, list[tuple[str, str, float]]] = {}

    def add_node(self, node: SurfaceNode) -> None:
        if node.node_id in self._nodes:
            raise ValueError(f"Duplicate surface node {node.node_id}")
        self._nodes[node.node_id] = node.model_copy(deep=True)
        self._adjacency[node.node_id] = []

    def add_edge(self, edge: SurfaceEdge) -> None:
        if edge.edge_id in self._edges:
            raise ValueError(f"Duplicate surface edge {edge.edge_id}")
        if edge.start_node_id not in self._nodes or edge.end_node_id not in self._nodes:
            raise ValueError("Surface edge endpoints must exist before the edge is added")
        self._edges[edge.edge_id] = edge.model_copy(deep=True)
        self._adjacency[edge.start_node_id].append((edge.end_node_id, edge.edge_id, edge.length_m))
        if edge.bidirectional:
            self._adjacency[edge.end_node_id].append((edge.start_node_id, edge.edge_id, edge.length_m))

    def node(self, node_id: str) -> SurfaceNode:
        item = self._nodes.get(node_id)
        if item is None:
            raise KeyError(f"Surface node {node_id} not found")
        return item.model_copy(deep=True)

    def edge(self, edge_id: str) -> SurfaceEdge:
        item = self._edges.get(edge_id)
        if item is None:
            raise KeyError(f"Surface edge {edge_id} not found")
        return item.model_copy(deep=True)

    def match_position(
        self,
        position: SurfacePosition,
        *,
        freshness: FreshnessClass,
        max_match_distance_m: float = 35.0,
    ) -> PositionMatch:
        if not self._nodes:
            return PositionMatch(
                confidence=0,
                freshness=freshness,
                sufficiently_known=False,
                reason="surface topology has no known nodes",
            )
        nearest = min(
            self._nodes.values(),
            key=lambda node: hypot(position.x_m - node.position.x_m, position.z_m - node.position.z_m),
        )
        distance = hypot(position.x_m - nearest.position.x_m, position.z_m - nearest.position.z_m)
        freshness_ok = freshness in {FreshnessClass.FRESH, FreshnessClass.AGING}
        within = distance <= max_match_distance_m
        confidence = max(0.0, min(1.0, 1.0 - distance / max_match_distance_m)) if max_match_distance_m > 0 else 0.0
        sufficiently_known = freshness_ok and within
        reason = (
            "position matched to known surface node"
            if sufficiently_known
            else "position/topology evidence is insufficient for precise taxi guidance"
        )
        return PositionMatch(
            node_id=nearest.node_id if within else None,
            distance_m=distance,
            confidence=confidence,
            freshness=freshness,
            sufficiently_known=sufficiently_known,
            reason=reason,
        )

    def shortest_path(self, origin_node_id: str, destination_node_id: str) -> PlannedTaxiPath:
        self.node(origin_node_id)
        self.node(destination_node_id)
        queue: list[tuple[float, str]] = [(0.0, origin_node_id)]
        distances = {origin_node_id: 0.0}
        previous: dict[str, tuple[str, str]] = {}

        while queue:
            distance, node_id = heappop(queue)
            if distance != distances.get(node_id):
                continue
            if node_id == destination_node_id:
                break
            for next_node, edge_id, edge_length in sorted(self._adjacency[node_id], key=lambda item: (item[0], item[1])):
                edge = self._edges[edge_id]
                if edge.blocked:
                    continue
                candidate = distance + edge_length
                if candidate < distances.get(next_node, float("inf")):
                    distances[next_node] = candidate
                    previous[next_node] = (node_id, edge_id)
                    heappush(queue, (candidate, next_node))

        if destination_node_id not in distances:
            raise ValueError("No usable taxi route exists between requested surface nodes")

        nodes = [destination_node_id]
        edges: list[str] = []
        cursor = destination_node_id
        while cursor != origin_node_id:
            previous_node, edge_id = previous[cursor]
            nodes.append(previous_node)
            edges.append(edge_id)
            cursor = previous_node
        nodes.reverse()
        edges.reverse()
        return PlannedTaxiPath(node_ids=nodes, edge_ids=edges, total_distance_m=distances[destination_node_id])

    def build_taxi_route(
        self,
        *,
        session_id: UUID,
        origin_node_id: str,
        destination_node_id: str,
        reason: str,
        revision: int = 1,
    ) -> TaxiRoute:
        path = self.shortest_path(origin_node_id, destination_node_id)
        runway_crossings: list[str] = []
        hold_short_resources: list[str] = []
        segments: list[SurfaceSegment] = []

        for edge_id in path.edge_ids:
            edge = self._edges[edge_id]
            segments.append(SurfaceSegment(segment_id=edge.edge_id, kind=edge.kind.value, label=edge.label))
            if edge.kind is SurfaceEdgeKind.RUNWAY_CROSSING and edge.runway_id:
                runway_crossings.append(edge.runway_id)

        for node_id in path.node_ids:
            node = self._nodes[node_id]
            if node.kind in {SurfaceNodeKind.HOLDING_POINT, SurfaceNodeKind.RUNWAY_BOUNDARY} and node.runway_id:
                if node.runway_id not in hold_short_resources:
                    hold_short_resources.append(node.runway_id)

        return TaxiRoute(
            session_id=session_id,
            facility_id=self.facility_id,
            origin=origin_node_id,
            destination=destination_node_id,
            segments=segments,
            runway_crossings=list(dict.fromkeys(runway_crossings)),
            hold_short_resources=hold_short_resources,
            topology_version=self.version,
            revision=revision,
            reason=reason,
        )
