from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from orion.dcs_installations import (
    DcsInstallation,
    DcsInstallationCreate,
    dcs_installations,
)

router = APIRouter(prefix="/v1/dcs-installations", tags=["DCS installations"])


@router.post("", response_model=DcsInstallation, status_code=201)
def add_dcs_installation(payload: DcsInstallationCreate) -> DcsInstallation:
    return dcs_installations.create(payload)


@router.get("", response_model=list[DcsInstallation])
def list_dcs_installations() -> list[DcsInstallation]:
    return dcs_installations.list()


@router.post("/{installation_id}/refresh", response_model=DcsInstallation)
def refresh_dcs_installation(installation_id: UUID) -> DcsInstallation:
    item = dcs_installations.refresh(installation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="DCS installation not found")
    return item


@router.delete("/{installation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dcs_installation(installation_id: UUID) -> Response:
    if not dcs_installations.delete(installation_id):
        raise HTTPException(status_code=404, detail="DCS installation not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
