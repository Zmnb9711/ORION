from fastapi import APIRouter, HTTPException, Response, status

from orion.active_dcs_installation import ActiveDcsInstallation, active_dcs_installation


router = APIRouter(prefix="/v1/dcs-active", tags=["DCS active installation"])


@router.get("", response_model=ActiveDcsInstallation)
def get_active_dcs_installation() -> ActiveDcsInstallation:
    selection = active_dcs_installation.get()
    if selection is None:
        raise HTTPException(status_code=404, detail="No active DCS installation selected")
    return selection


@router.put("", response_model=ActiveDcsInstallation)
def set_active_dcs_installation(selection: ActiveDcsInstallation) -> ActiveDcsInstallation:
    return active_dcs_installation.set(selection)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def clear_active_dcs_installation() -> Response:
    active_dcs_installation.clear()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
