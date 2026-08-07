from fastapi import APIRouter, HTTPException, Query

from orion.fa18c_systems import (
    HornetProcedure,
    HornetProcedureId,
    HornetSystemId,
    HornetSystemTopic,
    fa18c_knowledge_pack,
)

router = APIRouter(prefix="/fa-18c", tags=["Aircraft Knowledge Layer - F/A-18C"])


@router.get("/systems", response_model=list[HornetSystemTopic])
def list_hornet_systems() -> list[HornetSystemTopic]:
    return fa18c_knowledge_pack.list_systems()


@router.get("/systems/{system_id}", response_model=HornetSystemTopic)
def get_hornet_system(system_id: HornetSystemId) -> HornetSystemTopic:
    item = fa18c_knowledge_pack.get_system(system_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Hornet system topic not found")
    return item


@router.get("/procedures", response_model=list[HornetProcedure])
def list_hornet_procedures() -> list[HornetProcedure]:
    return fa18c_knowledge_pack.list_procedures()


@router.get("/procedures/{procedure_id}", response_model=HornetProcedure)
def get_hornet_procedure(procedure_id: HornetProcedureId) -> HornetProcedure:
    item = fa18c_knowledge_pack.get_procedure(procedure_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Hornet procedure not found")
    return item


@router.get("/lookup")
def lookup_hornet_topic(q: str = Query(min_length=1, max_length=160)) -> dict:
    return fa18c_knowledge_pack.find(q)
