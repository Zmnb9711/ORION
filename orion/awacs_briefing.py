from __future__ import annotations

from pydantic import BaseModel, Field

from orion.awacs_prioritization import prioritize_air_contacts
from orion.tactical_kinematics import RangeTrend, ThreatAspect
from orion.tactical_situation import TacticalThreat
from orion.threats import ThreatLevel


class AwacsBriefingPlan(BaseModel):
    primary: TacticalThreat | None = None
    secondary: list[TacticalThreat] = Field(default_factory=list)


def build_awacs_briefing(threats: list[TacticalThreat], max_secondary: int = 2) -> AwacsBriefingPlan:
    """Return one primary air contact and only tactically useful secondary contacts."""
    decision = prioritize_air_contacts(threats, limit=max(1, max_secondary + 3))
    if decision.primary is None:
        return AwacsBriefingPlan()

    secondary = [
        item
        for item in decision.ordered_contacts[1:]
        if _worth_secondary_callout(item, decision.primary)
    ][: max(0, max_secondary)]
    return AwacsBriefingPlan(primary=decision.primary, secondary=secondary)


def _worth_secondary_callout(threat: TacticalThreat, primary: TacticalThreat) -> bool:
    if threat.level is ThreatLevel.CRITICAL:
        return True
    if threat.level is not ThreatLevel.HIGH:
        return False
    if threat.kinematics.aspect is ThreatAspect.HOT and threat.kinematics.range_trend is RangeTrend.CLOSING:
        return True
    # Keep a near-peer threat in the briefing, but suppress contacts that are
    # tactically much less important than the primary.
    return threat.tactical_priority >= max(60.0, primary.tactical_priority - 15.0)
