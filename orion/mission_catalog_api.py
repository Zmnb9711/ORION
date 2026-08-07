from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from orion.mission_catalog import (
    MissionRecord,
    MissionSearchRoot,
    MissionSource,
    default_search_roots,
    discover_missions,
)

router = APIRouter(prefix="/v1/mission-manager", tags=["mission-manager"])


class MissionDiscoveryRequest(BaseModel):
    saved_games_path: str | None = None
    dcs_installations: list[str] = Field(default_factory=list)
    custom_directories: list[str] = Field(default_factory=list)


@router.post("/discover", response_model=list[MissionRecord])
def discover(payload: MissionDiscoveryRequest) -> list[MissionRecord]:
    roots = default_search_roots(
        saved_games=Path(payload.saved_games_path) if payload.saved_games_path else None,
        dcs_installations=[Path(path) for path in payload.dcs_installations],
    )
    return discover_missions(
        roots,
        custom_directories=[Path(path) for path in payload.custom_directories],
    )


@router.get("/default-roots", response_model=list[dict[str, str]])
def get_default_roots() -> list[dict[str, str]]:
    return [
        {"path": str(root.path), "source": root.source.value}
        for root in default_search_roots()
    ]
