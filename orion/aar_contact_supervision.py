from __future__ import annotations

from pydantic import BaseModel

from orion.aar_closure import AarClosureAssessment
from orion.aar_vertical import AarVerticalAssessment
from orion.mission_context import SupportAsset


class AarContactSupervision(BaseModel):
    stable: bool
    range_ok: bool
    closure_ok: bool
    vertical_ok: bool
    reasons: list[str]


# Advisory geometric limits while CONTACT has already been explicitly confirmed.
# These limits must never be used to infer physical probe/drogue or boom contact.
MAX_RANGE_KM = 0.1852  # 0.10 NM
MAX_ABS_CLOSURE_MPS = 1.5433  # 3 kt
MAX_VERTICAL_OFFSET_M = 10.0


def evaluate_contact_supervision(
    tanker: SupportAsset,
    closure: AarClosureAssessment | None,
    vertical: AarVerticalAssessment | None,
) -> AarContactSupervision:
    range_ok = tanker.distance_km is not None and tanker.distance_km <= MAX_RANGE_KM
    closure_ok = closure is not None and abs(closure.closure_mps) <= MAX_ABS_CLOSURE_MPS
    vertical_ok = vertical is not None and abs(vertical.offset_m) <= MAX_VERTICAL_OFFSET_M

    reasons: list[str] = []
    if not range_ok:
        reasons.append("contact_range_degraded")
    if not closure_ok:
        reasons.append("contact_closure_degraded")
    if not vertical_ok:
        reasons.append("contact_vertical_degraded")

    return AarContactSupervision(
        stable=range_ok and closure_ok and vertical_ok,
        range_ok=range_ok,
        closure_ok=closure_ok,
        vertical_ok=vertical_ok,
        reasons=reasons,
    )
