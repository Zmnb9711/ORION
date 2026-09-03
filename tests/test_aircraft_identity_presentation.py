from __future__ import annotations

from dataclasses import dataclass

import pytest

from orion.aircraft_identity_presentation import (
    AircraftIdentityShellValidationError,
    bind_aircraft_identity_shell,
    validate_aircraft_identity_shell,
    validate_and_bind_aircraft_identity_shell,
)


@dataclass(frozen=True)
class _Fact:
    status: str = "available"
    raw_aircraft_id: str | None = "FA-18C_hornet"
    display_name: str | None = "F/A-18C Hornet"


def test_provider_neutral_validator_preserves_natural_qwen_shell_and_core_binding() -> None:
    shell = validate_aircraft_identity_shell(
        "Вы сейчас находитесь в {{aircraft_identity}}.",
        _Fact(),
        language="ru-RU",
    )
    assert shell == "Вы сейчас находитесь в {{aircraft_identity}}."
    assert (
        bind_aircraft_identity_shell(shell, _Fact(), language="ru-RU")
        == "Вы сейчас находитесь в F/A-18C Hornet."
    )


@pytest.mark.parametrize(
    "text",
    (
        "Вы сейчас находитесь в самолёте.",
        "{{aircraft_identity}} и {{aircraft_identity}}.",
        "Вы в {{aircraft_unavailable}}.",
        "Your aircraft is {{aircraft_identity}}.",
        "Вы в {{aircraft_identity}} и топливо заканчивается.",
        "Вы в {{aircraft_identity}}; положение известно.",
        "Вы в {{aircraft_identity}} и летите курсом 137.",
        "Вы в FA-18C_hornet, то есть в {{aircraft_identity}}.",
        "Вы в F/A-18C Hornet, то есть в {{aircraft_identity}}.",
        f"Вы в {{aircraft_identity}} {'очень ' * 100}долго.",
    ),
)
def test_provider_neutral_validator_rejects_unsafe_or_unbounded_shells(text: str) -> None:
    with pytest.raises(AircraftIdentityShellValidationError):
        validate_and_bind_aircraft_identity_shell(text, _Fact(), language="ru-RU")


def test_unavailable_fact_binds_only_core_unavailable_wording() -> None:
    fact = _Fact(status="unavailable", raw_aircraft_id=None, display_name=None)
    assert validate_and_bind_aircraft_identity_shell(
        "К сожалению, {{aircraft_unavailable}}.",
        fact,
        language="ru-RU",
    ) == "К сожалению, данные о текущем самолёте из DCS недоступны."
