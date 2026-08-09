from __future__ import annotations

from enum import StrEnum
from math import atan2, degrees

from pydantic import BaseModel, Field

from orion.airport_surface import TaxiRoute
from orion.airport_taxi_navigation import AirportSurfaceGraph, PositionMatch, SurfaceNodeKind


class TaxiGuidanceAction(StrEnum):
    CONTINUE = "continue"
    TURN_LEFT = "turn_left"
    TURN_RIGHT = "turn_right"
    HOLD_SHORT = "hold_short"
    ARRIVED = "arrived"
    POSITION_UNCERTAIN = "position_uncertain"
    OFF_ROUTE = "off_route"


class TaxiGuidanceCue(BaseModel):
    action: TaxiGuidanceAction
    text: str = Field(min_length=1, max_length=500)
    current_node_id: str | None = None
    next_node_id: str | None = None
    runway_id: str | None = None
    named_surface: str | None = None
    safety_critical: bool = False
    confidence: float = Field(ge=0, le=1)


class TaxiGuidanceEngine:
    """Deterministic turn-by-turn guidance over a canonical TaxiRoute and surface graph."""

    def __init__(self, graph: AirportSurfaceGraph) -> None:
        self.graph = graph

    def next_cue(self, route: TaxiRoute, position_match: PositionMatch) -> TaxiGuidanceCue:
        if not position_match.sufficiently_known or position_match.node_id is None:
            return TaxiGuidanceCue(
                action=TaxiGuidanceAction.POSITION_UNCERTAIN,
                text="Position confidence is insufficient for precise taxi guidance.",
                confidence=position_match.confidence,
            )

        path = self.graph.shortest_path(route.origin, route.destination)
        current = position_match.node_id
        if current == route.destination:
            destination = self.graph.node(route.destination)
            return TaxiGuidanceCue(
                action=TaxiGuidanceAction.ARRIVED,
                text=f"Arrived at {destination.label or destination.node_id}.",
                current_node_id=current,
                confidence=position_match.confidence,
            )

        if current not in path.node_ids:
            return TaxiGuidanceCue(
                action=TaxiGuidanceAction.OFF_ROUTE,
                text="Aircraft is off the active taxi route; route re-evaluation is required.",
                current_node_id=current,
                confidence=position_match.confidence,
            )

        index = path.node_ids.index(current)
        if index >= len(path.node_ids) - 1:
            return TaxiGuidanceCue(
                action=TaxiGuidanceAction.ARRIVED,
                text="Taxi destination reached.",
                current_node_id=current,
                confidence=position_match.confidence,
            )

        next_node_id = path.node_ids[index + 1]
        next_node = self.graph.node(next_node_id)
        edge = self.graph.edge(path.edge_ids[index])

        if next_node.kind in {SurfaceNodeKind.HOLDING_POINT, SurfaceNodeKind.RUNWAY_BOUNDARY} and next_node.runway_id:
            return TaxiGuidanceCue(
                action=TaxiGuidanceAction.HOLD_SHORT,
                text=f"STOP. Hold short of runway {next_node.runway_id}.",
                current_node_id=current,
                next_node_id=next_node_id,
                runway_id=next_node.runway_id,
                named_surface=edge.label,
                safety_critical=True,
                confidence=position_match.confidence,
            )

        action = self._turn_action(path.node_ids, index)
        named_surface = edge.label
        if action is TaxiGuidanceAction.TURN_LEFT:
            text = f"Turn left{self._surface_suffix(named_surface)}."
        elif action is TaxiGuidanceAction.TURN_RIGHT:
            text = f"Turn right{self._surface_suffix(named_surface)}."
        else:
            text = f"Continue{self._surface_suffix(named_surface)}."
        return TaxiGuidanceCue(
            action=action,
            text=text,
            current_node_id=current,
            next_node_id=next_node_id,
            named_surface=named_surface,
            confidence=position_match.confidence,
        )

    def answer_free_form(self, route: TaxiRoute, position_match: PositionMatch, question: str) -> TaxiGuidanceCue:
        normalized = " ".join(question.strip().lower().split())
        cue = self.next_cue(route, position_match)
        if cue.action in {
            TaxiGuidanceAction.POSITION_UNCERTAIN,
            TaxiGuidanceAction.OFF_ROUTE,
            TaxiGuidanceAction.HOLD_SHORT,
            TaxiGuidanceAction.ARRIVED,
        }:
            return cue

        if any(token in normalized for token in ("куда дальше", "куда ехать", "что дальше", "next")):
            return cue
        if any(token in normalized for token in ("направо", "right")):
            expected = cue.action is TaxiGuidanceAction.TURN_RIGHT
            return cue.model_copy(update={"text": "Yes, turn right." if expected else f"No. {cue.text}"})
        if any(token in normalized for token in ("налево", "left")):
            expected = cue.action is TaxiGuidanceAction.TURN_LEFT
            return cue.model_copy(update={"text": "Yes, turn left." if expected else f"No. {cue.text}"})
        if any(token in normalized for token in ("где останов", "hold short", "stop")):
            return cue.model_copy(update={"text": cue.text if cue.safety_critical else "No stop is required at the next route step."})
        return cue.model_copy(update={"text": f"Current taxi guidance: {cue.text}"})

    def _turn_action(self, node_ids: list[str], current_index: int) -> TaxiGuidanceAction:
        if current_index == 0 or current_index + 1 >= len(node_ids):
            return TaxiGuidanceAction.CONTINUE
        previous = self.graph.node(node_ids[current_index - 1]).position
        current = self.graph.node(node_ids[current_index]).position
        following = self.graph.node(node_ids[current_index + 1]).position
        incoming = degrees(atan2(current.z_m - previous.z_m, current.x_m - previous.x_m))
        outgoing = degrees(atan2(following.z_m - current.z_m, following.x_m - current.x_m))
        delta = (outgoing - incoming + 180.0) % 360.0 - 180.0
        if delta > 25.0:
            return TaxiGuidanceAction.TURN_LEFT
        if delta < -25.0:
            return TaxiGuidanceAction.TURN_RIGHT
        return TaxiGuidanceAction.CONTINUE

    @staticmethod
    def _surface_suffix(label: str | None) -> str:
        return f" onto {label}" if label else ""
