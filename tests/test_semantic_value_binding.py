from datetime import UTC, datetime

from orion.interaction_contracts import (
    SemanticFact,
    SemanticFactKind,
    SemanticInputIssue,
    SemanticInputStatus,
)
from orion.semantic_value_binding import (
    authoritative_fact_matches_tool_result,
    unavailable_input_matches_tool_result,
)
from orion.tool_gateway_contracts import (
    ToolData,
    ToolProvenance,
    ToolReceipt,
    ToolReceiptStatus,
    ToolResult,
    ToolResultStatus,
)
from orion.world_model_contracts import WorldFactAuthority, WorldFactStatus


NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def result() -> ToolResult:
    def fact(
        key: str,
        value: object,
        *,
        status: str = "known",
        authority: str = "authoritative",
        unit: str | None = None,
    ) -> dict[str, object]:
        return {
            "key": key,
            "value": value,
            "status": status,
            "source": "dcs_export",
            "authority": authority,
            "unit": unit,
            "reason": None if status == "known" else "value_not_exported",
        }

    return ToolResult(
        call_id="binding-call",
        tool_name="orion.test.binding",
        tool_version="1.0",
        capability="test.binding",
        status=ToolResultStatus.COMPLETED,
        data=ToolData(
            root={
                "snapshot": {
                    "heading": fact("ownship.heading_deg", 137.0, unit="deg"),
                    "mode": fact("aircraft.mode", "NAV"),
                    "enabled": fact("aircraft.tacan_enabled", True),
                    "position": fact(
                        "ownship.position",
                        {"latitude": 42.1, "longitude": 41.2, "altitude_m": 2100},
                    ),
                    "missing": fact(
                        "ownship.altitude_agl_m", None, status="unavailable"
                    ),
                    "derived": fact(
                        "ownship.ground_speed_mps", 120.0, authority="derived"
                    ),
                }
            }
        ),
        output_schema="orion.tool.output.binding.v1",
        provenance=ToolProvenance(
            authorities=(WorldFactAuthority.AUTHORITATIVE, WorldFactAuthority.DERIVED),
            fact_statuses=(WorldFactStatus.KNOWN, WorldFactStatus.UNAVAILABLE),
        ),
        receipt=ToolReceipt(
            call_id="binding-call",
            tool_name="orion.test.binding",
            tool_version="1.0",
            status=ToolReceiptStatus.COMPLETED,
            actor_id="test",
            accepted_at=NOW,
            completed_at=NOW,
            latency_ms=0,
            handler_started=True,
        ),
    )


def semantic(
    key: str, value: str | int | float | bool, unit: str | None = None
) -> SemanticFact:
    return SemanticFact(
        key=key,
        value=value,
        kind=SemanticFactKind.AUTHORITATIVE,
        unit=unit,
    )


def test_binding_supports_exact_numeric_string_boolean_and_structured_leaves() -> None:
    tool = result()
    assert authoritative_fact_matches_tool_result(
        semantic("ownship.heading_deg", 137, "deg"), tool
    )
    assert authoritative_fact_matches_tool_result(
        semantic("aircraft.mode", "NAV"), tool
    )
    assert authoritative_fact_matches_tool_result(
        semantic("aircraft.tacan_enabled", True), tool
    )
    assert authoritative_fact_matches_tool_result(
        semantic("ownship.position.latitude", 42.1), tool
    )


def test_binding_rejects_mutation_wrong_unit_key_type_and_derived_upgrade() -> None:
    tool = result()
    assert not authoritative_fact_matches_tool_result(
        semantic("ownship.heading_deg", 173, "deg"), tool
    )
    assert not authoritative_fact_matches_tool_result(
        semantic("ownship.heading_deg", 137, "deg_true"), tool
    )
    assert not authoritative_fact_matches_tool_result(
        semantic("flight.heading_deg", 137), tool
    )
    assert not authoritative_fact_matches_tool_result(
        semantic("aircraft.tacan_enabled", 1), tool
    )
    assert not authoritative_fact_matches_tool_result(
        semantic("ownship.ground_speed_mps", 120.0), tool
    )


def test_unavailable_binding_requires_exact_null_key_and_status() -> None:
    tool = result()
    issue = SemanticInputIssue(
        key="ownship.altitude_agl_m",
        status=SemanticInputStatus.UNAVAILABLE,
        reason="value_not_exported",
    )
    assert unavailable_input_matches_tool_result(issue, tool)
    assert not unavailable_input_matches_tool_result(
        issue.model_copy(update={"status": SemanticInputStatus.UNKNOWN}), tool
    )
