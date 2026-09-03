"""Provider-neutral validation and Core binding for aircraft identity wording."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Protocol

from orion.aircraft_knowledge import aircraft_knowledge


AVAILABLE_AIRCRAFT_MARKER = "{{aircraft_identity}}"
UNAVAILABLE_AIRCRAFT_MARKER = "{{aircraft_unavailable}}"
MAX_AIRCRAFT_SHELL_LENGTH = 300


class AircraftIdentityShellValidationErrorCode(StrEnum):
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    EMPTY_OUTPUT = "empty_output"
    OVER_LENGTH = "over_length"
    MISSING_MARKER = "missing_marker"
    DUPLICATE_MARKER = "duplicate_marker"
    FOREIGN_MARKER = "foreign_marker"
    WRONG_LANGUAGE = "wrong_language"
    IDENTIFIER_PUNCTUATION = "identifier_punctuation"
    CANONICAL_IDENTITY_OUTSIDE_MARKER = "canonical_identity_outside_marker"
    RAW_IDENTITY_OUTSIDE_MARKER = "raw_identity_outside_marker"
    DISPLAY_IDENTITY_OUTSIDE_MARKER = "display_identity_outside_marker"
    UNSUPPORTED_EXTRA_CLAIM = "unsupported_extra_claim"
    BINDING_MARKER_INVALID = "binding_marker_invalid"
    BINDING_VALUE_UNAVAILABLE = "binding_value_unavailable"
    BINDING_IDENTITY_MISMATCH = "binding_identity_mismatch"


class AircraftIdentityShellValidationError(RuntimeError):
    """A provider exceeded the bounded no-fact-authority wording contract."""

    def __init__(
        self,
        message: str,
        *,
        code: AircraftIdentityShellValidationErrorCode | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code


class AircraftIdentityFactView(Protocol):
    @property
    def status(self) -> object: ...

    @property
    def raw_aircraft_id(self) -> str | None: ...

    @property
    def display_name(self) -> str | None: ...


def aircraft_identity_marker(result: AircraftIdentityFactView) -> str:
    status = getattr(result.status, "value", result.status)
    return (
        AVAILABLE_AIRCRAFT_MARKER
        if status == "available"
        else UNAVAILABLE_AIRCRAFT_MARKER
    )


def _safe_identity_label_colon(shell: str, *, language: str) -> bool:
    """Recognize one bounded identity label whose value is the Core marker.

    Realtime commonly emits ``label: {{marker}}`` in Russian.  Once the marker
    is removed, a terminal colon is punctuation rather than a second claim.
    Only identity-label vocabulary is accepted; this does not open a generic
    colon-delimited factual channel.
    """

    normalized = " ".join(shell.casefold().split()).strip().rstrip(".!?").strip()
    if not normalized.endswith(":") or normalized.count(":") != 1:
        return False
    words = set(re.findall(r"[a-zа-яё]+", normalized[:-1]))
    if language == "ru-RU":
        allowed = {
            "в",
            "выполняющего",
            "выполняемого",
            "данные",
            "данный",
            "для",
            "задействованного",
            "идентификационные",
            "текущая",
            "текущий",
            "текущего",
            "текущем",
            "идентифицировано",
            "идентификация",
            "идентификатор",
            "идентификатором",
            "воздушного",
            "воздушное",
            "судна",
            "судно",
            "на",
            "обозначено",
            "осуществляющего",
            "момент",
            "полёт",
            "полета",
            "полёта",
            "полете",
            "полёте",
            "рамках",
            "рейс",
            "рейсе",
            "самолета",
            "самолёта",
        }
        return bool(words) and words <= allowed and bool(
            words
            & {
                "идентификационные",
                "идентификация",
                "идентифицировано",
                "идентификатор",
                "идентификатором",
            }
        )
    allowed = {"the", "current", "aircraft", "identity"}
    return bool(words) and words <= allowed and "identity" in words


def _safe_ru_parenthetical_identity_clause(shell: str) -> bool:
    normalized = " ".join(shell.casefold().split()).strip().rstrip(".!?").strip()
    if normalized.count(",") != 2:
        return False
    words = set(re.findall(r"[а-яё]+", normalized))
    allowed = {
        "в",
        "воздушного",
        "воздушное",
        "выполняющее",
        "данные",
        "задействованного",
        "задействованное",
        "идентификационные",
        "идентификация",
        "идентифицировано",
        "идентификатор",
        "идентификатором",
        "идентифицируется",
        "имеет",
        "как",
        "на",
        "обозначено",
        "осуществляющее",
        "полета",
        "полет",
        "полёта",
        "полете",
        "полёт",
        "полёте",
        "рейс",
        "рейса",
        "рейсе",
        "судна",
        "судно",
        "текущего",
        "текущем",
        "текущий",
        "участвующее",
    }
    return bool(words) and words <= allowed and bool(
        words
        & {
            "идентификация",
            "идентифицировано",
            "идентификатор",
            "идентификатором",
            "идентификационные",
            "идентифицируется",
        }
    )


def _safe_en_with_identity_clause(shell: str) -> bool:
    normalized = " ".join(shell.casefold().split()).strip().rstrip(".!?").strip()
    words = set(re.findall(r"[a-z]+", normalized))
    allowed = {
        "aircraft",
        "associated",
        "being",
        "conducted",
        "current",
        "currently",
        "flight",
        "identity",
        "is",
        "operates",
        "operating",
        "the",
        "with",
    }
    identity_clause = "aircraft" in words or (
        "flight" in words and bool(words & {"conducted", "operates", "operating"})
    )
    return bool(words) and words <= allowed and "with" in words and identity_clause


def _unsupported_second_claim(shell: str, *, language: str) -> bool:
    """Reject multi-clause or operational additions to the linguistic shell.

    This deliberately validates structure rather than selecting a canned phrase.
    A single natural informational clause remains provider-owned, while another
    assertion, operational datum, or identifier-like value is rejected.
    """

    normalized = " ".join(shell.casefold().split()).strip()
    body = normalized.rstrip(".!?").strip()
    if re.search(r"[.!?]", body) or ";" in body:
        return True
    if ":" in body and not _safe_identity_label_colon(shell, language=language):
        return True
    if language == "ru-RU":
        if (
            "," in body
            and not body.startswith("к сожалению,")
            and not _safe_ru_parenthetical_identity_clause(shell)
            and not _safe_identity_label_colon(shell, language=language)
        ):
            return True
        connectors = r"\b(?:и|но|зато|также|прич[её]м|потому|котор(?:ый|ая|ое|ые))\b"
        operational = (
            r"\b(?:курс|скорост|высот|топлив|позици|координат|частот|канал|"
            r"tacan|полос|аэродром|вооружени|цель|угроз)\w*\b"
        )
    else:
        if "," in body:
            return True
        if " with " in f" {body} " and not _safe_en_with_identity_clause(shell):
            return True
        connectors = r"\b(?:and|but|also|because|while|which)\b"
        operational = (
            r"\b(?:heading|course|speed|altitude|fuel|position|coordinate|"
            r"frequency|channel|tacan|runway|airfield|weapon|target|threat)s?\b"
        )
    return bool(re.search(connectors, body) or re.search(operational, body))


def validate_aircraft_identity_structure(
    provider_text: str,
    result: AircraftIdentityFactView,
    *,
    language: str,
) -> str:
    """Validate only bounded Core binding structure, not natural-language grammar."""

    if language not in {"ru-RU", "en-US"}:
        raise AircraftIdentityShellValidationError(
            "Unsupported response language",
            code=AircraftIdentityShellValidationErrorCode.UNSUPPORTED_LANGUAGE,
        )
    marker = aircraft_identity_marker(result)
    text = " ".join(provider_text.split())
    if not text:
        raise AircraftIdentityShellValidationError(
            "Formulation is empty",
            code=AircraftIdentityShellValidationErrorCode.EMPTY_OUTPUT,
        )
    if len(text) > MAX_AIRCRAFT_SHELL_LENGTH:
        raise AircraftIdentityShellValidationError(
            "Formulation exceeds the bounded shell length",
            code=AircraftIdentityShellValidationErrorCode.OVER_LENGTH,
        )
    other_marker = (
        UNAVAILABLE_AIRCRAFT_MARKER
        if marker == AVAILABLE_AIRCRAFT_MARKER
        else AVAILABLE_AIRCRAFT_MARKER
    )
    if other_marker in text or "{{" in text.replace(marker, ""):
        raise AircraftIdentityShellValidationError(
            "Formulation introduced an unsupported substitution marker",
            code=AircraftIdentityShellValidationErrorCode.FOREIGN_MARKER,
        )
    marker_count = text.count(marker)
    if marker_count == 0:
        raise AircraftIdentityShellValidationError(
            "Formulation omitted the Core substitution marker",
            code=AircraftIdentityShellValidationErrorCode.MISSING_MARKER,
        )
    if marker_count > 1:
        raise AircraftIdentityShellValidationError(
            "Formulation duplicated the Core substitution marker",
            code=AircraftIdentityShellValidationErrorCode.DUPLICATE_MARKER,
        )

    shell = text.replace(marker, "")
    lowered = shell.casefold()
    has_cyrillic = bool(re.search(r"[А-Яа-яЁё]", shell))
    if (language == "ru-RU" and not has_cyrillic) or (
        language == "en-US" and has_cyrillic
    ):
        raise AircraftIdentityShellValidationError(
            "Formulation did not follow the requested language",
            code=AircraftIdentityShellValidationErrorCode.WRONG_LANGUAGE,
        )
    forbidden = {
        item.casefold()
        for profile in aircraft_knowledge.list_profiles()
        for item in {profile.aircraft_id, profile.display_name, *profile.aliases}
        if len(item.strip()) >= 3
    }
    if result.raw_aircraft_id and result.raw_aircraft_id.casefold() in lowered:
        raise AircraftIdentityShellValidationError(
            "Formulation copied the raw DCS identity outside the Core marker",
            code=AircraftIdentityShellValidationErrorCode.RAW_IDENTITY_OUTSIDE_MARKER,
        )
    if result.display_name and result.display_name.casefold() in lowered:
        raise AircraftIdentityShellValidationError(
            "Formulation copied the display identity outside the Core marker",
            code=AircraftIdentityShellValidationErrorCode.DISPLAY_IDENTITY_OUTSIDE_MARKER,
        )
    if any(item in lowered for item in forbidden):
        raise AircraftIdentityShellValidationError(
            "Formulation introduced an aircraft identity outside the Core marker",
            code=(
                AircraftIdentityShellValidationErrorCode.CANONICAL_IDENTITY_OUTSIDE_MARKER
            ),
        )
    if re.search(r"[\d/_+]", shell):
        raise AircraftIdentityShellValidationError(
            "Formulation introduced an identifier-like value outside the Core marker",
            code=AircraftIdentityShellValidationErrorCode.IDENTIFIER_PUNCTUATION,
        )
    return text


def validate_aircraft_identity_shell(
    provider_text: str,
    result: AircraftIdentityFactView,
    *,
    language: str,
) -> str:
    """Validate one complete provider shell without substituting the Core fact."""

    text = validate_aircraft_identity_structure(
        provider_text,
        result,
        language=language,
    )
    marker = aircraft_identity_marker(result)
    shell = text.replace(marker, "")
    if _unsupported_second_claim(shell, language=language):
        raise AircraftIdentityShellValidationError(
            "Formulation introduced an unsupported additional factual claim",
            code=AircraftIdentityShellValidationErrorCode.UNSUPPORTED_EXTRA_CLAIM,
        )
    return text


def bind_aircraft_identity_shell(
    validated_shell: str,
    result: AircraftIdentityFactView,
    *,
    language: str,
) -> str:
    """Bind one already-validated shell to the exact authoritative Core value."""

    marker = aircraft_identity_marker(result)
    if validated_shell.count(marker) != 1:
        raise AircraftIdentityShellValidationError(
            "Validated shell no longer contains exactly one Core marker",
            code=AircraftIdentityShellValidationErrorCode.BINDING_MARKER_INVALID,
        )

    status = getattr(result.status, "value", result.status)
    replacement = (
        result.display_name
        if status == "available"
        else (
            "данные о текущем самолёте из DCS недоступны"
            if language == "ru-RU"
            else "current aircraft identity from DCS is unavailable"
        )
    )
    if not replacement:
        raise AircraftIdentityShellValidationError(
            "Core aircraft substitution is unavailable",
            code=AircraftIdentityShellValidationErrorCode.BINDING_VALUE_UNAVAILABLE,
        )
    final_text = validated_shell.replace(marker, replacement)
    if result.display_name and final_text.count(result.display_name) != 1:
        raise AircraftIdentityShellValidationError(
            "Final wording did not preserve the exact Core aircraft display identity",
            code=AircraftIdentityShellValidationErrorCode.BINDING_IDENTITY_MISMATCH,
        )
    return final_text


def validate_and_bind_aircraft_identity_shell(
    provider_text: str,
    result: AircraftIdentityFactView,
    *,
    language: str,
) -> str:
    """Validate one complete provider shell, then bind the exact Core fact."""

    validated = validate_aircraft_identity_shell(
        provider_text,
        result,
        language=language,
    )
    return bind_aircraft_identity_shell(validated, result, language=language)


__all__ = [
    "AVAILABLE_AIRCRAFT_MARKER",
    "AircraftIdentityShellValidationError",
    "AircraftIdentityShellValidationErrorCode",
    "MAX_AIRCRAFT_SHELL_LENGTH",
    "UNAVAILABLE_AIRCRAFT_MARKER",
    "aircraft_identity_marker",
    "bind_aircraft_identity_shell",
    "validate_aircraft_identity_structure",
    "validate_aircraft_identity_shell",
    "validate_and_bind_aircraft_identity_shell",
]
