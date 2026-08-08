from __future__ import annotations

from pydantic import BaseModel

from orion.aar_closure import AarClosureAssessment, ClosureBand
from orion.aar_vertical import AarVerticalAssessment, VerticalBand
from orion.mission_context import SupportAsset


class AarJoinupStability(BaseModel):
    ready_for_precontact: bool
    distance_ok: bool
    closure_ok: bool
    vertical_ok: bool
    reasons: list[str]


def evaluate_joinup_stability(
    tanker: SupportAsset,
    closure: AarClosureAssessment | None,
    vertical: AarVerticalAssessment | None,
) -> AarJoinupStability:
    """Recommend pre-contact only when range, closure and vertical state are all stable."""
    distance_ok = tanker.distance_km is not None and tanker.distance_km <= 0.926  # 0.5 NM
    closure_ok = closure is not None and closure.band in {ClosureBand.HOLD, ClosureBand.STABLE}
    vertical_ok = vertical is not None and vertical.band == VerticalBand.ALIGNED

    reasons: list[str] = []
    if not distance_ok:
        reasons.append("distance_not_final")
    if not closure_ok:
        reasons.append("closure_not_stable")
    if not vertical_ok:
        reasons.append("vertical_not_aligned")

    return AarJoinupStability(
        ready_for_precontact=distance_ok and closure_ok and vertical_ok,
        distance_ok=distance_ok,
        closure_ok=closure_ok,
        vertical_ok=vertical_ok,
        reasons=reasons,
    )
