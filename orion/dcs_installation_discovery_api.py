from fastapi import APIRouter, Query

from orion.dcs_installation_discovery import DcsDiscoveryResult, discover_dcs_installations
from orion.dcs_installations import DcsInstallationType


router = APIRouter(prefix="/v1/dcs-discovery", tags=["DCS discovery"])


@router.get("", response_model=DcsDiscoveryResult)
def discover_dcs(mode: DcsInstallationType = Query(default=DcsInstallationType.AUTO)) -> DcsDiscoveryResult:
    return discover_dcs_installations(mode=mode)
