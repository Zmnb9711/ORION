from orion.knowledge_manager import DocumentSection, NetworkOfficialKnowledgeProvider, OfficialDocument
from orion.knowledge_response_followup import (
    FollowUpState,
    KnowledgeFollowUpCreate,
    KnowledgeFollowUpQueue,
)
from orion.official_knowledge_retrieval import FragmentRequest, OfficialKnowledgeRetrievalQueue


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
    import orion.official_knowledge_retrieval as retrieval_module
    import orion.knowledge_response_followup as followup_module

    monkeypatch.setattr(retrieval_module, "knowledge_manager", manager)
    retrievals = OfficialKnowledgeRetrievalQueue()
    monkeypatch.setattr(followup_module, "knowledge_manager", manager)
    monkeypatch.setattr(followup_module, "knowledge_retrieval", retrievals)
    return manager, retrievals, KnowledgeFollowUpQueue()


def test_follow_up_waits_for_retrieval(monkeypatch) -> None:
    _, retrievals, queue = _seed(monkeypatch)
    retrieval = retrievals.request(FragmentRequest(document_id="fa18c-en", section_id="fa18c-ins"))
    item = queue.register(KnowledgeFollowUpCreate(retrieval_id=retrieval.request_id))
    assert item.state is FollowUpState.WAITING
    assert item.spoken_text is None


def test_completed_retrieval_creates_voice_ready_answer(monkeypatch) -> None:
    _, retrievals, queue = _seed(monkeypatch)
    retrieval = retrievals.request(FragmentRequest(document_id="fa18c-en", section_id="fa18c-ins"))
    item = queue.register(KnowledgeFollowUpCreate(retrieval_id=retrieval.request_id))
    retrievals.complete(retrieval.request_id, text="Set the INS knob to GND and select stored heading.", size_bytes=55)
    ready = queue.refresh(item.follow_up_id)
    assert ready.state is FollowUpState.READY
    assert "INS Alignment" in ready.spoken_text
    assert "страница 287" in ready.spoken_text
    assert ready.source_locator.endswith("#page=287")


def test_ready_follow_up_can_be_marked_delivered(monkeypatch) -> None:
    _, retrievals, queue = _seed(monkeypatch)
    retrieval = retrievals.request(FragmentRequest(document_id="fa18c-en", section_id="fa18c-ins"))
    item = queue.register(KnowledgeFollowUpCreate(retrieval_id=retrieval.request_id))
    retrievals.complete(retrieval.request_id, text="Official procedure text", size_bytes=23)
    ready = queue.refresh(item.follow_up_id)
    delivered = queue.mark_delivered(ready.follow_up_id)
    assert delivered.state is FollowUpState.DELIVERED


def test_failed_retrieval_produces_controlled_failure(monkeypatch) -> None:
    _, retrievals, queue = _seed(monkeypatch)
    retrieval = retrievals.request(FragmentRequest(document_id="fa18c-en", section_id="fa18c-ins"))
    item = queue.register(KnowledgeFollowUpCreate(retrieval_id=retrieval.request_id))
    retrievals.fail(retrieval.request_id, "network timeout")
    failed = queue.refresh(item.follow_up_id)
    assert failed.state is FollowUpState.FAILED
    assert failed.error == "network timeout"
