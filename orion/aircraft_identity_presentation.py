"""Provider-neutral validation and Core binding for aircraft identity wording."""

from __future__ import annotations

import re
from typing import Protocol

from orion.aircraft_knowledge import aircraft_knowledge


AVAILABLE_AIRCRAFT_MARKER = "{{aircraft_identity}}"
UNAVAILABLE_AIRCRAFT_MARKER = "{{aircraft_unavailable}}"
MAX_AIRCRAFT_SHELL_LENGTH = 300


class AircraftIdentityShellValidationError(RuntimeError):
    """A provider exceeded the bounded no-fact-authority wording contract."""


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


def _unsupported_second_claim(shell: str, *, language: str) -> bool:
    """Reject multi-clause or operational additions to the linguistic shell.

    This deliberately validates structure rather than selecting a canned phrase.
    A single natural informational clause remains provider-owned, while another
    assertion, operational datum, or identifier-like value is rejected.
    """

    normalized = " ".join(shell.casefold().split()).strip()
    body = normalized.rstrip(".!?").strip()
    if re.search(r"[.!?]", body) or re.search(r"[;:]", body):
        return True
    if language == "ru-RU":
        if "," in body and not body.startswith("к сожалению,"):
            return True
        connectors = r"\b(?:и|но|зато|также|прич[её]м|потому|котор(?:ый|ая|ое|ые))\b"
        operational = (
            r"\b(?:курс|скорост|высот|топлив|позици|координат|частот|канал|"
            r"tacan|полос|аэродром|вооружени|цель|угроз)\w*\b"
        )
    else:
        if "," in body:
            return True
        connectors = r"\b(?:and|but|also|because|while|which|with)\b"
        operational = (
            r"\b(?:heading|course|speed|altitude|fuel|position|coordinate|"
            r"frequency|channel|tacan|runway|airfield|weapon|target|threat)s?\b"
        )
    return bool(re.search(connectors, body) or re.search(operational, body))


def validate_aircraft_identity_shell(
    provider_text: str,
    result: AircraftIdentityFactView,
    *,
    language: str,
) -> str:
    """Validate one complete provider shell without substituting the Core fact."""

    if language not in {"ru-RU", "en-US"}:
        raise AircraftIdentityShellValidationError("Unsupported response language")
    marker = aircraft_identity_marker(result)
    text = " ".join(provider_text.split())
    if not text or len(text) > MAX_AIRCRAFT_SHELL_LENGTH:
        raise AircraftIdentityShellValidationError(
            "Formulation is empty or exceeds the bounded shell length"
        )
    if text.count(marker) != 1:
        raise AircraftIdentityShellValidationError(
            "Formulation did not preserve exactly one Core substitution marker"
        )
    other_marker = (
        UNAVAILABLE_AIRCRAFT_MARKER
        if marker == AVAILABLE_AIRCRAFT_MARKER
        else AVAILABLE_AIRCRAFT_MARKER
    )
    if other_marker in text or "{{" in text.replace(marker, ""):
        raise AircraftIdentityShellValidationError(
            "Formulation introduced an unsupported substitution marker"
        )

    shell = text.replace(marker, "")
    lowered = shell.casefold()
    has_cyrillic = bool(re.search(r"[А-Яа-яЁё]", shell))
    if (language == "ru-RU" and not has_cyrillic) or (
        language == "en-US" and has_cyrillic
    ):
        raise AircraftIdentityShellValidationError(
            "Formulation did not follow the requested language"
        )
    if re.search(r"[\d/_+]", shell):
        raise AircraftIdentityShellValidationError(
            "Formulation introduced an identifier-like value outside the Core marker"
        )

    forbidden = {
        item.casefold()
        for profile in aircraft_knowledge.list_profiles()
        for item in {profile.aircraft_id, profile.display_name, *profile.aliases}
        if len(item.strip()) >= 3
    }
    if any(item in lowered for item in forbidden):
        raise AircraftIdentityShellValidationError(
            "Formulation introduced an aircraft identity outside the Core marker"
        )
    if result.raw_aircraft_id and result.raw_aircraft_id.casefold() in lowered:
        raise AircraftIdentityShellValidationError(
            "Formulation copied the raw DCS identity outside the Core marker"
        )
    if result.display_name and result.display_name.casefold() in lowered:
        raise AircraftIdentityShellValidationError(
            "Formulation copied the display identity outside the Core marker"
        )
    if _unsupported_second_claim(shell, language=language):
        raise AircraftIdentityShellValidationError(
            "Formulation introduced an unsupported additional factual claim"
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
            "Validated shell no longer contains exactly one Core marker"
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
            "Core aircraft substitution is unavailable"
        )
    final_text = validated_shell.replace(marker, replacement)
    if result.display_name and final_text.count(result.display_name) != 1:
        raise AircraftIdentityShellValidationError(
            "Final wording did not preserve the exact Core aircraft display identity"
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
    "MAX_AIRCRAFT_SHELL_LENGTH",
    "UNAVAILABLE_AIRCRAFT_MARKER",
    "aircraft_identity_marker",
    "bind_aircraft_identity_shell",
    "validate_aircraft_identity_shell",
    "validate_and_bind_aircraft_identity_shell",
]
