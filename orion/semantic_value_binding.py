"""Exact provider-neutral binding of semantic facts to accepted tool data."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from orion.interaction_contracts import (
    SemanticFact,
    SemanticInputIssue,
    SemanticInputStatus,
)
from orion.tool_gateway_contracts import ToolResult, ToolResultStatus
from orion.world_model_contracts import WorldFactAuthority, WorldFactStatus


@dataclass(frozen=True, slots=True)
class BoundToolValue:
    """One typed scalar leaf extracted from a retained Core ToolResult."""

    key: str
    value: str | int | float | bool | None
    status: WorldFactStatus
    authority: WorldFactAuthority
    unit: str | None


def authoritative_fact_matches_tool_result(
    fact: SemanticFact,
    result: ToolResult,
) -> bool:
    """Return whether ``fact`` is the exact known authoritative tool leaf."""

    matches = [item for item in tool_result_values(result) if item.key == fact.key]
    if len(matches) != 1:
        return False
    actual = matches[0]
    return (
        actual.status is WorldFactStatus.KNOWN
        and actual.authority is WorldFactAuthority.AUTHORITATIVE
        and actual.unit == fact.unit
        and _same_scalar(actual.value, fact.value)
    )


def unavailable_input_matches_tool_result(
    issue: SemanticInputIssue,
    result: ToolResult,
) -> bool:
    """Bind an explicitly sourced unknown/unavailable input to a null fact."""

    expected = {
        SemanticInputStatus.UNKNOWN: WorldFactStatus.UNKNOWN,
        SemanticInputStatus.UNAVAILABLE: WorldFactStatus.UNAVAILABLE,
    }[issue.status]
    matches = [item for item in tool_result_values(result) if item.key == issue.key]
    return (
        len(matches) == 1 and matches[0].status is expected and matches[0].value is None
    )


def tool_result_values(result: ToolResult) -> tuple[BoundToolValue, ...]:
    """Project scalar leaves from typed WorldFacts without natural-language parsing."""

    if result.status is not ToolResultStatus.COMPLETED or result.data is None:
        return ()
    projected: list[BoundToolValue] = []

    def leaves(prefix: str, value: Any) -> list[tuple[str, Any]]:
        if value is None or isinstance(value, (str, int, float, bool)):
            return [(prefix, value)]
        if isinstance(value, dict):
            output: list[tuple[str, Any]] = []
            for key, item in value.items():
                output.extend(leaves(f"{prefix}.{key}", item))
            return output
        if isinstance(value, list):
            output = []
            for index, item in enumerate(value):
                output.extend(leaves(f"{prefix}.{index}", item))
            return output
        return []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            required = {"key", "value", "status", "authority"}
            if required.issubset(value):
                try:
                    status = WorldFactStatus(value["status"])
                    authority = WorldFactAuthority(value["authority"])
                except (TypeError, ValueError):
                    return
                key = value["key"]
                unit = value.get("unit")
                if not isinstance(key, str) or (
                    unit is not None and not isinstance(unit, str)
                ):
                    return
                for leaf_key, leaf_value in leaves(key, value.get("value")):
                    if leaf_value is None or isinstance(
                        leaf_value, (str, int, float, bool)
                    ):
                        projected.append(
                            BoundToolValue(
                                key=leaf_key,
                                value=leaf_value,
                                status=status,
                                authority=authority,
                                unit=unit,
                            )
                        )
                return
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(result.data.root)
    return tuple(projected)


def _same_scalar(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        try:
            return Decimal(str(left)) == Decimal(str(right))
        except InvalidOperation:
            return False
    return type(left) is type(right) and left == right
