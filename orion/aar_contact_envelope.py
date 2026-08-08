from __future__ import annotations

from pydantic import BaseModel

from orion.aar_closure import AarClosureAssessment
from orion.aar_vertical import AarVerticalAssessment
from orion.mission_context import SupportAsset


class AarContactEnvelope(BaseModel):
    within_envelope: bool
    distance_ok: bool
    closure_ok: bool
    vertical_ok: bool
    reasons: list[str]


MAX_DISTANCE_KM = 0.463  # 0.25 NM
MAX_CLOSURE_MPS = 2.5722  # 5 kt
MAX_VERTICAL_OFFSET_M = 15.0


def evaluate_contact_envelope(
    tanker: SupportAsset,
    closure: AarClosureAssessment | None,
    vertical: AarVerticalAssessment | None,
) -> AarContactEnvelope:
    """Evaluate the tighter envelope used after an explicit pre-contact transition.

    This is advisory. It must not be used to infer actual probe/drogue or boom contact.
    """
    distance_ok = tanker.distance_km is not None and tanker.distance_km <= MAX_DISTANCE_KM
    closure_ok = closure is not None and -2.0 <= closure.closure_mps <= MAX_CLOSURE_MPS
    vertical_ok = vertical is not None and abs(vertical.offset_m) <= MAX_VERTICAL_OFFSET_M

    reasons: list[str] = []
    if not distance_ok:
        reasons.append("distance_outside_contact_envelope")
    if not closure_ok:
        reasons.append("closure_outside_contact_envelope")
    if not vertical_ok:
        reasons.append("vertical_outside_contact_envelope")

    return AarContactEnvelope(
        within_envelope=distance_ok and closure_ok and vertical_ok,
        distance_ok=distance_ok,
        closure_ok=closure_ok,
        vertical_ok=vertical_ok,
        reasons=reasons,
    )
