from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from orion.assistant_messages import AssistantMessageState, assistant_messages
from orion.official_knowledge_retrieval import RetrievalState, knowledge_retrieval


class ConsoleActivityState(StrEnum):
    IDLE = "idle"
    WORKING = "working"
    RESPONSE_READY = "response_ready"
    DELIVERING = "delivering"
    ERROR = "error"


class ConsoleActivity(BaseModel):
    state: ConsoleActivityState
    title: str
    detail: str | None = None
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    retrieval_id: str | None = None
    message_id: str | None = None
    source_locator: str | None = None
    error: str | None = None


class FlightConsoleStatus(BaseModel):
    activity: ConsoleActivity
    queued_messages: int
    claimed_messages: int
    failed_messages: int
    active_retrievals: int
    failed_retrievals: int


_RETRIEVAL_PROGRESS = {
    RetrievalState.QUEUED: 10,
    RetrievalState.FETCHING: 45,
    RetrievalState.EXTRACTING: 80,
}


class FlightConsoleStatusService:
    """Builds one user-facing status from background knowledge and message pipelines."""

    def get_status(self) -> FlightConsoleStatus:
        messages = assistant_messages.list()
        retrievals = knowledge_retrieval.list()

        queued = [item for item in messages if item.state is AssistantMessageState.QUEUED]
        claimed = [item for item in messages if item.state is AssistantMessageState.CLAIMED]
        failed_messages = [item for item in messages if item.state is AssistantMessageState.FAILED]
        active_retrievals = [
            item
            for item in retrievals
            if item.state in {RetrievalState.QUEUED, RetrievalState.FETCHING, RetrievalState.EXTRACTING}
        ]
        failed_retrievals = [item for item in retrievals if item.state is RetrievalState.FAILED]

        activity = self._select_activity(
            queued=queued,
            claimed=claimed,
            failed_messages=failed_messages,
            active_retrievals=active_retrievals,
            failed_retrievals=failed_retrievals,
        )
        return FlightConsoleStatus(
            activity=activity,
            queued_messages=len(queued),
            claimed_messages=len(claimed),
            failed_messages=len(failed_messages),
            active_retrievals=len(active_retrievals),
            failed_retrievals=len(failed_retrievals),
        )

    def _select_activity(
        self,
        *,
        queued: list,
        claimed: list,
        failed_messages: list,
        active_retrievals: list,
        failed_retrievals: list,
    ) -> ConsoleActivity:
        if claimed:
            item = claimed[0]
            return ConsoleActivity(
                state=ConsoleActivityState.DELIVERING,
                title="ORION отвечает",
                detail=item.text,
                message_id=str(item.message_id),
                progress_percent=100,
            )
        if queued:
            item = queued[0]
            return ConsoleActivity(
                state=ConsoleActivityState.RESPONSE_READY,
                title="Ответ готов",
                detail=item.text,
                message_id=str(item.message_id),
                progress_percent=100,
            )
        if active_retrievals:
            item = active_retrievals[0]
            titles = {
                RetrievalState.QUEUED: "Запрос поставлен в очередь",
                RetrievalState.FETCHING: "Получаю официальное руководство",
                RetrievalState.EXTRACTING: "Извлекаю нужный раздел",
            }
            return ConsoleActivity(
                state=ConsoleActivityState.WORKING,
                title=titles[item.state],
                detail=f"Страницы {item.page_start or '?'}–{item.page_end or item.page_start or '?'}",
                progress_percent=_RETRIEVAL_PROGRESS[item.state],
                retrieval_id=str(item.request_id),
                source_locator=item.source_locator,
            )
        if failed_retrievals:
            item = failed_retrievals[0]
            return ConsoleActivity(
                state=ConsoleActivityState.ERROR,
                title="Не удалось получить руководство",
                detail=item.error,
                retrieval_id=str(item.request_id),
                source_locator=item.source_locator,
                error=item.error,
            )
        if failed_messages:
            item = failed_messages[0]
            return ConsoleActivity(
                state=ConsoleActivityState.ERROR,
                title="Ошибка доставки ответа",
                detail=item.error,
                message_id=str(item.message_id),
                error=item.error,
            )
        return ConsoleActivity(
            state=ConsoleActivityState.IDLE,
            title="AI готов",
            detail="Нет активных операций",
            progress_percent=0,
        )


flight_console_status = FlightConsoleStatusService()
