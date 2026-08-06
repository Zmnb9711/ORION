import pytest

from orion.knowledge_manager import (
    DocumentSection,
    NetworkOfficialKnowledgeProvider,
    OfficialDocument,
)
from orion.official_knowledge_retrieval import (
    FragmentRequest,
    OfficialKnowledgeRetrievalQueue,
    RetrievalState,
)


def _seed(monkeypatch):
    manager = NetworkOfficialKnowledgeProvider()
    manager.register(
        OfficialDocument(
            document_id="fa18c-en",
            aircraft_id="fa-18c",
            title="F/A-18C Hornet Flight Manual",
            url="https://www.digitalcombatsimulator.com/en/downloads/documentation/",
        )
    )
    manager.replace_sections(
        "fa18c-en",
        [
            DocumentSection(
                section_id="fa18c-ins",
                document_id="fa18c-en",
                title="INS Alignment",
                page_start=287,
                page_end=294,
                keywords={"ins", "alignment"},
            )
        ],
    )
    monkeypatch.setattr("orion.official_knowledge_retrieval.knowledge_manager", manager)
    return manager, OfficialKnowledgeRetrievalQueue()


def test_request_contains_page_locator(monkeypatch) -> None:
    _, queue = _seed(monkeypatch)
    item = queue.request(FragmentRequest(document_id="fa18c-en", section_id="fa18c-ins"))
    assert item.state is RetrievalState.QUEUED
    assert item.page_start == 287
    assert item.source_locator.endswith("#page=287")


def test_duplicate_active_request_is_reused(monkeypatch) -> None:
    _, queue = _seed(monkeypatch)
    first = queue.request(FragmentRequest(document_id="fa18c-en", section_id="fa18c-ins"))
    second = queue.request(FragmentRequest(document_id="fa18c-en", section_id="fa18c-ins"))
    assert second.request_id == first.request_id


def test_completed_fragment_marks_section_cached(monkeypatch) -> None:
    manager, queue = _seed(monkeypatch)
    item = queue.request(FragmentRequest(document_id="fa18c-en", section_id="fa18c-ins"))
    queue.set_state(item.request_id, RetrievalState.FETCHING)
    queue.set_state(item.request_id, RetrievalState.EXTRACTING)
    completed = queue.complete(item.request_id, text="Stored heading alignment procedure.", size_bytes=2048)
    assert completed.state is RetrievalState.COMPLETED
    assert completed.text == "Stored heading alignment procedure."
    assert manager.list_sections("fa18c-en")[0].cached is True
    assert manager.status().total_cached_size_bytes == 2048


def test_completed_request_cannot_be_cancelled(monkeypatch) -> None:
    _, queue = _seed(monkeypatch)
    item = queue.request(FragmentRequest(document_id="fa18c-en", section_id="fa18c-ins"))
    queue.complete(item.request_id, text="Cached text", size_bytes=10)
    with pytest.raises(ValueError, match="cannot be cancelled"):
        queue.cancel(item.request_id)


def test_failed_request_can_be_requested_again(monkeypatch) -> None:
    _, queue = _seed(monkeypatch)
    first = queue.request(FragmentRequest(document_id="fa18c-en", section_id="fa18c-ins"))
    queue.fail(first.request_id, "Network unavailable")
    second = queue.request(FragmentRequest(document_id="fa18c-en", section_id="fa18c-ins"))
    assert second.request_id != first.request_id
