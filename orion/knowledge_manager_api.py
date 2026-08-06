from fastapi import APIRouter, HTTPException

from orion.knowledge_manager import (
    KnowledgeCachePolicy,
    KnowledgeManagerStatus,
    OfficialDocument,
    knowledge_manager,
)

router = APIRouter(prefix="/v1/knowledge-manager", tags=["Knowledge Manager"])


@router.get("/documents", response_model=list[OfficialDocument])
def list_official_documents() -> list[OfficialDocument]:
    return knowledge_manager.list_documents()


@router.post("/documents", response_model=OfficialDocument, status_code=201)
def register_official_document(payload: OfficialDocument) -> OfficialDocument:
    return knowledge_manager.register(payload)


@router.get("/status", response_model=KnowledgeManagerStatus)
def get_knowledge_manager_status() -> KnowledgeManagerStatus:
    return knowledge_manager.status()


@router.put("/cache-policy", response_model=KnowledgeCachePolicy)
def update_cache_policy(payload: KnowledgeCachePolicy) -> KnowledgeCachePolicy:
    try:
        return knowledge_manager.configure(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/cache", response_model=KnowledgeManagerStatus)
def clear_knowledge_cache() -> KnowledgeManagerStatus:
    return knowledge_manager.clear_cache()
