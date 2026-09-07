"""Narrow, non-normative ownship state report; never a heading instruction."""

from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from uuid import UUID

from orion.communication_contracts import (
    CommunicationContext, CommunicationDomain, CommunicationPriority,
    CommunicationProfileId, OperationalSemanticUnit, ProtectedOperationalFragment,
    ProtectedProvenance, ProtectedValue, ProtectedValueKind,
)
from orion.interaction_contracts import CapabilityId, ContextReference, SemanticFact, SemanticFactKind, SemanticResponse
from orion.semantic_value_binding import authoritative_fact_matches_tool_result, tool_result_values
from orion.tool_gateway import OwnshipOutput
from orion.tool_gateway_contracts import ToolResult, ToolResultStatus, ToolReceiptStatus
from orion.world_model_contracts import WorldFactAuthority, WorldFactSource, WorldFactStatus
from orion.ownship_phraseology import KEYS


def ownship_semantics_from_tool_result(
    tool: ToolResult, identity: UUID, *, now: datetime,
) -> SemanticResponse:
    """Project ONLY three named authoritative scalars; never stringify tool data.

    Other typed snapshot fields may exist, but have no path to this projection.
    Validate the registered output first, then retain exact uncoerced scalar
    values through the existing binding helper. No provider output is repaired.
    """
    if (
        tool.status is not ToolResultStatus.COMPLETED or tool.data is None
        or tool.tool_name != "orion.world.ownship.get" or tool.tool_version != "1.0"
        or tool.output_schema != OwnshipOutput.schema_identity
        or tool.capability != "world.ownship.read"
        or tool.receipt.status is not ToolReceiptStatus.COMPLETED
        or not tool.receipt.handler_started
        or tool.receipt.call_id != tool.call_id
        or tool.receipt.tool_name != tool.tool_name
        or tool.receipt.tool_version != tool.tool_version
        or tool.receipt.interaction_id != str(identity)
        or tool.provenance is None
    ):
        raise ValueError("ownship_tool_evidence")
    snapshot = OwnshipOutput.model_validate(tool.data.root).snapshot
    for fact, key, unit in (
        (snapshot.heading_deg, "ownship.heading_deg", "deg"),
        (snapshot.position, "ownship.position", None),
    ):
        if (
            fact.key != key or fact.unit != unit
            or fact.status is not WorldFactStatus.KNOWN
            or fact.authority is not WorldFactAuthority.AUTHORITATIVE
            or fact.source is not WorldFactSource.DCS_EXPORT
            or fact.value is None or fact.age_seconds is None
            or fact.generation is None or fact.generation not in tool.provenance.generations
            or fact.age_seconds + (now - tool.receipt.completed_at).total_seconds() > 5.0
        ):
            raise ValueError("ownship_fact_evidence")
    projected = tool_result_values(tool)
    facts = []
    for key in KEYS:
        matches = [leaf for leaf in projected if leaf.key == key]
        if len(matches) != 1:
            raise ValueError("ownship_missing_or_duplicate_fact")
        leaf = matches[0]
        if isinstance(leaf.value, bool) or not isinstance(leaf.value, (int, float)):
            raise ValueError("ownship_numeric_value")
        facts.append(SemanticFact(
            key=key, value=leaf.value, unit=leaf.unit,
            kind=SemanticFactKind.AUTHORITATIVE,
            source=ContextReference(context_type="tool_result", reference_id=tool.call_id),
        ))
    response = SemanticResponse(
        interaction_id=identity, capability=CapabilityId("world.ownship.read"),
        authoritative_facts=tuple(facts),
    )
    # Reuse the strict downstream contract, including exact binding, signs,
    # range, units, single generation and freshness. This call emits no text.
    map_ownship_report(response, (tool,), identity, now=now)
    return response


def map_ownship_report(
    response: SemanticResponse,
    retained: tuple[ToolResult, ...],
    identity: UUID,
    *,
    now: datetime | None = None,
) -> OperationalSemanticUnit:
    now = now or datetime.now(UTC)
    facts = {fact.key: fact for fact in response.authoritative_facts}
    if (
        response.interaction_id != identity or response.capability != "world.ownship.read"
        or len(response.authoritative_facts) != 3
        or set(facts) != set(KEYS) or response.derived_results
        or response.unavailable_inputs or response.verbatim_text
    ):
        raise ValueError("ownship_semantic_shape")
    values: list[ProtectedValue] = []
    provenance: list[ProtectedProvenance] = []
    for key in KEYS:
        fact = facts[key]
        source = fact.source
        matches = [item for item in retained if source is not None and item.call_id == source.reference_id]
        if source is None or source.context_type != "tool_result" or len(matches) != 1:
            raise ValueError("ownship_source_binding")
        tool = matches[0]
        if (
            tool.status is not ToolResultStatus.COMPLETED
            or tool.capability != "world.ownship.read"
            or tool.receipt.interaction_id != str(identity)
            or not authoritative_fact_matches_tool_result(fact, tool)
            or tool.provenance is None
        ):
            raise ValueError("ownship_value_binding")
        age = tool.provenance.max_age_seconds
        elapsed = (now - tool.receipt.completed_at).total_seconds()
        if age is None or elapsed < 0 or age + elapsed > 5.0:
            raise ValueError("ownship_stale")
        if len(tool.provenance.generations) != 1:
            raise ValueError("ownship_generation_ambiguous")
        heading = key == KEYS[0]
        expected_unit = "deg" if heading else None
        if fact.unit != expected_unit:
            raise ValueError("ownship_unit_mismatch")
        raw = fact.value
        limit = 360 if heading else (90 if key == KEYS[1] else 180)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not isfinite(raw):
            raise ValueError("ownship_numeric_value")
        if (heading and not 0 <= raw < limit) or (not heading and abs(raw) > limit):
            raise ValueError("ownship_numeric_range")
        values.append(ProtectedValue(
            key=key, value=raw, unit=fact.unit,
            kind=ProtectedValueKind.HEADING if heading else ProtectedValueKind.COORDINATES,
        ))
        provenance.append(ProtectedProvenance(
            source=source, authority=WorldFactAuthority.AUTHORITATIVE,
            generation=tool.provenance.generations[0],
            domain_origin=CommunicationDomain.NAVIGATION,
        ))
    # Recommendations/warnings/assumptions are not inputs to protected wording.
    return OperationalSemanticUnit(
        unit_type="navigation.ownship_report",
        semantic_meaning="navigation.current_ownship_state",
        domain=CommunicationDomain.NAVIGATION, priority=CommunicationPriority.ROUTINE,
        status="known", polarity="declarative",
        protected_values=tuple(values), provenance=tuple(provenance),
    )
