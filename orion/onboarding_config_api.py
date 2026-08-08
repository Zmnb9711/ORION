from fastapi import APIRouter

from orion.onboarding_config import OnboardingConfig, onboarding_config


router = APIRouter(prefix="/v1/onboarding-config", tags=["Onboarding"])


@router.get("", response_model=OnboardingConfig)
def get_onboarding_config() -> OnboardingConfig:
    return onboarding_config.get()


@router.put("", response_model=OnboardingConfig)
def set_onboarding_config(payload: OnboardingConfig) -> OnboardingConfig:
    return onboarding_config.set(payload)


@router.delete("", response_model=OnboardingConfig)
def reset_onboarding_config() -> OnboardingConfig:
    return onboarding_config.reset()
