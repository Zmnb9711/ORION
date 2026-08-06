from __future__ import annotations

from fastapi import APIRouter, HTTPException

from orion.mission_preparation import (
    MissionInspectionResult,
    MissionPreparationRequest,
    MissionPreparationResult,
    inspect_mission,
    prepare_mission,
)

router = APIRouter(prefix="/v1/mission-manager", tags=["Mission Manager"])


@router.post("/prepare", response_model=MissionPreparationResult, status_code=201)
def prepare_mission_copy(payload: MissionPreparationRequest) -> MissionPreparationResult:
    try:
        return prepare_mission(payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/inspect", response_model=MissionInspectionResult)
def inspect_mission_archive(mission_path: str) -> MissionInspectionResult:
    try:
        return inspect_mission(mission_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
