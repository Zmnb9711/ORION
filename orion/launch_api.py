from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from orion.launch_profiles import (
    DcsLaunchPlan,
    DcsLaunchProfile,
    DcsLaunchProfileCreate,
    build_launch_plan,
    launch_profiles,
)

router = APIRouter(prefix="/v1/launch-profiles", tags=["DCS launch profiles"])


@router.post("", response_model=DcsLaunchProfile, status_code=201)
def create_launch_profile(payload: DcsLaunchProfileCreate) -> DcsLaunchProfile:
    return launch_profiles.create(payload)


@router.get("", response_model=list[DcsLaunchProfile])
def list_launch_profiles() -> list[DcsLaunchProfile]:
    return launch_profiles.list()


@router.get("/{profile_id}", response_model=DcsLaunchProfile)
def get_launch_profile(profile_id: UUID) -> DcsLaunchProfile:
    profile = launch_profiles.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Launch profile not found")
    return profile


@router.get("/{profile_id}/plan", response_model=DcsLaunchPlan)
def preview_launch_plan(profile_id: UUID) -> DcsLaunchPlan:
    profile = launch_profiles.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Launch profile not found")
    return build_launch_plan(profile)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_launch_profile(profile_id: UUID) -> Response:
    if not launch_profiles.delete(profile_id):
        raise HTTPException(status_code=404, detail="Launch profile not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
