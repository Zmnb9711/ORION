"""Bounded offline Core composition, with no wording or domain decisions."""

from __future__ import annotations

from enum import StrEnum

from pydantic import ValidationError

from orion.communication_contracts import (
    COMPOSITION_SEPARATOR,
    MAX_ENVELOPE_CHARS,
    MAX_FINAL_TEXT_CHARS,
    MAX_FRAGMENT_CHARS,
    MAX_PROTECTED_FRAGMENTS,
    FinalizedCommunicationText,
    ResponseCompositionPlan,
)


class CompositionFailureCode(StrEnum):
    INVALID_PLAN = "invalid_plan"
    UNSUPPORTED_ADVISORY = "unsupported_advisory"
    EMPTY_OUTPUT = "empty_output"
    UNSUPPORTED_COMBINATION = "unsupported_combination"
    ENVELOPE_TOO_LARGE = "envelope_too_large"
    TOO_MANY_FRAGMENTS = "too_many_fragments"
    FRAGMENT_TOO_LARGE = "fragment_too_large"
    FINAL_TEXT_TOO_LARGE = "final_text_too_large"
    DUPLICATE_FRAGMENT = "duplicate_fragment"
    DOMAIN_MISMATCH = "domain_mismatch"
    PRIORITY_MISMATCH = "priority_mismatch"


class ResponseCompositionError(ValueError):
    """A bounded code only; no operational text or validation payload."""

    def __init__(self, code: CompositionFailureCode) -> None:
        self.code = code
        super().__init__(code.value)


class ResponseComposer:
    """Compose one protected plan without I/O, mutation, or provider round-trip."""

    def compose(self, plan: ResponseCompositionPlan) -> FinalizedCommunicationText:
        # Revalidate a snapshot, not the model instance (unchecked model_copy can
        # bypass Pydantic validation). Never replace originals with normalized data.
        try:
            if not isinstance(plan, ResponseCompositionPlan):
                raise ValueError
            snapshot = plan.model_dump(mode="python", warnings="error")
            validated = ResponseCompositionPlan.model_validate(snapshot, strict=True)
            if validated.model_dump(mode="python") != snapshot:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ResponseCompositionError(
                CompositionFailureCode.INVALID_PLAN
            ) from None

        code = CompositionFailureCode
        if plan.advisory:
            raise ResponseCompositionError(code.UNSUPPORTED_ADVISORY)
        fragments = plan.protected_fragments
        if not fragments:
            raise ResponseCompositionError(
                code.UNSUPPORTED_COMBINATION
                if plan.envelope is not None
                else code.EMPTY_OUTPUT
            )
        if plan.envelope is not None:
            # Suppression is not an escape from admission bounds/validation.
            if len(plan.envelope.text) > MAX_ENVELOPE_CHARS:
                raise ResponseCompositionError(code.ENVELOPE_TOO_LARGE)
        if len(fragments) > MAX_PROTECTED_FRAGMENTS:
            raise ResponseCompositionError(code.TOO_MANY_FRAGMENTS)
        for index, fragment in enumerate(fragments):
            if len(fragment.text) > MAX_FRAGMENT_CHARS:
                raise ResponseCompositionError(code.FRAGMENT_TOO_LARGE)
            if fragment.semantic_unit.domain != plan.communication.domain:
                raise ResponseCompositionError(code.DOMAIN_MISMATCH)
            if fragment.semantic_unit.priority != plan.priority:
                raise ResponseCompositionError(code.PRIORITY_MISMATCH)
            if fragment in fragments[:index]:
                raise ResponseCompositionError(code.DUPLICATE_FRAGMENT)
        # Fragments expose no profile/language witness. Do not infer it from text
        # or parse renderer_version as a surrogate render context.
        parts = [fragment.text for fragment in fragments]
        if plan.envelope is not None and not plan.suppress_conversational_envelope:
            parts.insert(0, plan.envelope.text)
        text = COMPOSITION_SEPARATOR.join(parts)
        if len(text) > MAX_FINAL_TEXT_CHARS:
            raise ResponseCompositionError(code.FINAL_TEXT_TOO_LARGE)
        try:
            text.encode("utf-8")
            return FinalizedCommunicationText(
                text=text,
                context=plan.communication,
                priority=plan.priority,
                interaction_id=plan.interaction_id,
                envelope=plan.envelope,
                protected_fragments=fragments,
                suppress_conversational_envelope=plan.suppress_conversational_envelope,
            )
        except (UnicodeError, ValidationError):
            raise ResponseCompositionError(code.INVALID_PLAN) from None
