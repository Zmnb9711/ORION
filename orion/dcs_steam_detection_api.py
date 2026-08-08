from fastapi import APIRouter

from orion.dcs_steam_detection import SteamDcsCandidate, discover_steam_dcs


router = APIRouter(prefix="/v1/dcs-detection", tags=["DCS detection"])


@router.get("/steam", response_model=list[SteamDcsCandidate])
def detect_steam_dcs() -> list[SteamDcsCandidate]:
    return discover_steam_dcs()
