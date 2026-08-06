from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from orion.knowledge_manager import DocumentSection, knowledge_manager


class RetrievalState(StrEnum):
    QUEUED = "queued"
    FETCHING = "fetching"
    EXTRACTING = "extracting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FragmentRequest(BaseModel):
    document_id: str = Field(min_length=1, max_length=160)
    section_id: str = Field(min_length=1, max_length=200)
    requested_by: str | None = Field(default=None, max_length=160)


class RetrievedFragment(BaseModel):
    request_id: UUID = Field(default_factory=uuid4)
    document_id: str
    section_id: str
    page_start: int | None = None
    page_end: int | None = None
    source_locator: str
    state: RetrievalState = RetrievalState.QUEUED
    text: str | None = Field(default=None, max_length=20000)
    size_bytes: int = Field(default=0, ge=0)
    error: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class OfficialKnowledgeRetrievalQueue:
    """Tracks page-range retrieval without coupling ORION to a concrete HTTP/PDF backend."""

    def __init__(self) -> None:
        self._items: dict[UUID, RetrievedFragment] = {}
        self._by_section: dict[str, UUID] = {}
        self._lock = RLock()

    def request(self, payload: FragmentRequest) -> RetrievedFragment:
        documents = {item.document_id: item for item in knowledge_manager.list_documents()}
        document = documents.get(payload.document_id)
        if document is None:
            raise KeyError("Official document not found")
        sections = {item.section_id: item for item in knowledge_manager.list_sections(payload.document_id)}
        section = sections.get(payload.section_id)
        if section is None:
            raise KeyError("Indexed document section not found")

        with self._lock:
            previous_id = self._by_section.get(section.section_id)
            if previous_id is not None:
                previous = self._items[previous_id]
                if previous.state in {
                    RetrievalState.QUEUED,
                    RetrievalState.FETCHING,
                    RetrievalState.EXTRACTING,
                    RetrievalState.COMPLETED,
                }:
                    return previous.model_copy(deep=True)

            locator = str(document.url)
            if section.page_start is not None:
                locator = f"{locator}#page={section.page_start}"
            item = RetrievedFragment(
                document_id=document.document_id,
                section_id=section.section_id,
                page_start=section.page_start,
                page_end=section.page_end,
                source_locator=locator,
            )
            self._items[item.request_id] = item
            self._by_section[section.section_id] = item.request_id
            return item.model_copy(deep=True)

    def get(self, request_id: UUID) -> RetrievedFragment | None:
        with self._lock:
            item = self._items.get(request_id)
            return item.model_copy(deep=True) if item else None

    def list(self) -> list[RetrievedFragment]:
        with self._lock:
            return [
                item.model_copy(deep=True)
                for item in sorted(self._items.values(), key=lambda value: value.created_at, reverse=True)
            ]

    def set_state(self, request_id: UUID, state: RetrievalState) -> RetrievedFragment:
        with self._lock:
            item = self._items[request_id]
            if item.state in {RetrievalState.COMPLETED, RetrievalState.CANCELLED}:
                raise ValueError("Completed or cancelled retrieval cannot be restarted")
            item.state = state
            item.updated_at = datetime.now(UTC)
            return item.model_copy(deep=True)

    def complete(self, request_id: UUID, *, text: str, size_bytes: int) -> RetrievedFragment:
        if not text.strip():
            raise ValueError("Retrieved fragment text cannot be empty")
        if size_bytes < 0:
            raise ValueError("Fragment size cannot be negative")
        with self._lock:
            item = self._items[request_id]
            item.text = text.strip()
            item.size_bytes = size_bytes
            item.state = RetrievalState.COMPLETED
            item.error = None
            item.updated_at = datetime.now(UTC)
            self._mark_section_cached(item.section_id, item.text)
            document = next(
                document for document in knowledge_manager.list_documents() if document.document_id == item.document_id
            )
            knowledge_manager.update_storage(
                item.document_id,
                index_size_bytes=document.index_size_bytes,
                cached_size_bytes=document.cached_size_bytes + size_bytes,
            )
            return item.model_copy(deep=True)

    def fail(self, request_id: UUID, error: str) -> RetrievedFragment:
        with self._lock:
            item = self._items[request_id]
            item.state = RetrievalState.FAILED
            item.error = error
            item.updated_at = datetime.now(UTC)
            return item.model_copy(deep=True)

    def cancel(self, request_id: UUID) -> RetrievedFragment:
        with self._lock:
            item = self._items[request_id]
            if item.state is RetrievalState.COMPLETED:
                raise ValueError("Completed retrieval cannot be cancelled")
            item.state = RetrievalState.CANCELLED
            item.updated_at = datetime.now(UTC)
            return item.model_copy(deep=True)

    def _mark_section_cached(self, section_id: str, text: str) -> None:
        sections = knowledge_manager.list_sections()
        target = next(section for section in sections if section.section_id == section_id)
        updated = target.model_copy(update={"cached": True, "summary": text[:3000]})
        document_sections = [updated if item.section_id == section_id else item for item in sections if item.document_id == target.document_id]
        knowledge_manager.replace_sections(target.document_id, document_sections)


knowledge_retrieval = OfficialKnowledgeRetrievalQueue()
