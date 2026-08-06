from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock

from pydantic import BaseModel, Field

from orion.voice_core import VoiceAgent


class VoiceConversationContext(BaseModel):
    session_id: str = Field(min_length=1, max_length=120)
    active_agent: VoiceAgent | None = None
    active_subject: str | None = None
    last_intent: str | None = None
    entities: dict[str, str] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class VoiceContextStore:
    def __init__(self) -> None:
        self._contexts: dict[str, VoiceConversationContext] = {}
        self._lock = RLock()

    def get(self, session_id: str) -> VoiceConversationContext:
        with self._lock:
            context = self._contexts.get(session_id)
            if context is None:
                context = VoiceConversationContext(session_id=session_id)
                self._contexts[session_id] = context
            return context.model_copy(deep=True)

    def update(
        self,
        session_id: str,
        *,
        agent: VoiceAgent | None = None,
        subject: str | None = None,
        intent: str | None = None,
        entities: dict[str, str] | None = None,
    ) -> VoiceConversationContext:
        with self._lock:
            context = self._contexts.get(session_id) or VoiceConversationContext(session_id=session_id)
            if agent is not None:
                context.active_agent = agent
            if subject is not None:
                context.active_subject = subject
            if intent is not None:
                context.last_intent = intent
            if entities:
                context.entities.update(entities)
            context.updated_at = datetime.now(UTC)
            self._contexts[session_id] = context
            return context.model_copy(deep=True)

    def clear(self, session_id: str) -> VoiceConversationContext:
        with self._lock:
            self._contexts.pop(session_id, None)
            return VoiceConversationContext(session_id=session_id)


voice_contexts = VoiceContextStore()
