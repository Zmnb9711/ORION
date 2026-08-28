"""Experimental, non-normative deterministic Pilot phraseology boundary.

This bounded module consumes already-decided operational semantics.  It does not
read runtime state, select tools, establish operational truth, or perform speech
or radio presentation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from string import Formatter
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from orion.communication_contracts import (
    CommunicationContext,
    CommunicationDomain,
    CommunicationPriority,
    CommunicationProfileId,
    OperationalSemanticUnit,
    ProtectedOperationalFragment,
    ProtectedProvenance,
    ProtectedValue,
    ProtectedValueKind,
)
from orion.interaction_contracts import (
    CapabilityId,
    SemanticFactKind,
    SemanticResponse,
)
from orion.world_model_contracts import WorldFactAuthority


CATALOG_VERSION = "pilot-phraseology-v1"
SUPPORTED_LANGUAGES = ("en-US", "ru-RU")

EntryId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=120,
        pattern=r"^[a-z][a-z0-9-]*$",
    ),
]
Placeholder = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=80,
        pattern=r"^[a-z][a-z0-9_]*$",
    ),
]


class _PilotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class PilotFormatterId(StrEnum):
    EXACT_TEXT = "exact_text"
    INTEGER = "integer"
    SIGNED_INTEGER = "signed_integer"
    FIXED_THREE = "fixed_three"
    TACAN_EXACT = "tacan_exact"
    LASER_CODE_EXACT = "laser_code_exact"
    COORDINATE_SIX = "coordinate_six"
    MODULATION_EXACT = "modulation_exact"


class PilotResolutionStatus(StrEnum):
    RENDERED = "rendered"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    MISSING_REQUIRED_SLOT = "missing_required_slot"
    INVALID_SLOT_VALUE = "invalid_slot_value"
    INVALID_UNIT = "invalid_unit"


class PilotSelector(_PilotModel):
    profile_id: CommunicationProfileId
    domain: CommunicationDomain
    unit_type: str = Field(pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
    semantic_meaning: str = Field(pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
    status: str | None = Field(default=None, min_length=1, max_length=80)
    polarity: str | None = Field(default=None, min_length=1, max_length=40)


class PilotSlotDefinition(_PilotModel):
    placeholder: Placeholder
    semantic_key: str = Field(pattern=r"^[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)*$")
    expected_kind: ProtectedValueKind
    expected_unit: str | None = Field(default=None, min_length=1, max_length=40)
    formatter_id: PilotFormatterId

    @model_validator(mode="after")
    def validate_formatter_contract(self) -> Self:
        formatter = self.formatter_id
        canonical_units = {
            ProtectedValueKind.CALLSIGN: None,
            ProtectedValueKind.RUNWAY: None,
            ProtectedValueKind.HEADING: "deg",
            ProtectedValueKind.ALTITUDE: "ft",
            ProtectedValueKind.SPEED: "kt",
            ProtectedValueKind.FREQUENCY: "MHz",
            ProtectedValueKind.TACAN: None,
            ProtectedValueKind.LASER_CODE: None,
            ProtectedValueKind.COORDINATES: "deg",
        }
        required_unit = canonical_units.get(self.expected_kind)
        if (
            self.expected_kind in canonical_units
            and self.expected_unit != required_unit
        ):
            raise ValueError(
                f"{self.expected_kind.value} requires canonical unit {required_unit!r}"
            )
        if formatter is PilotFormatterId.FIXED_THREE and (
            self.expected_kind is not ProtectedValueKind.FREQUENCY
            or self.expected_unit != "MHz"
        ):
            raise ValueError("fixed_three requires FREQUENCY in MHz")
        if formatter is PilotFormatterId.TACAN_EXACT and (
            self.expected_kind is not ProtectedValueKind.TACAN
            or self.expected_unit is not None
        ):
            raise ValueError("tacan_exact requires TACAN without a unit")
        if formatter is PilotFormatterId.LASER_CODE_EXACT and (
            self.expected_kind is not ProtectedValueKind.LASER_CODE
            or self.expected_unit is not None
        ):
            raise ValueError("laser_code_exact requires LASER_CODE without a unit")
        if formatter is PilotFormatterId.COORDINATE_SIX and (
            self.expected_kind is not ProtectedValueKind.COORDINATES
            or self.expected_unit != "deg"
        ):
            raise ValueError("coordinate_six requires COORDINATES in deg")
        if formatter is PilotFormatterId.MODULATION_EXACT and (
            self.expected_kind is not ProtectedValueKind.GENERIC
            or self.expected_unit is not None
        ):
            raise ValueError("modulation_exact requires GENERIC without a unit")
        if formatter is PilotFormatterId.SIGNED_INTEGER and self.expected_unit is None:
            raise ValueError("signed_integer requires an explicit unit")
        return self


class PilotLanguageRealization(_PilotModel):
    language: str = Field(pattern=r"^(?:en-US|ru-RU)$")
    template: str = Field(min_length=1, max_length=1_000)


class PilotPhraseologyEntry(_PilotModel):
    entry_id: EntryId
    catalog_version: str = Field(min_length=1, max_length=80)
    selector: PilotSelector
    slots: tuple[PilotSlotDefinition, ...] = ()
    realizations: tuple[PilotLanguageRealization, ...]
    experimental_non_normative: bool = True

    @model_validator(mode="after")
    def validate_entry_shape(self) -> Self:
        if self.catalog_version != CATALOG_VERSION:
            raise ValueError("entry catalog version does not match Pilot catalog")
        if not self.experimental_non_normative:
            raise ValueError("Pilot entries must remain experimental/non-normative")

        placeholders = [slot.placeholder for slot in self.slots]
        semantic_keys = [slot.semantic_key for slot in self.slots]
        if len(placeholders) != len(set(placeholders)):
            raise ValueError("slot placeholders must be unique")
        if len(semantic_keys) != len(set(semantic_keys)):
            raise ValueError("slot semantic keys must be unique")

        languages = [item.language for item in self.realizations]
        if tuple(languages) != SUPPORTED_LANGUAGES:
            raise ValueError(
                "Pilot entries require ordered en-US and ru-RU realizations"
            )
        declared = set(placeholders)
        for realization in self.realizations:
            used: list[str] = []
            for _, field_name, format_spec, conversion in Formatter().parse(
                realization.template
            ):
                if field_name is None:
                    continue
                if re.fullmatch(r"[a-z][a-z0-9_]*", field_name) is None:
                    raise ValueError(
                        "templates may use only simple declared placeholders"
                    )
                if format_spec or conversion:
                    raise ValueError(
                        "template format specs and conversions are forbidden"
                    )
                used.append(field_name)
            if set(used) != declared or len(used) != len(declared):
                raise ValueError(
                    "each realization must use every declared placeholder exactly"
                )
        return self

    def realization(self, language: str) -> PilotLanguageRealization | None:
        return next(
            (item for item in self.realizations if item.language == language), None
        )


class PilotResolvedSlot(_PilotModel):
    placeholder: Placeholder
    semantic_key: str
    kind: ProtectedValueKind
    value: str
    unit: str | None = None
    formatter_id: PilotFormatterId


class PilotResolutionResult(_PilotModel):
    status: PilotResolutionStatus
    selected_entry_id: EntryId | None = None
    resolved_slots: tuple[PilotResolvedSlot, ...] = ()
    fragment: ProtectedOperationalFragment | None = Field(default=None, repr=False)
    failure_reason: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        rendered = self.status is PilotResolutionStatus.RENDERED
        if rendered != (self.fragment is not None):
            raise ValueError("only rendered results may contain a fragment")
        if rendered and (
            self.selected_entry_id is None or self.failure_reason is not None
        ):
            raise ValueError("rendered result shape is invalid")
        if not rendered and self.failure_reason is None:
            raise ValueError("failed result requires a bounded reason")
        return self


class PilotCatalogError(ValueError):
    """Raised for invalid static Pilot catalog definitions."""


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class PilotPhraseologyCatalog:
    entries: tuple[PilotPhraseologyEntry, ...]
    version: str = CATALOG_VERSION

    def __post_init__(self) -> None:
        if not self.entries:
            raise PilotCatalogError("Pilot catalog must not be empty")
        if self.version != CATALOG_VERSION:
            raise PilotCatalogError("unsupported Pilot catalog version")
        ids = [entry.entry_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise PilotCatalogError("duplicate Pilot catalog entry ID")
        selector_keys = [
            _canonical_json(entry.selector.model_dump(mode="json"))
            for entry in self.entries
        ]
        if len(selector_keys) != len(set(selector_keys)):
            raise PilotCatalogError("duplicate or ambiguous exact selector")

    def canonical_payload(self) -> dict[str, object]:
        ordered = sorted(self.entries, key=lambda item: item.entry_id)
        return {
            "catalog_version": self.version,
            "experimental_non_normative": True,
            "entries": [entry.model_dump(mode="json") for entry in ordered],
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical_json(self.canonical_payload())).hexdigest()

    def matches(
        self,
        context: CommunicationContext,
        unit: OperationalSemanticUnit,
    ) -> tuple[PilotPhraseologyEntry, ...]:
        return tuple(
            entry
            for entry in self.entries
            if entry.selector.profile_id is context.profile_id
            and entry.selector.domain is context.domain
            and entry.selector.domain is unit.domain
            and entry.selector.unit_type == unit.unit_type
            and entry.selector.semantic_meaning == unit.semantic_meaning
            and entry.selector.status == unit.status
            and entry.selector.polarity == unit.polarity
        )


class PilotPhraseologyResolver:
    def __init__(self, catalog: PilotPhraseologyCatalog) -> None:
        self.catalog = catalog

    def resolve(
        self,
        context: CommunicationContext,
        unit: OperationalSemanticUnit,
    ) -> PilotResolutionResult:
        language = context.operational_language
        matches = self.catalog.matches(context, unit)
        if not matches or language not in SUPPORTED_LANGUAGES:
            return self._failure(
                PilotResolutionStatus.NOT_FOUND,
                "no exact selector and supported language realization matched",
            )
        if len(matches) != 1:
            return self._failure(
                PilotResolutionStatus.AMBIGUOUS,
                "more than one exact Pilot selector matched",
            )
        entry = matches[0]
        realization = entry.realization(language)
        if realization is None:
            return self._failure(
                PilotResolutionStatus.NOT_FOUND,
                "matched entry has no exact language realization",
            )
        if len(unit.provenance) != 1:
            return self._failure(
                PilotResolutionStatus.INVALID_SLOT_VALUE,
                "Pilot requires exactly one coherent unit-level provenance",
            )

        expected_keys = {slot.semantic_key for slot in entry.slots}
        supplied = {value.key: value for value in unit.protected_values}
        missing = expected_keys.difference(supplied)
        if missing:
            return self._failure(
                PilotResolutionStatus.MISSING_REQUIRED_SLOT,
                f"missing required protected key: {sorted(missing)[0]}",
            )
        unexpected = set(supplied).difference(expected_keys)
        if unexpected:
            return self._failure(
                PilotResolutionStatus.INVALID_SLOT_VALUE,
                f"unexpected protected key: {sorted(unexpected)[0]}",
            )

        resolved: list[PilotResolvedSlot] = []
        for slot in entry.slots:
            protected = supplied[slot.semantic_key]
            if protected.kind is not slot.expected_kind:
                return self._failure(
                    PilotResolutionStatus.INVALID_SLOT_VALUE,
                    f"invalid kind for {slot.semantic_key}",
                )
            if protected.unit != slot.expected_unit:
                return self._failure(
                    PilotResolutionStatus.INVALID_UNIT,
                    f"invalid unit for {slot.semantic_key}",
                )
            formatted = _format_protected_value(slot, protected)
            if formatted is None:
                return self._failure(
                    PilotResolutionStatus.INVALID_SLOT_VALUE,
                    f"invalid value for {slot.semantic_key}",
                )
            resolved.append(
                PilotResolvedSlot(
                    placeholder=slot.placeholder,
                    semantic_key=slot.semantic_key,
                    kind=protected.kind,
                    value=formatted,
                    unit=protected.unit,
                    formatter_id=slot.formatter_id,
                )
            )

        values = {item.placeholder: item.value for item in resolved}
        rendered = realization.template.format_map(values)
        fragment = ProtectedOperationalFragment(
            text=rendered,
            semantic_unit=unit,
            renderer_version=(f"{self.catalog.version}/{self.catalog.sha256[:16]}"),
        )
        return PilotResolutionResult(
            status=PilotResolutionStatus.RENDERED,
            selected_entry_id=entry.entry_id,
            resolved_slots=tuple(resolved),
            fragment=fragment,
        )

    @staticmethod
    def _failure(
        status: PilotResolutionStatus,
        reason: str,
    ) -> PilotResolutionResult:
        return PilotResolutionResult(status=status, failure_reason=reason)


def _format_protected_value(
    slot: PilotSlotDefinition,
    protected: ProtectedValue,
) -> str | None:
    value = protected.value
    formatter = slot.formatter_id
    if formatter is PilotFormatterId.EXACT_TEXT:
        if not isinstance(value, str) or value != value.strip() or not value:
            return None
        return value if len(value) <= 160 else None
    if formatter is PilotFormatterId.INTEGER:
        return (
            str(value)
            if isinstance(value, int) and not isinstance(value, bool)
            else None
        )
    if formatter is PilotFormatterId.SIGNED_INTEGER:
        return (
            str(value)
            if isinstance(value, int) and not isinstance(value, bool)
            else None
        )
    if formatter is PilotFormatterId.FIXED_THREE:
        return (
            value
            if isinstance(value, str) and re.fullmatch(r"\d{1,3}\.\d{3}", value)
            else None
        )
    if formatter is PilotFormatterId.MODULATION_EXACT:
        return value if value in {"AM", "FM"} else None
    if formatter is PilotFormatterId.TACAN_EXACT:
        if not isinstance(value, str) or re.fullmatch(r"\d{1,3}[XY]", value) is None:
            return None
        channel = int(value[:-1])
        return value if 1 <= channel <= 126 else None
    if formatter is PilotFormatterId.LASER_CODE_EXACT:
        return (
            value if isinstance(value, str) and re.fullmatch(r"\d{4}", value) else None
        )
    if formatter is PilotFormatterId.COORDINATE_SIX:
        if (
            not isinstance(value, str)
            or re.fullmatch(r"-?\d{1,3}\.\d{6}", value) is None
        ):
            return None
        numeric = float(value)
        limit = 90.0 if slot.semantic_key.endswith("latitude") else 180.0
        return value if -limit <= numeric <= limit else None
    return None


def adapt_ia6_ownship_heading(
    response: SemanticResponse,
) -> OperationalSemanticUnit:
    """Adapt only the controlled IA-6 ownship heading fact, never free prose."""

    if response.capability != CapabilityId("world.ownship.read"):
        raise ValueError("Pilot adapter accepts only world.ownship.read")
    facts = [
        fact
        for fact in response.authoritative_facts
        if fact.key == "ownship.heading_deg"
    ]
    if len(facts) != 1:
        raise ValueError("Pilot adapter requires one authoritative heading fact")
    fact = facts[0]
    if (
        fact.kind is not SemanticFactKind.AUTHORITATIVE
        or fact.unit != "deg"
        or fact.source is None
    ):
        raise ValueError("Pilot adapter heading fact has incompatible semantics")
    return OperationalSemanticUnit(
        unit_type="navigation.heading",
        semantic_meaning="navigation.heading",
        domain=CommunicationDomain.NAVIGATION,
        priority=CommunicationPriority.IMPORTANT,
        status="available",
        protected_values=(
            ProtectedValue(
                key=fact.key,
                kind=ProtectedValueKind.HEADING,
                value=fact.value,
                unit=fact.unit,
            ),
        ),
        provenance=(
            ProtectedProvenance(
                source=fact.source,
                authority=WorldFactAuthority.AUTHORITATIVE,
                domain_origin=CommunicationDomain.NAVIGATION,
            ),
        ),
    )
