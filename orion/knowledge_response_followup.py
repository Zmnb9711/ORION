from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from orion.knowledge_manager import knowledge_manager
from orion.official_knowledge_retrieval import RetrievalState, knowledge_retrieval


class FollowUpState(StrEnum):
    WAITING = "waiting"
    READY = "ready"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


class KnowledgeFollowUpCreate(BaseModel):
    retrieval_id: UUID
    command_id: UUID | None = None
    session_id: str | None = Field(default=None, max_length=160)
    language: str = Field(default="ru", min_length=2, max_length=20)


class KnowledgeFollowUp(BaseModel):
    follow_up_id: UUID = Field(default_factory=uuid4)
    retrieval_id: UUID
    command_id: UUID | None = None
    session_id: str | None = None
    state: FollowUpState = FollowUpState.WAITING
    spoken_text: str | None = Field(default=None, max_length=24000)
    source_locator: str | None = Field(default=None, max_length=2000)
    error: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KnowledgeFollowUpQueue:
    """Turns asynchronous manual retrievals into final voice-ready answers."""

    def __init__(self) -> None:
        self._items: dict[UUID, KnowledgeFollowUp] = {}
        self._by_retrieval: dict[UUID, UUID] = {}
        self._lock = RLock()

    def register(self, payload: KnowledgeFollowUpCreate) -> KnowledgeFollowUp:
        retrieval = knowledge_retrieval.get(payload.retrieval_id)
        if retrieval is None:
            raise KeyError("Knowledge retrieval not found")
        with self._lock:
            existing_id = self._by_retrieval.get(payload.retrieval_id)
            if existing_id is not None:
                return self._items[existing_id].model_copy(deep=True)
            item = KnowledgeFollowUp(
                retrieval_id=payload.retrieval_id,
                command_id=payload.command_id,
                session_id=payload.session_id,
            )
            self._items[item.follow_up_id] = item
            self._by_retrieval[payload.retrieval_id] = item.follow_up_id
        return self.refresh(item.follow_up_id, language=payload.language)

    def get(self, follow_up_id: UUID) -> KnowledgeFollowUp | None:
        with self._lock:
            item = self._items.get(follow_up_id)
            return item.model_copy(deep=True) if item else None

    def list(self, *, ready_only: bool = False) -> list[KnowledgeFollowUp]:
        with self._lock:
            values = list(self._items.values())
            if ready_only:
                values = [item for item in values if item.state is FollowUpState.READY]
            return [item.model_copy(deep=True) for item in sorted(values, key=lambda value: value.created_at)]

    def refresh(self, follow_up_id: UUID, *, language: str = "ru") -> KnowledgeFollowUp:
        with self._lock:
            item = self._items[follow_up_id]
            if item.state in {FollowUpState.DELIVERED, FollowUpState.CANCELLED}:
                return item.model_copy(deep=True)
            retrieval = knowledge_retrieval.get(item.retrieval_id)
            if retrieval is None:
                item.state = FollowUpState.FAILED
                item.error = "Knowledge retrieval no longer exists"
            elif retrieval.state is RetrievalState.COMPLETED:
                item.state = FollowUpState.READY
                item.source_locator = retrieval.source_locator
                item.spoken_text = self._compose_answer(retrieval.section_id, retrieval.text or "", language)
                item.error = None
            elif retrieval.state is RetrievalState.FAILED:
                item.state = FollowUpState.FAILED
                item.error = retrieval.error or "Official manual retrieval failed"
                item.spoken_text = "Не удалось получить раздел официального руководства."
            elif retrieval.state is RetrievalState.CANCELLED:
                item.state = FollowUpState.CANCELLED
                item.spoken_text = "Получение раздела официального руководства отменено."
            else:
                item.state = FollowUpState.WAITING
            item.updated_at = datetime.now(UTC)
            return item.model_copy(deep=True)

    def refresh_all(self, *, language: str = "ru") -> list[KnowledgeFollowUp]:
        with self._lock:
            ids = list(self._items)
        return [self.refresh(item_id, language=language) for item_id in ids]

    def mark_delivered(self, follow_up_id: UUID) -> KnowledgeFollowUp:
        with self._lock:
            item = self._items[follow_up_id]
            if item.state is not FollowUpState.READY:
                raise ValueError("Only a ready follow-up can be marked as delivered")
            item.state = FollowUpState.DELIVERED
            item.updated_at = datetime.now(UTC)
            return item.model_copy(deep=True)

    def _compose_answer(self, section_id: str, text: str, language: str) -> str:
        section = next((item for item in knowledge_manager.list_sections() if item.section_id == section_id), None)
        title = section.title if section else "официального руководства"
        page = f", страница {section.page_start}" if section and section.page_start else ""
        excerpt = " ".join(text.split())
        if len(excerpt) > 1800:
            excerpt = excerpt[:1797].rstrip() + "..."
        if language.casefold().startswith("en"):
            return f"According to the official manual, section {title}{page}: {excerpt}"
        return f"Согласно официальному руководству, раздел «{title}»{page}: {excerpt}"


knowledge_follow_ups = KnowledgeFollowUpQueue()
