import ast
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from orion.communication_contracts import (
    COMPOSER_VERSION,
    COMPOSITION_SEPARATOR,
    MAX_ENVELOPE_CHARS,
    MAX_FINAL_TEXT_CHARS,
    MAX_FRAGMENT_CHARS,
    MAX_PROTECTED_FRAGMENTS,
    CommunicationContext,
    CommunicationDomain,
    CommunicationPriority,
    CommunicationProfileId,
    FinalizedCommunicationText,
    ProtectedOperationalFragment,
    ResponseCompositionPlan,
    UntrustedConversationalEnvelope,
)
from orion.phraseology_probe import synthetic_probe_cases
from orion.phraseology_renderer import PhraseologyRenderer, synthetic_pilot_ruleset
from orion.response_composer import (
    CompositionFailureCode as Code,
    ResponseComposer,
    ResponseCompositionError,
)


INTERACTION_ID = UUID("12345678-1234-5678-1234-567812345678")


def fragment(index: int = 0) -> ProtectedOperationalFragment:
    case = synthetic_probe_cases()[index]
    return PhraseologyRenderer(synthetic_pilot_ruleset()).render(
        case.unit, case.context
    )


def with_text(text: str) -> ProtectedOperationalFragment:
    return ProtectedOperationalFragment.model_validate(
        {**fragment().model_dump(), "text": text}
    )


def plan(**changes: object) -> ResponseCompositionPlan:
    fields: dict[str, object] = {
        "interaction_id": INTERACTION_ID,
        "communication": synthetic_probe_cases()[0].context,
        "priority": CommunicationPriority.IMPORTANT,
        "protected_fragments": (fragment(),),
    }
    fields.update(changes)
    return ResponseCompositionPlan.model_validate(fields)


def failure(value: ResponseCompositionPlan, code: Code) -> None:
    before = value.model_dump(warnings=False)
    with pytest.raises(ResponseCompositionError) as caught:
        ResponseComposer().compose(value)
    assert caught.value.code is code
    assert str(caught.value) == code.value
    assert caught.value.__suppress_context__ or caught.value.__context__ is None
    assert value.model_dump(warnings=False) == before


def test_protected_only_preserves_original_identity() -> None:
    source = plan()
    result = ResponseComposer().compose(source)
    assert result.text == "Fly heading one three seven deg."
    assert result.protected_fragments[0] is source.protected_fragments[0]
    assert result.envelope is None


def test_envelope_plus_one_keeps_untrusted_original() -> None:
    envelope = UntrustedConversationalEnvelope(text="Добрый день ещё раз.")
    result = ResponseComposer().compose(plan(envelope=envelope))
    assert result.text == "Добрый день ещё раз. Fly heading one three seven deg."
    assert result.envelope is envelope
    assert result.envelope is not None
    assert result.envelope.authoritative is False and result.envelope.droppable is True
    assert "authoritative" not in type(result).model_fields


def test_multiple_fragments_and_envelope_use_exact_order_and_separator() -> None:
    pieces = (fragment(2), fragment(0), fragment(1))
    source = plan(
        protected_fragments=pieces,
        envelope=UntrustedConversationalEnvelope(text="Hello."),
    )
    result = ResponseComposer().compose(source)
    assert (
        result.text
        == "Hello. Maintain speed 286 kn. Fly heading one three seven deg. Maintain altitude 12450 ft."
    )
    assert result.protected_fragments == pieces
    assert COMPOSITION_SEPARATOR == " "


def test_multiple_protected_without_envelope_are_not_sorted() -> None:
    result = ResponseComposer().compose(
        plan(protected_fragments=(fragment(1), fragment(0)))
    )
    assert result.text == "Maintain altitude 12450 ft. Fly heading one three seven deg."


def test_unicode_whitespace_punctuation_and_utf8_are_not_normalized() -> None:
    text = "Курс  e\u0301 — ０１５７\tMHz.\nDo NOT alter!"
    piece = with_text(text)
    result = ResponseComposer().compose(plan(protected_fragments=(piece,)))
    assert result.text == piece.text == text
    assert (
        result.text.encode("utf-8")
        == piece.text.encode("utf-8")
        == text.encode("utf-8")
    )


def test_all_pilot_values_sign_units_osu_and_provenance_survive() -> None:
    for index, case in enumerate(synthetic_probe_cases()):
        piece = fragment(index)
        source = plan(communication=case.context, protected_fragments=(piece,))
        result = ResponseComposer().compose(source)
        assert result.text == case.expected_text
        assert result.text.encode("utf-8") == piece.text.encode("utf-8")
        assert result.protected_fragments[0].semantic_unit is piece.semantic_unit
        assert (
            result.protected_fragments[0].semantic_unit.protected_values
            == case.unit.protected_values
        )
        assert result.provenance == case.unit.provenance
        assert result.provenance[0] is piece.semantic_unit.provenance[0]
    assert fragment(5).semantic_unit.protected_values[0].value == "0157"
    assert fragment(8).semantic_unit.protected_values[0].value == -850


def test_provenance_order_duplicates_and_empty_sources_are_not_rewritten() -> None:
    first = fragment()
    second = ProtectedOperationalFragment.model_validate(
        {**first.model_dump(), "text": "Different fixture."}
    )
    result = ResponseComposer().compose(plan(protected_fragments=(first, second)))
    assert result.provenance == first.semantic_unit.provenance * 2
    empty_unit = first.semantic_unit.model_copy(update={"provenance": ()})
    empty = first.model_copy(update={"semantic_unit": empty_unit})
    assert (
        ResponseComposer().compose(plan(protected_fragments=(empty,))).provenance == ()
    )


def test_context_and_interaction_id_are_original_not_generated() -> None:
    source = plan()
    result = ResponseComposer().compose(source)
    assert result.context is source.communication
    assert result.interaction_id == INTERACTION_ID
    assert result.context.model_dump() == source.communication.model_dump()
    assert "session_id" not in type(result).model_fields
    assert "turn_id" not in type(result).model_fields


def test_all_priorities_and_explicit_suppression() -> None:
    for priority in CommunicationPriority:
        original = fragment()
        piece = original.model_copy(
            update={
                "semantic_unit": original.semantic_unit.model_copy(
                    update={"priority": priority}
                )
            }
        )
        envelope = (
            None
            if priority is CommunicationPriority.IMMEDIATE
            else UntrustedConversationalEnvelope(text="Hello.")
        )
        source = plan(
            priority=priority,
            protected_fragments=(piece,),
            envelope=envelope,
            suppress_conversational_envelope=True,
        )
        result = ResponseComposer().compose(source)
        assert result.priority is priority
        assert result.text == piece.text
        assert result.suppress_conversational_envelope is True
        assert (
            result.envelope is envelope
        )  # preserved as suppressed structure, never emitted


def test_non_immediate_unsuppressed_envelopes_are_included() -> None:
    for priority in (
        CommunicationPriority.ROUTINE,
        CommunicationPriority.IMPORTANT,
        CommunicationPriority.URGENT,
    ):
        piece = fragment()
        piece = piece.model_copy(
            update={
                "semantic_unit": piece.semantic_unit.model_copy(
                    update={"priority": priority}
                )
            }
        )
        result = ResponseComposer().compose(
            plan(
                priority=priority,
                protected_fragments=(piece,),
                envelope=UntrustedConversationalEnvelope(text="Hello."),
            )
        )
        assert result.text == "Hello. " + piece.text


def test_malformed_immediate_is_rejected_even_with_unchecked_copy() -> None:
    source = plan()
    for changes in (
        {"priority": CommunicationPriority.IMMEDIATE},
        {
            "priority": CommunicationPriority.IMMEDIATE,
            "suppress_conversational_envelope": True,
            "envelope": UntrustedConversationalEnvelope(text="SECRET"),
        },
    ):
        with pytest.raises(ValidationError):
            plan(**changes)
        failure(source.model_copy(update=changes), Code.INVALID_PLAN)


def test_structural_duplicate_not_identity_is_rejected() -> None:
    piece = fragment()
    copy = ProtectedOperationalFragment.model_validate(piece.model_dump())
    assert copy is not piece and copy == piece
    failure(plan(protected_fragments=(piece, copy)), Code.DUPLICATE_FRAGMENT)


def test_identical_text_different_osu_or_renderer_is_not_duplicate() -> None:
    first = fragment()
    for second in (
        first.model_copy(update={"renderer_version": "synthetic-different-version"}),
        first.model_copy(
            update={
                "semantic_unit": first.semantic_unit.model_copy(
                    update={"provenance": ()}
                )
            }
        ),
        first.model_copy(
            update={
                "semantic_unit": first.semantic_unit.model_copy(
                    update={"status": "different_fixture"}
                )
            }
        ),
    ):
        result = ResponseComposer().compose(plan(protected_fragments=(first, second)))
        assert result.text == first.text + " " + first.text
        assert len(result.protected_fragments) == 2


def test_envelope_bounds_also_apply_when_suppressed() -> None:
    for suppress in (False, True):
        source = plan(
            envelope=UntrustedConversationalEnvelope(text="x" * MAX_ENVELOPE_CHARS),
            suppress_conversational_envelope=suppress,
        )
        result = ResponseComposer().compose(source)
        assert result.envelope is source.envelope
        failure(
            plan(
                envelope=UntrustedConversationalEnvelope(
                    text="x" * (MAX_ENVELOPE_CHARS + 1)
                ),
                suppress_conversational_envelope=suppress,
            ),
            Code.ENVELOPE_TOO_LARGE,
        )


def test_fragment_count_bounds() -> None:
    pieces = tuple(
        with_text(f"Fixture {index}.") for index in range(MAX_PROTECTED_FRAGMENTS + 1)
    )
    assert (
        len(
            ResponseComposer()
            .compose(plan(protected_fragments=pieces[:-1]))
            .protected_fragments
        )
        == 8
    )
    failure(plan(protected_fragments=pieces), Code.TOO_MANY_FRAGMENTS)


def test_fragment_size_bounds_without_truncation() -> None:
    piece = with_text("x" * MAX_FRAGMENT_CHARS)
    assert (
        ResponseComposer().compose(plan(protected_fragments=(piece,))).text
        == piece.text
    )
    failure(
        plan(protected_fragments=(with_text("x" * (MAX_FRAGMENT_CHARS + 1)),)),
        Code.FRAGMENT_TOO_LARGE,
    )


def test_final_text_boundary_and_overflow_include_separators() -> None:
    # 1024 + 1024 + 1024 + 1021 + three ASCII spaces = 4096.
    pieces = (
        with_text("a" * 1024),
        with_text("b" * 1024),
        with_text("c" * 1024),
        with_text("d" * 1021),
    )
    result = ResponseComposer().compose(plan(protected_fragments=pieces))
    assert len(result.text) == MAX_FINAL_TEXT_CHARS == 4096
    assert result.text == " ".join(piece.text for piece in pieces)
    failure(
        plan(protected_fragments=(*pieces[:-1], with_text("d" * 1022))),
        Code.FINAL_TEXT_TOO_LARGE,
    )


def test_bounds_are_small_explicit_stage_local_defaults() -> None:
    assert (
        MAX_ENVELOPE_CHARS,
        MAX_PROTECTED_FRAGMENTS,
        MAX_FRAGMENT_CHARS,
        MAX_FINAL_TEXT_CHARS,
    ) == (512, 8, 1024, 4096)


def test_nonempty_advisory_is_typed_rejection_never_ignored() -> None:
    failure(plan(advisory=("SECRET advisory",)), Code.UNSUPPORTED_ADVISORY)
    assert ResponseComposer().compose(plan(advisory=())).text == fragment().text


def test_domain_mismatch_in_any_fragment_is_rejected() -> None:
    failure(plan(protected_fragments=(fragment(), fragment(5))), Code.DOMAIN_MISMATCH)
    context = synthetic_probe_cases()[0].context.model_copy(
        update={"domain": CommunicationDomain.GENERAL}
    )
    failure(plan(communication=context), Code.DOMAIN_MISMATCH)


def test_priority_mismatch_is_not_aggregated_or_promoted() -> None:
    failure(plan(priority=CommunicationPriority.URGENT), Code.PRIORITY_MISMATCH)


def test_missing_render_context_witness_is_not_inferred_from_wording() -> None:
    for language in (None, "ru-RU", "en-US"):
        context = CommunicationContext(
            profile_id=CommunicationProfileId.FAA_US,
            domain=CommunicationDomain.NAVIGATION,
            operational_language=language,
        )
        result = ResponseComposer().compose(plan(communication=context))
        assert result.context is context
        assert result.text == fragment().text
    # No claim that this pairing is valid for presentation: fragment has no witness.
    assert "operational_language" not in ProtectedOperationalFragment.model_fields
    assert "profile_id" not in ProtectedOperationalFragment.model_fields


def test_envelope_only_and_empty_plans_fail_closed() -> None:
    failure(plan(protected_fragments=()), Code.EMPTY_OUTPUT)
    failure(
        plan(
            protected_fragments=(),
            envelope=UntrustedConversationalEnvelope(text="Hello."),
        ),
        Code.UNSUPPORTED_COMBINATION,
    )


def test_malformed_nested_envelope_is_revalidated_without_rewriting() -> None:
    for update in (
        {"text": ""},
        {"text": " SECRET "},
        {"authoritative": True},
        {"droppable": False},
        {"text": 42},
    ):
        envelope = UntrustedConversationalEnvelope(text="Hello.").model_copy(
            update=update
        )
        failure(plan().model_copy(update={"envelope": envelope}), Code.INVALID_PLAN)


def test_malformed_nested_fragment_or_osu_is_revalidated() -> None:
    piece = fragment()
    for malformed in (
        piece.model_copy(update={"text": " SECRET "}),
        piece.model_copy(update={"rendered_by_core": False}),
        piece.model_copy(
            update={
                "semantic_unit": piece.semantic_unit.model_copy(
                    update={
                        "protected_values": piece.semantic_unit.protected_values * 2
                    }
                )
            }
        ),
    ):
        failure(
            plan().model_copy(update={"protected_fragments": (malformed,)}),
            Code.INVALID_PLAN,
        )


def test_invalid_plan_type_and_unencodable_text_are_bounded_errors() -> None:
    with pytest.raises(ResponseCompositionError, match="^invalid_plan$"):
        ResponseComposer().compose(None)  # type: ignore[arg-type]
    malformed = fragment().model_copy(update={"text": "bad\ud800text"})
    failure(
        plan().model_copy(update={"protected_fragments": (malformed,)}),
        Code.INVALID_PLAN,
    )


def test_result_and_nested_inputs_are_immutable() -> None:
    source = plan(envelope=UntrustedConversationalEnvelope(text="Hello."))
    result = ResponseComposer().compose(source)
    with pytest.raises(ValidationError):
        result.text = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        result.context.domain = CommunicationDomain.ATC  # type: ignore[misc]
    with pytest.raises(ValidationError):
        result.protected_fragments[0].semantic_unit.protected_values[0].value = 0  # type: ignore[misc]
    assert result.envelope is not None
    with pytest.raises(ValidationError):
        result.envelope.text = "changed"  # type: ignore[misc]


def test_repeated_composition_is_identical_and_inputs_unchanged() -> None:
    source = plan(envelope=UntrustedConversationalEnvelope(text="Hello."))
    before = source.model_dump_json()
    composer = ResponseComposer()
    first = composer.compose(source)
    assert first == composer.compose(source)
    assert first.model_dump_json() == composer.compose(source).model_dump_json()
    assert source.model_dump_json() == before
    assert first.composer_version == COMPOSER_VERSION == "stage7b.composer.v1"


def test_finalized_contract_rejects_inconsistent_text_and_extra_metadata() -> None:
    result = ResponseComposer().compose(plan())
    for update in (
        {"text": "SECRET rewrite"},
        {"composer_version": "unknown"},
        {"provider": "forbidden"},
        {"protected_fragments": ()},
    ):
        with pytest.raises(ValidationError):
            FinalizedCommunicationText.model_validate({**result.model_dump(), **update})
    assert (
        FinalizedCommunicationText.model_validate_json(result.model_dump_json())
        == result
    )


def test_finalized_contract_rejects_malformed_immediate_suppression() -> None:
    result = ResponseComposer().compose(
        plan(envelope=UntrustedConversationalEnvelope(text="Hello."))
    )
    with pytest.raises(ValidationError):
        FinalizedCommunicationText.model_validate(
            {**result.model_dump(), "priority": CommunicationPriority.IMMEDIATE}
        )


def test_failure_does_not_leak_text_or_contaminate_next_call() -> None:
    instance = ResponseComposer()
    with pytest.raises(ResponseCompositionError) as caught:
        instance.compose(plan(advisory=("SECRET",)))
    assert "SECRET" not in str(caught.value)
    assert instance.compose(plan()) == ResponseComposer().compose(plan())


def test_offline_module_has_only_contract_and_validation_dependencies() -> None:
    path = Path(__file__).resolve().parents[1] / "orion" / "response_composer.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"__import__", "eval", "exec", "open", "getattr"}
    assert imports <= {
        "__future__",
        "enum",
        "pydantic",
        "orion.communication_contracts",
    }


def test_compose_never_opens_network_files_or_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins
    import socket
    import subprocess
    import urllib.request

    source = plan(envelope=UntrustedConversationalEnvelope(text="Hello."))

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Composer attempted external I/O")

    with monkeypatch.context() as isolated:
        isolated.setattr(socket, "create_connection", forbidden)
        isolated.setattr(socket.socket, "connect", forbidden)
        isolated.setattr(urllib.request, "urlopen", forbidden)
        isolated.setattr(subprocess, "Popen", forbidden)
        isolated.setattr(builtins, "open", forbidden)
        result = ResponseComposer().compose(source)
    assert result.text == "Hello. Fly heading one three seven deg."


def test_final_bound_counts_envelope_only_when_emitted() -> None:
    pieces = (
        with_text("a" * 1024),
        with_text("b" * 1024),
        with_text("c" * 1024),
        with_text("d" * 508),
    )
    envelope = UntrustedConversationalEnvelope(text="e" * 512)
    source = plan(protected_fragments=pieces, envelope=envelope)
    assert len(ResponseComposer().compose(source).text) == 4096
    overflow = plan(
        protected_fragments=(*pieces[:-1], with_text("d" * 509)), envelope=envelope
    )
    failure(overflow, Code.FINAL_TEXT_TOO_LARGE)
    suppressed = overflow.model_copy(update={"suppress_conversational_envelope": True})
    assert len(ResponseComposer().compose(suppressed).text) == 3584


def test_unchecked_incomplete_plan_is_rejected_without_raw_exception() -> None:
    failure(ResponseCompositionPlan.model_construct(), Code.INVALID_PLAN)
