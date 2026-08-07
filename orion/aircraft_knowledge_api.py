from fastapi import APIRouter, HTTPException, Query

from orion.aircraft_knowledge import (
    AircraftProfile,
    KnowledgeCategory,
    KnowledgeEntry,
    KnowledgeSearchQuery,
    KnowledgeSearchResult,
    KnowledgeSource,
    aircraft_knowledge,
)
from orion.fa18c_systems_api import router as fa18c_systems_router

router = APIRouter(prefix="/v1/aircraft-knowledge", tags=["Aircraft Knowledge Layer"])


@router.get("/profiles", response_model=list[AircraftProfile])
def list_aircraft_profiles() -> list[AircraftProfile]:
    return aircraft_knowledge.list_profiles()


@router.get("/profiles/{aircraft_id}", response_model=AircraftProfile)
def get_aircraft_profile(aircraft_id: str) -> AircraftProfile:
    profile = aircraft_knowledge.get_profile(aircraft_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Aircraft profile not found")
    return profile


@router.get("/profiles/{aircraft_id}/sources", response_model=list[KnowledgeSource])
def list_aircraft_sources(aircraft_id: str) -> list[KnowledgeSource]:
    if aircraft_knowledge.get_profile(aircraft_id) is None:
        raise HTTPException(status_code=404, detail="Aircraft profile not found")
    return aircraft_knowledge.list_sources(aircraft_id)


@router.get("/profiles/{aircraft_id}/entries", response_model=list[KnowledgeEntry])
def list_aircraft_entries(
    aircraft_id: str,
    category: KnowledgeCategory | None = Query(default=None),
) -> list[KnowledgeEntry]:
    if aircraft_knowledge.get_profile(aircraft_id) is None:
        raise HTTPException(status_code=404, detail="Aircraft profile not found")
    return aircraft_knowledge.list_entries(aircraft_id, category=category)


@router.post("/sources", response_model=KnowledgeSource, status_code=201)
def upsert_knowledge_source(payload: KnowledgeSource) -> KnowledgeSource:
    return aircraft_knowledge.upsert_source(payload)


@router.post("/entries", response_model=KnowledgeEntry, status_code=201)
def upsert_knowledge_entry(payload: KnowledgeEntry) -> KnowledgeEntry:
    try:
        return aircraft_knowledge.upsert_entry(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/search", response_model=KnowledgeSearchResult)
def search_aircraft_knowledge(payload: KnowledgeSearchQuery) -> KnowledgeSearchResult:
    return aircraft_knowledge.search(payload)


router.include_router(fa18c_systems_router)
