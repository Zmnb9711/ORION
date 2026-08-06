import pytest

from orion.knowledge_manager import (
    DocumentState,
    KnowledgeCachePolicy,
    NetworkOfficialKnowledgeProvider,
    OfficialDocument,
)


def _manual() -> OfficialDocument:
    return OfficialDocument(
        document_id="fa18c-en",
        aircraft_id="fa-18c",
        title="F/A-18C Hornet Flight Manual",
        url="https://www.digitalcombatsimulator.com/en/downloads/documentation/",
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
    manager.mark_checked("fa18c-en", content_hash="old")
    changed = manager.mark_checked("fa18c-en", content_hash="new")
    assert changed.state is DocumentState.CHANGED


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
    manager.update_storage("fa18c-en", index_size_bytes=4096, cached_size_bytes=8192)
    status = manager.clear_cache()
    assert status.total_cached_size_bytes == 0
    assert status.total_index_size_bytes == 4096
