from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Protocol

from pydantic import BaseModel, Field, HttpUrl


class KnowledgeLayer(StrEnum):
    OFFICIAL = "official"
    ORION_INTELLIGENCE = "orion_intelligence"
    PILOT_EXPERIENCE = "pilot_experience"


class DocumentState(StrEnum):
    REGISTERED = "registered"
    CHECK_REQUIRED = "check_required"
    CURRENT = "current"
    CHANGED = "changed"
    UNAVAILABLE = "unavailable"


class OfficialDocument(BaseModel):
    document_id: str = Field(min_length=1, max_length=160)
    aircraft_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=300)
    url: HttpUrl
    language: str = Field(default="en", min_length=2, max_length=20)
    publisher: str = Field(default="Eagle Dynamics", max_length=160)
    version: str | None = Field(default=None, max_length=120)
    content_hash: str | None = Field(default=None, max_length=160)
    state: DocumentState = DocumentState.REGISTERED
    last_checked_at: datetime | None = None
    index_size_bytes: int = Field(default=0, ge=0)
    cached_size_bytes: int = Field(default=0, ge=0)


class DocumentSection(BaseModel):
    section_id: str = Field(min_length=1, max_length=200)
    document_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=300)
    summary: str | None = Field(default=None, max_length=3000)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    keywords: set[str] = Field(default_factory=set)
    cached: bool = False


class OfficialKnowledgeQuery(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    aircraft_id: str | None = Field(default=None, max_length=120)
    language: str | None = Field(default=None, min_length=2, max_length=20)
    limit: int = Field(default=5, ge=1, le=20)


class OfficialKnowledgeMatch(BaseModel):
    document: OfficialDocument
    section: DocumentSection
    score: int = Field(ge=0)
    network_required: bool
    source_locator: str


class OfficialKnowledgeSearchResult(BaseModel):
    matches: list[OfficialKnowledgeMatch] = Field(default_factory=list)
    total: int = 0


class KnowledgeCachePolicy(BaseModel):
    max_size_bytes: int = Field(default=500 * 1024 * 1024, ge=100 * 1024 * 1024, le=2 * 1024 * 1024 * 1024)
    keep_frequently_used: bool = False
    remove_temporary_documents: bool = True
    automatic_update_checks: bool = True


class KnowledgeManagerStatus(BaseModel):
    provider_id: str
    policy: KnowledgeCachePolicy
    document_count: int
    indexed_section_count: int
    current_count: int
    changed_count: int
    unavailable_count: int
    total_index_size_bytes: int
    total_cached_size_bytes: int


class OfficialKnowledgeProvider(Protocol):
    provider_id: str

    def register(self, document: OfficialDocument) -> OfficialDocument: ...
    def list_documents(self) -> list[OfficialDocument]: ...
    def status(self) -> KnowledgeManagerStatus: ...


class NetworkOfficialKnowledgeProvider:
    """Metadata, section index and cache-control layer for official DCS manuals.

    Network fetching and PDF parsing remain behind this provider so storage and retrieval
    can later be replaced without changing Voice Core, AKL or Procedure Engine.
    """

    provider_id = "dcs-official-network"

    def __init__(self, policy: KnowledgeCachePolicy | None = None) -> None:
        self._policy = policy or KnowledgeCachePolicy()
        self._documents: dict[str, OfficialDocument] = {}
        self._sections: dict[str, DocumentSection] = {}
        self._lock = RLock()

    def register(self, document: OfficialDocument) -> OfficialDocument:
        with self._lock:
            self._documents[document.document_id] = document.model_copy(deep=True)
            return document.model_copy(deep=True)

    def list_documents(self) -> list[OfficialDocument]:
        with self._lock:
            return [item.model_copy(deep=True) for item in sorted(
                self._documents.values(), key=lambda value: (value.aircraft_id, value.language, value.title)
            )]

    def replace_sections(self, document_id: str, sections: list[DocumentSection]) -> list[DocumentSection]:
        with self._lock:
            if document_id not in self._documents:
                raise KeyError("Official document not found")
            invalid = [item.section_id for item in sections if item.document_id != document_id]
            if invalid:
                raise ValueError("All indexed sections must belong to the selected document")
            self._sections = {
                key: value
                for key, value in self._sections.items()
                if value.document_id != document_id
            }
            for section in sections:
                self._sections[section.section_id] = section.model_copy(deep=True)
            return self.list_sections(document_id)

    def list_sections(self, document_id: str | None = None) -> list[DocumentSection]:
        with self._lock:
            sections = [
                item.model_copy(deep=True)
                for item in self._sections.values()
                if document_id is None or item.document_id == document_id
            ]
            return sorted(sections, key=lambda item: (item.document_id, item.page_start or 0, item.title))

    def search(self, query: OfficialKnowledgeQuery) -> OfficialKnowledgeSearchResult:
        tokens = {token for token in query.text.casefold().split() if len(token) > 1}
        with self._lock:
            matches: list[OfficialKnowledgeMatch] = []
            for section in self._sections.values():
                document = self._documents.get(section.document_id)
                if document is None:
                    continue
                if query.aircraft_id and document.aircraft_id != query.aircraft_id:
                    continue
                if query.language and document.language.casefold() != query.language.casefold():
                    continue
                haystack = " ".join((section.title, section.summary or "", *section.keywords)).casefold()
                score = sum(3 if token in section.title.casefold() else 1 for token in tokens if token in haystack)
                if score == 0:
                    continue
                page = section.page_start
                locator = str(document.url)
                if page is not None:
                    locator = f"{locator}#page={page}"
                matches.append(
                    OfficialKnowledgeMatch(
                        document=document.model_copy(deep=True),
                        section=section.model_copy(deep=True),
                        score=score,
                        network_required=not section.cached,
                        source_locator=locator,
                    )
                )
            matches.sort(key=lambda item: (-item.score, item.document.aircraft_id, item.section.page_start or 0))
            selected = matches[: query.limit]
            return OfficialKnowledgeSearchResult(matches=selected, total=len(matches))

    def mark_checked(
        self,
        document_id: str,
        *,
        content_hash: str | None,
        version: str | None = None,
        available: bool = True,
    ) -> OfficialDocument:
        with self._lock:
            document = self._documents[document_id]
            old_hash = document.content_hash
            document.last_checked_at = datetime.now(UTC)
            document.version = version or document.version
            if not available:
                document.state = DocumentState.UNAVAILABLE
            elif old_hash is not None and content_hash is not None and old_hash != content_hash:
                document.state = DocumentState.CHANGED
                document.content_hash = content_hash
                for section in self._sections.values():
                    if section.document_id == document_id:
                        section.cached = False
            else:
                document.state = DocumentState.CURRENT
                document.content_hash = content_hash or old_hash
            return document.model_copy(deep=True)

    def update_storage(self, document_id: str, *, index_size_bytes: int, cached_size_bytes: int) -> OfficialDocument:
        if index_size_bytes < 0 or cached_size_bytes < 0:
            raise ValueError("Storage sizes cannot be negative")
        with self._lock:
            other_cache = sum(
                item.cached_size_bytes for key, item in self._documents.items() if key != document_id
            )
            if other_cache + cached_size_bytes > self._policy.max_size_bytes:
                raise ValueError("Knowledge cache limit would be exceeded")
            document = self._documents[document_id]
            document.index_size_bytes = index_size_bytes
            document.cached_size_bytes = cached_size_bytes
            return document.model_copy(deep=True)

    def configure(self, policy: KnowledgeCachePolicy) -> KnowledgeCachePolicy:
        with self._lock:
            current_cache = sum(item.cached_size_bytes for item in self._documents.values())
            if current_cache > policy.max_size_bytes:
                raise ValueError("New cache limit is below current cache usage")
            self._policy = policy.model_copy(deep=True)
            return self._policy.model_copy(deep=True)

    def clear_cache(self) -> KnowledgeManagerStatus:
        with self._lock:
            for document in self._documents.values():
                document.cached_size_bytes = 0
            for section in self._sections.values():
                section.cached = False
            return self.status()

    def status(self) -> KnowledgeManagerStatus:
        with self._lock:
            documents = list(self._documents.values())
            return KnowledgeManagerStatus(
                provider_id=self.provider_id,
                policy=self._policy.model_copy(deep=True),
                document_count=len(documents),
                indexed_section_count=len(self._sections),
                current_count=sum(item.state is DocumentState.CURRENT for item in documents),
                changed_count=sum(item.state is DocumentState.CHANGED for item in documents),
                unavailable_count=sum(item.state is DocumentState.UNAVAILABLE for item in documents),
                total_index_size_bytes=sum(item.index_size_bytes for item in documents),
                total_cached_size_bytes=sum(item.cached_size_bytes for item in documents),
            )


knowledge_manager = NetworkOfficialKnowledgeProvider()
