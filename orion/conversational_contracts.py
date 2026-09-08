"""Level-0 only: exact-source binding, no fact/tool/action payloads."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictConversation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ConversationalRequest(StrictConversation):
    interaction_id: UUID
    source_text: str = Field(min_length=1, max_length=500, repr=False)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    language: Literal["ru-RU"] = "ru-RU"
    deadline: datetime


class SocialDraft(StrictConversation):
    kind: Literal["social_support"]
    text: str = Field(min_length=1, max_length=300, repr=False)


class ConversationalCandidate(StrictConversation):
    request: ConversationalRequest
    draft: SocialDraft
    provider_response_id: str = Field(min_length=1, max_length=200)
    terminal: Literal["completed"]
    provider_id: Literal["yandex.realtime.text"] = "yandex.realtime.text"


class FinalizedConversationalText(StrictConversation):
    candidate: ConversationalCandidate
    text: str = Field(min_length=1, max_length=300, repr=False)


class ConversationFailure(RuntimeError):
    """Only bounded categories cross the runtime/evidence boundary."""


class ConversationCleanupError(ConversationFailure):
    """An owned resource failed to terminate; preserve truthful host ERROR."""
