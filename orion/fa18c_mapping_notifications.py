from __future__ import annotations

from dataclasses import dataclass

from orion.assistant_messages import AssistantMessageCreate, AssistantMessagePriority, AssistantMessageQueue, assistant_messages
from orion.fa18c_calibration_wizard import CalibrationSession


@dataclass(frozen=True)
class MappingNotification:
    correlation_id: str
    text: str


class HornetMappingNotifier:
    """Publishes hands-free cockpit-mapping prompts to the shared assistant queue."""

    def __init__(self, queue: AssistantMessageQueue = assistant_messages, language: str = "ru") -> None:
        self.queue = queue
        self.language = language

    def step_advanced(self, session: CalibrationSession, previous_step: str) -> MappingNotification:
        if session.active_step is None:
            text = (
                "Настройка распознавания кабины F/A-18C завершена. Перехожу к живой проверке данных кабины."
                if self.language == "ru"
                else "F/A-18C cockpit mapping setup is complete. Moving to live cockpit validation."
            )
            step_key = "complete"
        else:
            instruction = session.active_step.instruction_ru if self.language == "ru" else session.active_step.instruction_en
            text = (
                f"Шаг подтверждён автоматически. Следующий шаг: {instruction}"
                if self.language == "ru"
                else f"Step confirmed automatically. Next step: {instruction}"
            )
            step_key = session.active_step.key

        correlation_id = f"fa18c-mapping:{session.session_id}:{previous_step}:{step_key}"
        self.queue.enqueue(
            AssistantMessageCreate(
                text=text,
                source="fa18c-cockpit-mapping",
                session_id=session.session_id,
                correlation_id=correlation_id,
                priority=AssistantMessagePriority.NORMAL,
                speak=True,
                show_in_console=True,
                metadata={
                    "aircraft": "FA-18C_hornet",
                    "previous_step": previous_step,
                    "next_step": step_key,
                    "language": self.language,
                    "event": "mapping_step_advanced",
                },
            )
        )
        return MappingNotification(correlation_id=correlation_id, text=text)


hornet_mapping_notifier = HornetMappingNotifier()
