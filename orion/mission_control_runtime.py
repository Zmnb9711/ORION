from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from orion.tactical_situation import TacticalThreat, TacticalThreatKind, get_tactical_situation


class MissionControlReadiness(StrEnum):
    UNAVAILABLE = "unavailable"
    MONITORING = "monitoring"
    ENGAGED = "engaged"


class MissionControlPicture(BaseModel):
    readiness: MissionControlReadiness = MissionControlReadiness.UNAVAILABLE
    primary_air_threat: TacticalThreat | None = None
    primary_surface_threat: TacticalThreat | None = None
    secondary_air_threats: list[TacticalThreat] = Field(default_factory=list)
    total_threats: int = 0
    summary: str = "Tactical picture unavailable"


def build_mission_control_picture() -> MissionControlPicture:
    tactical = get_tactical_situation(limit=8)
    if not tactical.available:
        return MissionControlPicture()

    air = [item for item in tactical.priority_threats if item.kind is TacticalThreatKind.AIR]
    surface = [item for item in tactical.priority_threats if item.kind is not TacticalThreatKind.AIR]
    primary_air = air[0] if air else None
    primary_surface = surface[0] if surface else None
    readiness = MissionControlReadiness.ENGAGED if tactical.total_threats else MissionControlReadiness.MONITORING

    parts: list[str] = []
    if primary_air is not None:
        parts.append(f"primary air {primary_air.braa}")
    if primary_surface is not None:
        parts.append(
            f"primary {primary_surface.kind.value} bearing {primary_surface.bearing_deg:.0f} range {primary_surface.range_nm:.0f} nm"
        )
    summary = "; ".join(parts) if parts else "No prioritized threats"

    return MissionControlPicture(
        readiness=readiness,
        primary_air_threat=primary_air,
        primary_surface_threat=primary_surface,
        secondary_air_threats=air[1:3],
        total_threats=tactical.total_threats,
        summary=summary,
    )
