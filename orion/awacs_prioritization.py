from __future__ import annotations

from pydantic import BaseModel, Field

from orion.tactical_situation import TacticalThreat, TacticalThreatKind


class AwacsPriorityDecision(BaseModel):
    primary: TacticalThreat | None = None
    ordered_contacts: list[TacticalThreat] = Field(default_factory=list)


def prioritize_air_contacts(threats: list[TacticalThreat], limit: int = 3) -> AwacsPriorityDecision:
    """Rank air contacts for AWACS presentation without changing threat severity.

    Tactical priority already incorporates aspect and range trend. Existing threat
    score is the first tiebreaker, then closer range for stable deterministic output.
    """
    air = [item for item in threats if item.kind is TacticalThreatKind.AIR]
    air.sort(
        key=lambda item: (
            item.tactical_priority,
            item.score,
            -item.range_nm,
        ),
        reverse=True,
    )
    ordered = air[: max(1, limit)] if air else []
    return AwacsPriorityDecision(primary=ordered[0] if ordered else None, ordered_contacts=ordered)
