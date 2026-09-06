"""Pure, non-normative declarative ownship wording extension."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
from orion.communication_contracts import (
    CommunicationContext, CommunicationDomain, CommunicationProfileId,
    OperationalSemanticUnit, ProtectedOperationalFragment, ProtectedValueKind,
)
from orion.world_model_contracts import WorldFactAuthority

OWNSHIP_REPORT_V1 = "RECOVERY_OWNSHIP_REPORT_V1"
KEYS = ("ownship.heading_deg", "ownship.position.latitude", "ownship.position.longitude")
_DIGITS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")

@dataclass(frozen=True)
class OwnshipReportRuleset:
    """Explicit extension; not an aviation-standard assertion."""
    version: str = OWNSHIP_REPORT_V1

def render_ownship_report(
    unit: OperationalSemanticUnit, context: CommunicationContext,
) -> ProtectedOperationalFragment:
    if (
        context.profile_id is not CommunicationProfileId.ICAO
        or context.domain is not CommunicationDomain.NAVIGATION
        or context.operational_language != "en-US"
        or context.phraseology_version != OWNSHIP_REPORT_V1
        or context.phraseology_snapshot_id not in (None, OWNSHIP_REPORT_V1)
        or unit.unit_type != "navigation.ownship_report"
        or unit.semantic_meaning != "navigation.current_ownship_state"
        or unit.domain is not CommunicationDomain.NAVIGATION
        or unit.status != "known" or unit.polarity != "declarative"
        or tuple(value.key for value in unit.protected_values) != KEYS
        or len(unit.provenance) != 3
        or any(p.authority is not WorldFactAuthority.AUTHORITATIVE for p in unit.provenance)
    ):
        raise ValueError("unsupported_ownship_report")
    spoken = []
    for index, item in enumerate(unit.protected_values):
        heading = index == 0
        expected_kind = ProtectedValueKind.HEADING if heading else ProtectedValueKind.COORDINATES
        raw = item.value
        if (
            item.kind is not expected_kind or item.unit != ("deg" if heading else None)
            or isinstance(raw, bool) or not isinstance(raw, (int, float)) or not isfinite(raw)
        ):
            raise ValueError("invalid_ownship_report_value")
        limit = (360, 90, 180)[index]
        if (heading and not 0 <= raw < limit) or (not heading and abs(raw) > limit):
            raise ValueError("invalid_ownship_report_range")
        literal = format(Decimal(str(raw)), "f")
        if heading:
            whole, dot, fraction = literal.partition(".")
            literal = whole.zfill(3) + dot + fraction
        words = [_DIGITS[int(c)] if c.isdigit() else ("minus" if c == "-" else "point") for c in literal]
        spoken.append(" ".join(words))
    return ProtectedOperationalFragment(
        text=f"Current heading {spoken[0]} degrees. Latitude {spoken[1]} degrees. Longitude {spoken[2]} degrees.",
        semantic_unit=unit,
        renderer_version=f"recovery.ownship.renderer.v1/{OWNSHIP_REPORT_V1}",
    )
