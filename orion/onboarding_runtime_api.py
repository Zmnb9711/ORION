from fastapi import APIRouter

from orion.onboarding_runtime import OnboardingRuntimeState, apply_onboarding_config, current_onboarding_runtime


router = APIRouter(prefix="/v1/onboarding-runtime", tags=["Onboarding"])


@router.post("/apply", response_model=OnboardingRuntimeState)
def apply_runtime() -> OnboardingRuntimeState:
    return apply_onboarding_config()


@router.get("", response_model=OnboardingRuntimeState)
def get_runtime() -> OnboardingRuntimeState:
    return current_onboarding_runtime()
