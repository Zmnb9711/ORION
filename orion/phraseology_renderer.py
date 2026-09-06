"""Offline Core wording mechanics; PILOT_SYNTHETIC_V1 is NON-NORMATIVE."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orion.communication_contracts import (
    CommunicationContext,
    CommunicationDomain,
    CommunicationProfileId,
    LanguageId,
    OpaqueVersion,
    OperationalSemanticUnit,
    OperationalUnitType,
    ProtectedOperationalFragment,
    ProtectedValue,
    ProtectedValueKind,
)
from orion.interaction_contracts import SemanticKey


PILOT_SYNTHETIC_V1 = "PILOT_SYNTHETIC_V1"
RENDERER_VERSION = "stage7a.renderer.v1"
_DIGITS = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
)
_SUPPORTED_KINDS = frozenset(
    {
        ProtectedValueKind.HEADING,
        ProtectedValueKind.ALTITUDE,
        ProtectedValueKind.SPEED,
        ProtectedValueKind.FREQUENCY,
        ProtectedValueKind.TACAN,
        ProtectedValueKind.LASER_CODE,
        ProtectedValueKind.CALLSIGN,
        ProtectedValueKind.GENERIC,
    }
)


class PhraseologyFailureCode(StrEnum):
    UNSUPPORTED_PROFILE = "unsupported_profile"
    UNSUPPORTED_DOMAIN = "unsupported_domain"
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    UNSUPPORTED_SEMANTICS = "unsupported_semantics"
    UNSUPPORTED_KIND = "unsupported_kind"
    UNSUPPORTED_RULESET = "unsupported_ruleset"
    MISSING_VALUE = "missing_value"
    CONFLICTING_VALUES = "conflicting_values"
    MALFORMED_VALUE = "malformed_value"
    INVALID_RULESET = "invalid_ruleset"


class PhraseologyRenderError(ValueError):
    """Bounded failure: never includes operational values or caller text."""

    def __init__(self, code: PhraseologyFailureCode) -> None:
        self.code = code
        super().__init__(code.value)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PilotValueSlot(_FrozenModel):
    key: SemanticKey
    kind: ProtectedValueKind
    unit: str | None = Field(default=None, min_length=1, max_length=40)


class PilotRule(_FrozenModel):
    """One synthetic meaning with at most one explicitly consumed scalar."""

    profile: CommunicationProfileId
    domain: CommunicationDomain
    language: LanguageId
    unit_type: OperationalUnitType
    meaning: OperationalUnitType
    status: str = Field(min_length=1, max_length=80)
    polarity: str = Field(min_length=1, max_length=40)
    prefix: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z ]+$")
    slot: PilotValueSlot | None = None

    @property
    def selection_key(self) -> tuple[str, ...]:
        return (
            self.profile.value,
            self.domain.value,
            self.language,
            self.unit_type,
            self.meaning,
        )


class PilotRuleset(_FrozenModel):
    version: OpaqueVersion
    rules: tuple[PilotRule, ...] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def unique_selection(self) -> Self:
        keys = [rule.selection_key for rule in self.rules]
        if len(keys) != len(set(keys)):
            raise PhraseologyRenderError(PhraseologyFailureCode.INVALID_RULESET)
        return self


def synthetic_pilot_ruleset() -> PilotRuleset:
    """Fresh immutable test rules, not aviation standards or domain decisions."""

    def rule(
        unit_type: str,
        meaning: str,
        prefix: str,
        key: str | None = None,
        kind: ProtectedValueKind = ProtectedValueKind.GENERIC,
        unit: str | None = None,
        *,
        status: str = "issued",
        polarity: str = "positive",
        domain: CommunicationDomain = CommunicationDomain.NAVIGATION,
    ) -> PilotRule:
        return PilotRule(
            profile=CommunicationProfileId.ICAO,
            domain=domain,
            language="en-US",
            unit_type=unit_type,
            meaning=meaning,
            status=status,
            polarity=polarity,
            prefix=prefix,
            slot=PilotValueSlot(key=key, kind=kind, unit=unit) if key else None,
        )

    return PilotRuleset(
        version=PILOT_SYNTHETIC_V1,
        rules=(
            rule(
                "navigation.heading",
                "navigation.heading_assignment",
                "Fly heading",
                "ownship.heading_deg",
                ProtectedValueKind.HEADING,
                "deg",
            ),
            rule(
                "navigation.altitude",
                "navigation.altitude_instruction",
                "Maintain altitude",
                "assigned.altitude",
                ProtectedValueKind.ALTITUDE,
                "ft",
            ),
            rule(
                "navigation.speed",
                "navigation.speed_instruction",
                "Maintain speed",
                "assigned.speed",
                ProtectedValueKind.SPEED,
                "kn",
            ),
            rule(
                "navigation.frequency",
                "navigation.frequency_information",
                "Frequency",
                "radio.frequency",
                ProtectedValueKind.FREQUENCY,
                "MHz",
                status="available",
            ),
            rule(
                "navigation.tacan",
                "navigation.tacan_information",
                "TACAN",
                "navigation.tacan",
                ProtectedValueKind.TACAN,
                status="available",
            ),
            rule(
                "jtac.laser",
                "jtac.laser_information",
                "Laser code",
                "jtac.laser_code",
                ProtectedValueKind.LASER_CODE,
                status="available",
                domain=CommunicationDomain.JTAC,
            ),
            rule(
                "navigation.callsign",
                "navigation.callsign_information",
                "Callsign",
                "speaker.callsign",
                ProtectedValueKind.CALLSIGN,
                status="available",
            ),
            rule(
                "navigation.distance",
                "navigation.distance_information",
                "Distance",
                "navigation.distance",
                ProtectedValueKind.GENERIC,
                "NM",
                status="available",
            ),
            rule(
                "navigation.correction",
                "navigation.altitude_correction",
                "Altitude correction",
                "navigation.altitude_correction",
                ProtectedValueKind.ALTITUDE,
                "ft",
                polarity="negative",
            ),
            rule(
                "navigation.heading",
                "navigation.heading_unavailable",
                "Heading unavailable",
                status="unavailable",
                polarity="negative",
            ),
        ),
    )


class PhraseologyRenderer:
    """Render resolved semantics using an explicitly injected synthetic ruleset."""

    def __init__(self, ruleset: PilotRuleset) -> None:
        if ruleset.version != PILOT_SYNTHETIC_V1:
            raise PhraseologyRenderError(PhraseologyFailureCode.UNSUPPORTED_RULESET)
        # The version names content, not just a schema. Reordering is permitted;
        # changing wording under the same version is not.
        canonical = synthetic_pilot_ruleset()
        if sorted(ruleset.rules, key=lambda r: r.selection_key) != sorted(
            canonical.rules, key=lambda r: r.selection_key
        ):
            raise PhraseologyRenderError(PhraseologyFailureCode.INVALID_RULESET)
        self._ruleset = ruleset

    def render(
        self,
        unit: OperationalSemanticUnit,
        context: CommunicationContext,
    ) -> ProtectedOperationalFragment:
        if context.phraseology_version not in (None, self._ruleset.version) or (
            context.phraseology_snapshot_id not in (None, self._ruleset.version)
        ):
            raise PhraseologyRenderError(PhraseologyFailureCode.UNSUPPORTED_RULESET)
        candidates = tuple(
            r for r in self._ruleset.rules if r.profile == context.profile_id
        )
        if not candidates:
            raise PhraseologyRenderError(PhraseologyFailureCode.UNSUPPORTED_PROFILE)
        candidates = tuple(r for r in candidates if r.domain == context.domain)
        if not candidates or unit.domain != context.domain:
            raise PhraseologyRenderError(PhraseologyFailureCode.UNSUPPORTED_DOMAIN)
        candidates = tuple(
            r for r in candidates if r.language == context.operational_language
        )
        if not candidates:
            raise PhraseologyRenderError(PhraseologyFailureCode.UNSUPPORTED_LANGUAGE)
        rule = next(
            (
                r
                for r in candidates
                if (
                    r.unit_type == unit.unit_type and r.meaning == unit.semantic_meaning
                )
            ),
            None,
        )
        if rule is None or (unit.status, unit.polarity) != (rule.status, rule.polarity):
            raise PhraseologyRenderError(PhraseologyFailureCode.UNSUPPORTED_SEMANTICS)

        values = unit.protected_values
        keys = [value.key for value in values]
        if len(keys) != len(set(keys)) or len(values) > (1 if rule.slot else 0):
            raise PhraseologyRenderError(PhraseologyFailureCode.CONFLICTING_VALUES)
        if rule.slot is None:
            text = rule.prefix + "."
        else:
            if not values:
                raise PhraseologyRenderError(PhraseologyFailureCode.MISSING_VALUE)
            value = values[0]
            if value.key != rule.slot.key:
                raise PhraseologyRenderError(PhraseologyFailureCode.CONFLICTING_VALUES)
            if value.kind not in _SUPPORTED_KINDS or value.kind != rule.slot.kind:
                raise PhraseologyRenderError(PhraseologyFailureCode.UNSUPPORTED_KIND)
            if value.unit != rule.slot.unit:
                raise PhraseologyRenderError(PhraseologyFailureCode.MALFORMED_VALUE)
            rendered = _format_value(value, negative=rule.polarity == "negative")
            text = f"{rule.prefix} {rendered}."
        return ProtectedOperationalFragment(
            text=text,
            semantic_unit=unit,
            renderer_version=f"{RENDERER_VERSION}/{self._ruleset.version}",
        )


def _format_value(value: ProtectedValue, *, negative: bool) -> str:
    """Lossless pilot forms only; no rounding, unit conversion or coercion."""

    raw = value.value
    kind = value.kind
    rendered: str | None = None
    if kind is ProtectedValueKind.HEADING:
        if type(raw) is int and 0 <= raw <= 359:
            rendered = " ".join(_DIGITS[int(digit)] for digit in f"{raw:03d}")
    elif kind in (ProtectedValueKind.ALTITUDE, ProtectedValueKind.SPEED):
        limit = 999_999 if kind is ProtectedValueKind.ALTITUDE else 9_999
        if type(raw) is int and abs(raw) <= limit and (raw < 0) == negative:
            rendered = str(raw)
    elif isinstance(raw, str) and len(raw) <= 32:
        if kind is ProtectedValueKind.FREQUENCY:
            if re.fullmatch(r"[1-9][0-9]{0,2}\.[0-9]{3}", raw):
                rendered = raw
        elif kind is ProtectedValueKind.TACAN:
            if re.fullmatch(r"[1-9][0-9]{0,2}[XY]", raw) and int(raw[:-1]) <= 126:
                rendered = raw
        elif kind is ProtectedValueKind.LASER_CODE:
            if re.fullmatch(r"[0-9]{4}", raw):
                rendered = " ".join(_DIGITS[int(digit)] for digit in raw)
        elif kind is ProtectedValueKind.CALLSIGN:
            if re.fullmatch(r"[A-Za-z0-9]+(?:[ -][A-Za-z0-9]+)*", raw):
                rendered = raw
        elif kind is ProtectedValueKind.GENERIC:
            # GENERIC is allowed only for the explicit pilot distance slot.
            if re.fullmatch(r"(?:0|[1-9][0-9]{0,5})(?:\.[0-9]{1,3})?", raw):
                rendered = raw
    if rendered is None:
        raise PhraseologyRenderError(PhraseologyFailureCode.MALFORMED_VALUE)
    return f"{rendered} {value.unit}" if value.unit is not None else rendered
