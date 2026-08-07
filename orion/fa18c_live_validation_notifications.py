from __future__ import annotations

from dataclasses import dataclass, field

from orion.assistant_messages import (
    AssistantMessage,
    AssistantMessageCreate,
    AssistantMessagePriority,
    AssistantMessageQueue,
    assistant_messages,
)
from orion.fa18c_live_validation import HornetLiveValidationSnapshot


@dataclass
class HornetLiveValidationNotifier:
    queue: AssistantMessageQueue = field(default_factory=lambda: assistant_messages)
    language: str = "ru"

    def __post_init__(self) -> None:
        self._was_validated = False
        self._mapping_version: str | None = None

    def observe(self, snapshot: HornetLiveValidationSnapshot) -> AssistantMessage | None:
        mapping_changed = snapshot.mapping_version != self._mapping_version
        if mapping_changed:
            self._mapping_version = snapshot.mapping_version
            self._was_validated = False

        if snapshot.validated and not self._was_validated:
            self._was_validated = True
            return self.queue.enqueue(
                AssistantMessageCreate(
                    text=self._ready_text(),
                    source="fa18c-live-validation",
                    correlation_id=f"fa18c-live-ready:{snapshot.mapping_version or 'unknown'}",
                    priority=AssistantMessagePriority.HIGH,
                    metadata={
                        "event": "ready_to_fly",
                        "mapping_version": snapshot.mapping_version,
                        "validated_samples": snapshot.consecutive_valid_samples,
                    },
                )
            )

        if not snapshot.validated and self._was_validated:
            self._was_validated = False
            missing = self._missing(snapshot)
            fingerprint = ",".join(missing) or snapshot.last_issue or "unknown"
            return self.queue.enqueue(
                AssistantMessageCreate(
                    text=self._lost_text(snapshot, missing),
                    source="fa18c-live-validation",
                    correlation_id=f"fa18c-live-lost:{snapshot.mapping_version or 'unknown'}:{fingerprint}",
                    priority=AssistantMessagePriority.HIGH,
                    metadata={
                        "event": "ready_to_fly_lost",
                        "mapping_version": snapshot.mapping_version,
                        "missing": fingerprint,
                    },
                )
            )

        return None

    def clear(self) -> None:
        self._was_validated = False
        self._mapping_version = None

    @staticmethod
    def _missing(snapshot: HornetLiveValidationSnapshot) -> list[str]:
        missing: list[str] = []
        if not snapshot.tacan_valid:
            missing.append("TACAN")
        if not snapshot.comm1_valid:
            missing.append("COMM1")
        if not snapshot.comm2_valid:
            missing.append("COMM2")
        return missing

    def _ready_text(self) -> str:
        if self.language == "en":
            return "F/A-18C live cockpit validation complete. ORION is Ready to Fly."
        return "Живая проверка кабины F/A-18C завершена. ORION готов к полёту — Ready to Fly."

    def _lost_text(self, snapshot: HornetLiveValidationSnapshot, missing: list[str]) -> str:
        details = ", ".join(missing)
        if self.language == "en":
            if details:
                return f"Ready to Fly status lost. Live cockpit validation no longer confirms: {details}."
            return f"Ready to Fly status lost. {snapshot.last_issue or 'Live cockpit validation is incomplete.'}"
        if details:
            return f"Статус Ready to Fly потерян. Живая проверка больше не подтверждает: {details}."
        return f"Статус Ready to Fly потерян. {snapshot.last_issue or 'Живая проверка кабины не завершена.'}"


hornet_live_validation_notifier = HornetLiveValidationNotifier()
