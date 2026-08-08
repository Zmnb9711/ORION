from __future__ import annotations

from pydantic import BaseModel

from orion.onboarding_config import OnboardingConfig, onboarding_config
from orion.onboarding_runtime import OnboardingRuntimeState, apply_onboarding_config


class StartupOnboardingResult(BaseModel):
    applied: bool
    reason: str
    config: OnboardingConfig
    runtime: OnboardingRuntimeState | None = None


def apply_completed_onboarding_at_startup() -> StartupOnboardingResult:
    """Apply persisted onboarding only after the user has completed the wizard.

    Incomplete onboarding data is intentionally treated as a draft and must not
    change live runtime settings during application startup.
    """

    config = onboarding_config.get()
    if not config.completed:
        return StartupOnboardingResult(
            applied=False,
            reason="Onboarding is not completed; persisted settings were not applied",
            config=config,
        )

    runtime = apply_onboarding_config(config)
    return StartupOnboardingResult(
        applied=True,
        reason="Completed onboarding configuration applied",
        config=config,
        runtime=runtime,
    )
