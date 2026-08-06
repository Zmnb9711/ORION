from __future__ import annotations

import re
from threading import RLock

from pydantic import BaseModel, Field

from orion.knowledge_manager import DocumentState, knowledge_manager


class ManualSection(BaseModel):
    section_id: str = Field(min_length=1, max_length=200)
    document_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=400)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    keywords: set[str] = Field(default_factory=set)
    excerpt: str | None = Field(default=None, max_length=8000)
    cached: bool = False


class OfficialKnowledgeQuery(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    aircraft_id: str | None = Field(default=None, max_length=120)
    language: str | None = Field(default=None, max_length=20)
    limit: int = Field(default=5, ge=1, le=20)


class ManualSectionMatch(BaseModel):
    section: ManualSection
    document_title: str
    source_url: str
    score: float
    network_required: bool
    document_changed: bool


class OfficialKnowledgeSearchResult(BaseModel):
    found: bool
    matches: list[ManualSectionMatch] = Field(default_factory=list)
    message: str


_TOKEN_RE = re.compile(r"[\wа-яё/-]+", re.IGNORECASE)


class OfficialManualIndex:
    """Compact metadata index; full PDF content remains on the official DCS website."""

    def __init__(self) -> None:
        self._sections: dict[str, ManualSection] = {}
        self._lock = RLock()

    def upsert(self, section: ManualSection) -> ManualSection:
        documents = {item.document_id for item in knowledge_manager.list_documents()}
        if section.document_id not in documents:
            raise KeyError("Official document is not registered")
        with self._lock:
            self._sections[section.section_id] = section.model_copy(deep=True)
            return section.model_copy(deep=True)

    def replace_document(self, document_id: str, sections: list[ManualSection]) -> list[ManualSection]:
        if any(section.document_id != document_id for section in sections):
            raise ValueError("All sections must belong to the selected document")
        with self._lock:
            self._sections = {
                key: value for key, value in self._sections.items() if value.document_id != document_id
            }
        return [self.upsert(section) for section in sections]

    def list(self, document_id: str | None = None) -> list[ManualSection]:
        with self._lock:
            values = [
                item.model_copy(deep=True)
                for item in self._sections.values()
                if document_id is None or item.document_id == document_id
            ]
        return sorted(values, key=lambda item: (item.document_id, item.page_start or 0, item.title))

    def search(self, query: OfficialKnowledgeQuery) -> OfficialKnowledgeSearchResult:
        documents = {item.document_id: item for item in knowledge_manager.list_documents()}
        query_tokens = _tokens(query.text)
        matches: list[ManualSectionMatch] = []
        with self._lock:
            sections = list(self._sections.values())
        for section in sections:
            document = documents.get(section.document_id)
            if document is None:
                continue
            if query.aircraft_id and document.aircraft_id != query.aircraft_id:
                continue
            if query.language and document.language.casefold() != query.language.casefold():
                continue
            haystack = _tokens(" ".join((section.title, *section.keywords, section.excerpt or "")))
            overlap = query_tokens & haystack
            if not overlap:
                continue
            title_tokens = _tokens(section.title)
            score = len(overlap) / max(1, len(query_tokens))
            score += 0.5 * len(query_tokens & title_tokens) / max(1, len(query_tokens))
            matches.append(
                ManualSectionMatch(
                    section=section.model_copy(deep=True),
                    document_title=document.title,
                    source_url=str(document.url),
                    score=round(score, 4),
                    network_required=not section.cached or not bool(section.excerpt),
                    document_changed=document.state is DocumentState.CHANGED,
                )
            )
        matches.sort(key=lambda item: (-item.score, item.document_title, item.section.page_start or 0))
        matches = matches[: query.limit]
        if not matches:
            return OfficialKnowledgeSearchResult(
                found=False,
                message="No matching indexed section was found in registered official manuals",
            )
        return OfficialKnowledgeSearchResult(
            found=True,
            matches=matches,
            message="Matching official manual sections found",
        )


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_RE.findall(value) if len(token) > 1}


official_manual_index = OfficialManualIndex()
