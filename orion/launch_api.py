from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from orion.flight_readiness_api import router as flight_readiness_router
from orion.launch_profiles import (
    DcsLaunchPlan,
    DcsLaunchProfile,
    DcsLaunchProfileCreate,
    build_launch_plan,
    launch_profiles,
)
from orion.mission_activation_api import router as mission_activation_router
from orion.mission_catalog_api import router as mission_catalog_router
from orion.mission_preparation_api import router as mission_preparation_router

router = APIRouter()
launch_router = APIRouter(prefix="/v1/launch-profiles", tags=["DCS launch profiles"])


@launch_router.post("", response_model=DcsLaunchProfile, status_code=201)
def create_launch_profile(payload: DcsLaunchProfileCreate) -> DcsLaunchProfile:
    return launch_profiles.create(payload)


@launch_router.get("", response_model=list[DcsLaunchProfile])
def list_launch_profiles() -> list[DcsLaunchProfile]:
    return launch_profiles.list()


@launch_router.get("/{profile_id}", response_model=DcsLaunchProfile)
def get_launch_profile(profile_id: UUID) -> DcsLaunchProfile:
    profile = launch_profiles.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Launch profile not found")
    return profile


@launch_router.get("/{profile_id}/plan", response_model=DcsLaunchPlan)
def preview_launch_plan(profile_id: UUID) -> DcsLaunchPlan:
    profile = launch_profiles.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Launch profile not found")
    return build_launch_plan(profile)


@launch_router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_launch_profile(profile_id: UUID) -> Response:
    if not launch_profiles.delete(profile_id):
        raise HTTPException(status_code=404, detail="Launch profile not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


router.include_router(launch_router)
router.include_router(mission_catalog_router)
router.include_router(mission_preparation_router)
router.include_router(mission_activation_router)
router.include_router(flight_readiness_router)
