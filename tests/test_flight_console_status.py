from orion.assistant_messages import (
    AssistantMessageCreate,
    AssistantMessageQueue,
)
from orion.flight_console_status import (
    ConsoleActivityState,
    FlightConsoleStatusService,
)
import orion.flight_console_status as status_module


class EmptyRetrievalQueue:
    def list(self) -> list:
        return []


def test_idle_status_reports_ai_ready(monkeypatch) -> None:
    monkeypatch.setattr(status_module, "assistant_messages", AssistantMessageQueue())
    monkeypatch.setattr(status_module, "knowledge_retrieval", EmptyRetrievalQueue())

    status = FlightConsoleStatusService().get_status()

    assert status.activity.state is ConsoleActivityState.IDLE
    assert status.activity.title == "AI готов"
    assert status.queued_messages == 0


def test_queued_response_is_visible_to_console(monkeypatch) -> None:
    queue = AssistantMessageQueue()
    message = queue.enqueue(
        AssistantMessageCreate(
            text="Согласно руководству, раздел INS Alignment готов.",
            source="official-knowledge",
        )
    )
    monkeypatch.setattr(status_module, "assistant_messages", queue)
    monkeypatch.setattr(status_module, "knowledge_retrieval", EmptyRetrievalQueue())

    status = FlightConsoleStatusService().get_status()

    assert status.activity.state is ConsoleActivityState.RESPONSE_READY
    assert status.activity.message_id == str(message.message_id)
    assert status.queued_messages == 1


def test_claimed_response_has_delivery_status(monkeypatch) -> None:
    queue = AssistantMessageQueue()
    queue.enqueue(
        AssistantMessageCreate(
            text="Ответ передаётся в выбранное аудиоустройство.",
            source="tts",
        )
    )
    claimed = queue.claim_next("tts-output", speech_only=True)
    assert claimed is not None
    monkeypatch.setattr(status_module, "assistant_messages", queue)
    monkeypatch.setattr(status_module, "knowledge_retrieval", EmptyRetrievalQueue())

    status = FlightConsoleStatusService().get_status()

    assert status.activity.state is ConsoleActivityState.DELIVERING
    assert status.activity.message_id == str(claimed.message_id)
    assert status.claimed_messages == 1
