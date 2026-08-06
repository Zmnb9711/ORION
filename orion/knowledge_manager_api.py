from fastapi import APIRouter, HTTPException

from orion.knowledge_manager import (
    DocumentSection,
    KnowledgeCachePolicy,
    KnowledgeManagerStatus,
    OfficialDocument,
    OfficialKnowledgeQuery,
    OfficialKnowledgeSearchResult,
    knowledge_manager,
)

router = APIRouter(prefix="/v1/knowledge-manager", tags=["Knowledge Manager"])


@router.get("/documents", response_model=list[OfficialDocument])
def list_official_documents() -> list[OfficialDocument]:
    return knowledge_manager.list_documents()


@router.post("/documents", response_model=OfficialDocument, status_code=201)
def register_official_document(payload: OfficialDocument) -> OfficialDocument:
    return knowledge_manager.register(payload)


@router.get("/documents/{document_id}/sections", response_model=list[DocumentSection])
def list_document_sections(document_id: str) -> list[DocumentSection]:
    return knowledge_manager.list_sections(document_id)


@router.put("/documents/{document_id}/sections", response_model=list[DocumentSection])
def replace_document_sections(document_id: str, payload: list[DocumentSection]) -> list[DocumentSection]:
    try:
        return knowledge_manager.replace_sections(document_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/search", response_model=OfficialKnowledgeSearchResult)
def search_official_knowledge(payload: OfficialKnowledgeQuery) -> OfficialKnowledgeSearchResult:
    return knowledge_manager.search(payload)


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
