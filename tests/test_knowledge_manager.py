import pytest

from orion.knowledge_manager import (
    DocumentSection,
    DocumentState,
    KnowledgeCachePolicy,
    NetworkOfficialKnowledgeProvider,
    OfficialDocument,
    OfficialKnowledgeQuery,
)


def _manual() -> OfficialDocument:
    return OfficialDocument(
        document_id="fa18c-en",
        aircraft_id="fa-18c",
        title="F/A-18C Hornet Flight Manual",
        url="https://www.digitalcombatsimulator.com/en/downloads/documentation/",
    )


def _section(*, cached: bool = False) -> DocumentSection:
    return DocumentSection(
        section_id="fa18c-ins-alignment",
        document_id="fa18c-en",
        title="INS Alignment",
        summary="Stored heading and normal inertial navigation system alignment procedures",
        page_start=287,
        page_end=294,
        keywords={"ins", "alignment", "stored heading", "ifa"},
        cached=cached,
    )


def test_official_manual_is_registered_without_local_pdf() -> None:
    manager = NetworkOfficialKnowledgeProvider()
    document = manager.register(_manual())
    assert document.state is DocumentState.REGISTERED
    assert document.cached_size_bytes == 0
    assert manager.status().provider_id == "dcs-official-network"


def test_changed_hash_marks_document_for_reindex() -> None:
    manager = NetworkOfficialKnowledgeProvider()
    manager.register(_manual())
    manager.replace_sections("fa18c-en", [_section(cached=True)])
    manager.mark_checked("fa18c-en", content_hash="old")
    changed = manager.mark_checked("fa18c-en", content_hash="new")
    assert changed.state is DocumentState.CHANGED
    assert manager.list_sections("fa18c-en")[0].cached is False


def test_cache_limit_is_enforced() -> None:
    manager = NetworkOfficialKnowledgeProvider(
        KnowledgeCachePolicy(max_size_bytes=100 * 1024 * 1024)
    )
    manager.register(_manual())
    with pytest.raises(ValueError, match="cache limit"):
        manager.update_storage(
            "fa18c-en",
            index_size_bytes=1024,
            cached_size_bytes=101 * 1024 * 1024,
        )


def test_clear_cache_preserves_index() -> None:
    manager = NetworkOfficialKnowledgeProvider()
    manager.register(_manual())
    manager.replace_sections("fa18c-en", [_section(cached=True)])
    manager.update_storage("fa18c-en", index_size_bytes=4096, cached_size_bytes=8192)
    status = manager.clear_cache()
    assert status.total_cached_size_bytes == 0
    assert status.total_index_size_bytes == 4096
    assert status.indexed_section_count == 1
    assert manager.list_sections("fa18c-en")[0].cached is False


def test_search_returns_source_page_and_network_requirement() -> None:
    manager = NetworkOfficialKnowledgeProvider()
    manager.register(_manual())
    manager.replace_sections("fa18c-en", [_section()])
    result = manager.search(
        OfficialKnowledgeQuery(text="stored heading alignment", aircraft_id="fa-18c")
    )
    assert result.total == 1
    assert result.matches[0].section.page_start == 287
    assert result.matches[0].network_required is True
    assert result.matches[0].source_locator.endswith("#page=287")


def test_cached_section_can_be_used_without_network_fetch() -> None:
    manager = NetworkOfficialKnowledgeProvider()
    manager.register(_manual())
    manager.replace_sections("fa18c-en", [_section(cached=True)])
    result = manager.search(OfficialKnowledgeQuery(text="INS alignment"))
    assert result.matches[0].network_required is False
