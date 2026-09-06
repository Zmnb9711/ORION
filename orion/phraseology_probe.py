"""Fixed, NON-NORMATIVE synthetic OSUs and exact offline wording checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json

from orion.communication_contracts import (
    CommunicationContext,
    CommunicationDomain,
    CommunicationPriority,
    CommunicationProfileId,
    OperationalSemanticUnit,
    ProtectedProvenance,
    ProtectedValue,
    ProtectedValueKind,
)
from orion.interaction_contracts import ContextReference
from orion.phraseology_renderer import (
    PILOT_SYNTHETIC_V1,
    RENDERER_VERSION,
    PhraseologyFailureCode,
    PhraseologyRenderError,
    PhraseologyRenderer,
    synthetic_pilot_ruleset,
)
from orion.world_model_contracts import WorldFactAuthority


@dataclass(frozen=True, slots=True)
class PhraseologyProbeCase:
    case_id: str
    unit: OperationalSemanticUnit
    context: CommunicationContext
    expected_text: str | None = None
    expected_failure: PhraseologyFailureCode | None = None


def synthetic_probe_cases() -> tuple[PhraseologyProbeCase, ...]:
    """Expected text is authored independently of the renderer's rule table."""

    def case(
        name: str,
        unit_type: str,
        meaning: str,
        expected: str,
        key: str | None = None,
        kind: ProtectedValueKind = ProtectedValueKind.GENERIC,
        value: str | int = "",
        measure: str | None = None,
        *,
        status: str = "issued",
        polarity: str = "positive",
        domain: CommunicationDomain = CommunicationDomain.NAVIGATION,
    ) -> PhraseologyProbeCase:
        return PhraseologyProbeCase(
            case_id=name,
            unit=OperationalSemanticUnit(
                unit_type=unit_type,
                semantic_meaning=meaning,
                domain=domain,
                priority=CommunicationPriority.IMPORTANT,
                status=status,
                polarity=polarity,
                protected_values=(
                    ProtectedValue(key=key, kind=kind, value=value, unit=measure),
                )
                if key
                else (),
                provenance=(
                    ProtectedProvenance(
                        source=ContextReference(
                            context_type="synthetic_probe", reference_id=name
                        ),
                        authority=WorldFactAuthority.AUTHORITATIVE,
                        generation=1,
                        domain_origin=domain,
                    ),
                ),
            ),
            context=CommunicationContext(
                profile_id=CommunicationProfileId.ICAO,
                domain=domain,
                input_language="ru-RU",
                operational_language="en-US",
                phraseology_snapshot_id=PILOT_SYNTHETIC_V1,
                phraseology_version=PILOT_SYNTHETIC_V1,
            ),
            expected_text=expected,
        )

    return (
        case(
            "heading",
            "navigation.heading",
            "navigation.heading_assignment",
            "Fly heading one three seven deg.",
            "ownship.heading_deg",
            ProtectedValueKind.HEADING,
            137,
            "deg",
        ),
        case(
            "altitude",
            "navigation.altitude",
            "navigation.altitude_instruction",
            "Maintain altitude 12450 ft.",
            "assigned.altitude",
            ProtectedValueKind.ALTITUDE,
            12450,
            "ft",
        ),
        case(
            "speed",
            "navigation.speed",
            "navigation.speed_instruction",
            "Maintain speed 286 kn.",
            "assigned.speed",
            ProtectedValueKind.SPEED,
            286,
            "kn",
        ),
        case(
            "frequency",
            "navigation.frequency",
            "navigation.frequency_information",
            "Frequency 264.500 MHz.",
            "radio.frequency",
            ProtectedValueKind.FREQUENCY,
            "264.500",
            "MHz",
            status="available",
        ),
        case(
            "tacan",
            "navigation.tacan",
            "navigation.tacan_information",
            "TACAN 44X.",
            "navigation.tacan",
            ProtectedValueKind.TACAN,
            "44X",
            status="available",
        ),
        case(
            "laser",
            "jtac.laser",
            "jtac.laser_information",
            "Laser code zero one five seven.",
            "jtac.laser_code",
            ProtectedValueKind.LASER_CODE,
            "0157",
            status="available",
            domain=CommunicationDomain.JTAC,
        ),
        case(
            "callsign",
            "navigation.callsign",
            "navigation.callsign_information",
            "Callsign Viper 2-1.",
            "speaker.callsign",
            ProtectedValueKind.CALLSIGN,
            "Viper 2-1",
            status="available",
        ),
        case(
            "distance",
            "navigation.distance",
            "navigation.distance_information",
            "Distance 63.0 NM.",
            "navigation.distance",
            ProtectedValueKind.GENERIC,
            "63.0",
            "NM",
            status="available",
        ),
        case(
            "negative",
            "navigation.correction",
            "navigation.altitude_correction",
            "Altitude correction -850 ft.",
            "navigation.altitude_correction",
            ProtectedValueKind.ALTITUDE,
            -850,
            "ft",
            polarity="negative",
        ),
        case(
            "unavailable",
            "navigation.heading",
            "navigation.heading_unavailable",
            "Heading unavailable.",
            status="unavailable",
            polarity="negative",
        ),
    )


@dataclass(frozen=True, slots=True)
class PhraseologyProbeResult:
    case_id: str
    passed: bool
    observed_text: str | None
    failure: PhraseologyFailureCode | None


@dataclass(frozen=True, slots=True)
class PhraseologyProbeReport:
    ruleset_version: str
    renderer_version: str
    results: tuple[PhraseologyProbeResult, ...]

    @property
    def passed(self) -> bool:
        return bool(self.results) and all(result.passed for result in self.results)


def run_probe(renderer: PhraseologyRenderer | None = None) -> PhraseologyProbeReport:
    """Evaluate ten literal outputs and four exact expected rejection codes."""

    selected = (
        renderer
        if renderer is not None
        else PhraseologyRenderer(synthetic_pilot_ruleset())
    )
    cases = synthetic_probe_cases()
    base = cases[0]
    failures = (
        (
            "profile",
            {"profile_id": CommunicationProfileId.FAA_US},
            PhraseologyFailureCode.UNSUPPORTED_PROFILE,
        ),
        (
            "domain",
            {"domain": CommunicationDomain.ATC},
            PhraseologyFailureCode.UNSUPPORTED_DOMAIN,
        ),
        (
            "language",
            {"operational_language": "ru-RU"},
            PhraseologyFailureCode.UNSUPPORTED_LANGUAGE,
        ),
        (
            "version",
            {"phraseology_version": "unknown-v1"},
            PhraseologyFailureCode.UNSUPPORTED_RULESET,
        ),
    )
    cases += tuple(
        PhraseologyProbeCase(
            case_id=f"reject-{name}",
            unit=base.unit,
            context=CommunicationContext.model_validate(
                {**base.context.model_dump(), **update}
            ),
            expected_failure=code,
        )
        for name, update, code in failures
    )
    results: list[PhraseologyProbeResult] = []
    for case in cases:
        try:
            fragment = selected.render(case.unit, case.context)
            passed = (
                case.expected_failure is None
                and fragment.text == case.expected_text
                and fragment.semantic_unit == case.unit
                and fragment.rendered_by_core
                and fragment.renderer_version
                == f"{RENDERER_VERSION}/{PILOT_SYNTHETIC_V1}"
            )
            results.append(
                PhraseologyProbeResult(case.case_id, passed, fragment.text, None)
            )
        except PhraseologyRenderError as exc:
            results.append(
                PhraseologyProbeResult(
                    case.case_id, exc.code == case.expected_failure, None, exc.code
                )
            )
    return PhraseologyProbeReport(PILOT_SYNTHETIC_V1, RENDERER_VERSION, tuple(results))


if __name__ == "__main__":
    report = run_probe()
    print(json.dumps({"passed": report.passed, **asdict(report)}, indent=2))
    raise SystemExit(0 if report.passed else 1)
