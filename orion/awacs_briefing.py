from __future__ import annotations

from pydantic import BaseModel, Field

from orion.awacs_prioritization import prioritize_air_contacts
from orion.tactical_situation import TacticalThreat


class AwacsBriefingPlan(BaseModel):
    primary: TacticalThreat | None = None
    secondary: list[TacticalThreat] = Field(default_factory=list)


def build_awacs_briefing(threats: list[TacticalThreat], max_secondary: int = 2) -> AwacsBriefingPlan:
    """Return one primary air contact and at most two secondary contacts."""
    decision = prioritize_air_contacts(threats, limit=max(1, max_secondary + 1))
    if decision.primary is None:
        return AwacsBriefingPlan()
    return AwacsBriefingPlan(
        primary=decision.primary,
        secondary=decision.ordered_contacts[1 : 1 + max(0, max_secondary)],
    )
