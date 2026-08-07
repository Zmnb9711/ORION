from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from orion.components import InstallPlan, InstallPreset, OrionComponent, component_registry


router = APIRouter(prefix="/v1/components", tags=["Components"])


@router.get("", response_model=list[OrionComponent])
def list_components() -> list[OrionComponent]:
    return component_registry.list()


@router.get("/{component_id}", response_model=OrionComponent)
def get_component(component_id: str) -> OrionComponent:
    component = component_registry.get(component_id)
    if component is None:
        raise HTTPException(status_code=404, detail="Component not found")
    return component


@router.get("/plan/install", response_model=InstallPlan)
def plan_install(
    preset: InstallPreset = Query(default=InstallPreset.RECOMMENDED),
    component: list[str] = Query(default=[]),
) -> InstallPlan:
    try:
        requested = component if preset == InstallPreset.CUSTOM else None
        return component_registry.plan(preset, requested=requested)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown component: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
