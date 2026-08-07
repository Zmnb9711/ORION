from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from orion.fa18c_mapping_registry import HornetArgumentMapping, hornet_mapping_registry


router = APIRouter(prefix="/fa18c/mapping", tags=["F/A-18C Cockpit Mapping"])


class MappingUpdate(BaseModel):
    arguments: dict[str, int] = Field(default_factory=dict)
    confidence: dict[str, float] = Field(default_factory=dict)


@router.get("", response_model=HornetArgumentMapping)
def get_mapping() -> HornetArgumentMapping:
    mapping = hornet_mapping_registry.current()
    if mapping is None:
        raise HTTPException(status_code=404, detail="No validated F/A-18C cockpit mapping is stored")
    return mapping


@router.get("/dcs-command")
def get_dcs_mapping_command() -> dict[str, object]:
    mapping = hornet_mapping_registry.current()
    if mapping is None:
        raise HTTPException(status_code=404, detail="No validated F/A-18C cockpit mapping is stored")
    return mapping.dcs_command()


@router.put("", response_model=HornetArgumentMapping)
def save_mapping(payload: MappingUpdate) -> HornetArgumentMapping:
    try:
        return hornet_mapping_registry.save(payload.arguments, payload.confidence)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("", status_code=204)
def clear_mapping() -> None:
    hornet_mapping_registry.clear()
