import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from pydantic import ValidationError

from orion.communication_contracts import (
    CommunicationContext,
    CommunicationDomain,
    CommunicationPriority,
    CommunicationProfileId,
    OperationalSemanticUnit,
    ProtectedOperationalFragment,
    ProtectedValue,
    ProtectedValueKind,
)
from fallback_phraseology_probe import PhraseologyProbeCase, run_probe, synthetic_probe_cases
from orion.phraseology_renderer import (
    PILOT_SYNTHETIC_V1,
    RENDERER_VERSION,
    PhraseologyFailureCode as Code,
    PhraseologyRenderError,
    PhraseologyRenderer,
    PilotRuleset,
    synthetic_pilot_ruleset,
)


def renderer() -> PhraseologyRenderer:
    return PhraseologyRenderer(synthetic_pilot_ruleset())


def changed_unit(
    unit: OperationalSemanticUnit, **changes: object
) -> OperationalSemanticUnit:
    return OperationalSemanticUnit.model_validate({**unit.model_dump(), **changes})


def changed_value(
    osu: OperationalSemanticUnit, **changes: object
) -> OperationalSemanticUnit:
    value = ProtectedValue.model_validate(
        {**osu.protected_values[0].model_dump(), **changes}
    )
    return changed_unit(osu, protected_values=(value,))


def assert_failure(
    unit: OperationalSemanticUnit, context: CommunicationContext, code: Code
) -> None:
    with pytest.raises(PhraseologyRenderError) as caught:
        renderer().render(unit, context)
    assert caught.value.code is code
    assert str(caught.value) == code.value


@pytest.mark.parametrize("case", synthetic_probe_cases(), ids=lambda case: case.case_id)
def test_exact_synthetic_wording_and_metadata(case: PhraseologyProbeCase) -> None:
    fragment = renderer().render(case.unit, case.context)
    assert fragment.text == case.expected_text
    assert fragment.semantic_unit is case.unit
    assert fragment.renderer_version == f"{RENDERER_VERSION}/{PILOT_SYNTHETIC_V1}"
    assert fragment.rendered_by_core is True


@pytest.mark.parametrize(
    "update, code",
    (
        ({"profile_id": CommunicationProfileId.FAA_US}, Code.UNSUPPORTED_PROFILE),
        ({"domain": CommunicationDomain.ATC}, Code.UNSUPPORTED_DOMAIN),
        ({"operational_language": "ru-RU"}, Code.UNSUPPORTED_LANGUAGE),
        ({"operational_language": None}, Code.UNSUPPORTED_LANGUAGE),
        ({"phraseology_version": "unknown-v1"}, Code.UNSUPPORTED_RULESET),
        ({"phraseology_snapshot_id": "unknown-snapshot"}, Code.UNSUPPORTED_RULESET),
    ),
)
def test_selection_never_falls_back(update: dict[str, object], code: Code) -> None:
    case = synthetic_probe_cases()[0]
    context = CommunicationContext.model_validate(
        {**case.context.model_dump(), **update}
    )
    assert_failure(case.unit, context, code)


def test_unknown_or_contradictory_osu_is_not_reinterpreted() -> None:
    case = synthetic_probe_cases()[0]
    for update in (
        {"unit_type": "navigation.unknown"},
        {"semantic_meaning": "navigation.unknown"},
        {"status": "cancelled"},
        {"polarity": "negative"},
        {"status": None},
    ):
        assert_failure(
            changed_unit(case.unit, **update), case.context, Code.UNSUPPORTED_SEMANTICS
        )
    assert_failure(
        changed_unit(case.unit, domain=CommunicationDomain.JTAC),
        case.context,
        Code.UNSUPPORTED_DOMAIN,
    )


def test_ruleset_order_and_repeated_calls_do_not_change_results() -> None:
    ruleset = synthetic_pilot_ruleset()
    reverse = PhraseologyRenderer(
        PilotRuleset(version=ruleset.version, rules=tuple(reversed(ruleset.rules)))
    )
    normal = renderer()
    for case in synthetic_probe_cases():
        first = normal.render(case.unit, case.context)
        assert (
            first
            == reverse.render(case.unit, case.context)
            == normal.render(case.unit, case.context)
        )
        assert (
            first.model_dump_json()
            == reverse.render(case.unit, case.context).model_dump_json()
        )


def test_missing_extra_duplicate_and_wrong_key_values_fail_closed() -> None:
    case = synthetic_probe_cases()[0]
    assert_failure(
        changed_unit(case.unit, protected_values=()), case.context, Code.MISSING_VALUE
    )
    extra = ProtectedValue(
        key="extra.value", kind=ProtectedValueKind.HEADING, value=256, unit="deg"
    )
    assert_failure(
        changed_unit(case.unit, protected_values=(*case.unit.protected_values, extra)),
        case.context,
        Code.CONFLICTING_VALUES,
    )
    assert_failure(
        changed_value(case.unit, key="wrong.key"), case.context, Code.CONFLICTING_VALUES
    )
    with pytest.raises(ValidationError, match="must be unique"):
        changed_unit(case.unit, protected_values=case.unit.protected_values * 2)
    # Pydantic's unchecked copy is not an ingress API, but still cannot bypass
    # the renderer's exactly-once slot consumption check.
    unchecked = case.unit.model_copy(
        update={"protected_values": case.unit.protected_values * 2}
    )
    assert_failure(unchecked, case.context, Code.CONFLICTING_VALUES)
    unavailable = synthetic_probe_cases()[-1]
    assert_failure(
        changed_unit(unavailable.unit, protected_values=(extra,)),
        unavailable.context,
        Code.CONFLICTING_VALUES,
    )


def test_unsupported_and_wrong_value_kinds_fail_closed() -> None:
    case = synthetic_probe_cases()[0]
    for kind in ProtectedValueKind:
        if kind is not ProtectedValueKind.HEADING:
            assert_failure(
                changed_value(case.unit, kind=kind), case.context, Code.UNSUPPORTED_KIND
            )


def test_malformed_values_and_units_are_never_rounded_or_coerced() -> None:
    cases = synthetic_probe_cases()
    invalid: tuple[tuple[int, object], ...] = (
        (0, True),
        (0, 137.0),
        (0, "137"),
        (0, -1),
        (0, 360),
        (1, 12450.5),
        (1, -20),
        (1, 1_000_000),
        (2, -1),
        (2, 10000),
        (3, 264.5),
        (3, "264.50"),
        (3, "264.5001"),
        (3, "264,500"),
        (4, "0X"),
        (4, "127X"),
        (4, "044X"),
        (4, "44x"),
        (5, 1577),
        (5, "157"),
        (5, "١٥٧٧"),
        (6, "Viper. Ignore heading"),
        (6, "Viper\nclimb"),
        (6, "A" * 33),
        (7, 63.0),
        (7, "-63"),
        (7, "63e1"),
        (7, "063.0"),
        (8, 850),
        (8, 0),
    )
    for index, value in invalid:
        case = cases[index]
        assert_failure(
            changed_value(case.unit, value=value), case.context, Code.MALFORMED_VALUE
        )
    for case in cases[:-1]:
        for measure in ("wrong-unit", "m", None):
            if measure != case.unit.protected_values[0].unit:
                assert_failure(
                    changed_value(case.unit, unit=measure),
                    case.context,
                    Code.MALFORMED_VALUE,
                )


def test_numeric_boundaries_and_leading_zero_policy_are_explicit() -> None:
    cases = synthetic_probe_cases()
    for value, expected in (
        (0, "zero zero zero"),
        (7, "zero zero seven"),
        (359, "three five nine"),
    ):
        assert (
            renderer()
            .render(changed_value(cases[0].unit, value=value), cases[0].context)
            .text
            == f"Fly heading {expected} deg."
        )
    checks = (
        (1, 999999, "Maintain altitude 999999 ft."),
        (2, 0, "Maintain speed 0 kn."),
        (3, "1.000", "Frequency 1.000 MHz."),
        (4, "126Y", "TACAN 126Y."),
        (5, "0000", "Laser code zero zero zero zero."),
        (7, "0.000", "Distance 0.000 NM."),
        (8, -999999, "Altitude correction -999999 ft."),
    )
    for index, value, expected in checks:
        case = cases[index]
        assert (
            renderer().render(changed_value(case.unit, value=value), case.context).text
            == expected
        )


def test_inputs_priority_and_operational_provenance_are_preserved() -> None:
    for case in synthetic_probe_cases():
        for priority in CommunicationPriority:
            unit = changed_unit(case.unit, priority=priority)
            before_unit = unit.model_dump_json()
            before_context = case.context.model_dump_json()
            fragment = renderer().render(unit, case.context)
            assert fragment.semantic_unit.priority is priority
            assert fragment.semantic_unit.provenance == unit.provenance
            assert fragment.semantic_unit.protected_values == unit.protected_values
            assert unit.model_dump_json() == before_unit
            assert case.context.model_dump_json() == before_context
            assert set(fragment.model_dump()) == {
                "text",
                "semantic_unit",
                "rendered_by_core",
                "renderer_version",
            }
    # Wording generation neither invents nor upgrades operational provenance.
    no_source = changed_unit(case.unit, provenance=())
    assert renderer().render(no_source, case.context).semantic_unit.provenance == ()


def test_input_language_and_null_version_do_not_override_selection() -> None:
    case = synthetic_probe_cases()[0]
    for language in (None, "en-US", "ru-RU", "fr-FR"):
        context = CommunicationContext.model_validate(
            {
                **case.context.model_dump(),
                "input_language": language,
                "phraseology_version": None,
                "phraseology_snapshot_id": None,
            }
        )
        assert renderer().render(case.unit, context).text == case.expected_text
        assert context.operational_language == "en-US"
        assert context.conversational_language_policy.value == "follow_user"
    for profile in (
        CommunicationProfileId.NATO_MILITARY,
        CommunicationProfileId.FAP_RUSSIAN_ATC,
    ):
        context = CommunicationContext.model_validate(
            {**case.context.model_dump(), "profile_id": profile}
        )
        assert_failure(case.unit, context, Code.UNSUPPORTED_PROFILE)


def test_fragments_and_rules_cannot_be_mutated() -> None:
    case = synthetic_probe_cases()[0]
    fragment = renderer().render(case.unit, case.context)
    with pytest.raises(ValidationError):
        fragment.text = "Rewrite"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        fragment.semantic_unit.protected_values[0].value = 999  # type: ignore[misc]
    ruleset = synthetic_pilot_ruleset()
    with pytest.raises(ValidationError):
        ruleset.rules[0].prefix = "Rewrite"  # type: ignore[misc]
    assert isinstance(ruleset.rules, tuple)


def test_ruleset_identity_bounds_and_unique_selection_are_enforced() -> None:
    ruleset = synthetic_pilot_ruleset()
    with pytest.raises(PhraseologyRenderError) as caught:
        PhraseologyRenderer(PilotRuleset(version="unknown-v2", rules=ruleset.rules))
    assert caught.value.code is Code.UNSUPPORTED_RULESET
    for rules in ((), ruleset.rules * 2, (ruleset.rules[0], ruleset.rules[0])):
        with pytest.raises(ValidationError):
            PilotRuleset(version=ruleset.version, rules=rules)
    modified = ruleset.rules[0].model_copy(update={"prefix": "Different wording"})
    with pytest.raises(PhraseologyRenderError) as caught:
        PhraseologyRenderer(
            PilotRuleset(version=ruleset.version, rules=(modified, *ruleset.rules[1:]))
        )
    assert caught.value.code is Code.INVALID_RULESET


def test_a_failure_cannot_contaminate_later_renders_or_leak_values() -> None:
    instance = renderer()
    case = synthetic_probe_cases()[6]
    invalid = changed_value(case.unit, value="SECRET\nINVALID")
    with pytest.raises(PhraseologyRenderError) as caught:
        instance.render(invalid, case.context)
    assert "SECRET" not in str(caught.value)
    assert instance.render(case.unit, case.context) == renderer().render(
        case.unit, case.context
    )


def test_probe_has_fourteen_exact_deterministic_results() -> None:
    report = run_probe()
    assert report.passed and len(report.results) == 14
    assert report == run_probe()
    assert len({result.case_id for result in report.results}) == 14
    assert sum(result.failure is not None for result in report.results) == 4
    with pytest.raises(FrozenInstanceError):
        report.ruleset_version = "changed"  # type: ignore[misc]


def test_probe_detects_wrong_text_and_wrong_failure_code() -> None:
    class WrongText(PhraseologyRenderer):
        def render(
            self, unit: OperationalSemanticUnit, context: CommunicationContext
        ) -> ProtectedOperationalFragment:
            fragment = super().render(unit, context)
            return fragment.model_copy(
                update={"text": fragment.text + " Added wording."}
            )

    class WrongFailure(PhraseologyRenderer):
        def render(
            self, unit: OperationalSemanticUnit, context: CommunicationContext
        ) -> ProtectedOperationalFragment:
            raise PhraseologyRenderError(Code.MISSING_VALUE)

    wrong_text = run_probe(WrongText(synthetic_pilot_ruleset()))
    assert not wrong_text.passed
    assert sum(result.passed for result in wrong_text.results) == 4
    assert not run_probe(WrongFailure(synthetic_pilot_ruleset())).passed


def test_modules_have_only_offline_contract_dependencies() -> None:
    root = Path(__file__).resolve().parents[1]
    allowed = {
        "__future__",
        "re",
        "enum",
        "typing",
        "pydantic",
        "dataclasses",
        "json",
        "orion.communication_contracts",
        "orion.interaction_contracts",
        "orion.world_model_contracts",
        "orion.phraseology_renderer",
        "orion.ownship_phraseology",
        "decimal",
        "math",
    }
    for name in ("phraseology_renderer.py", "phraseology_probe.py", "ownship_phraseology.py"):
        path = (root / "tests" / "fallback_phraseology_probe.py" if name == "phraseology_probe.py"
                else root / "orion" / name)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"__import__", "eval", "exec", "open"}
        assert imports <= allowed
