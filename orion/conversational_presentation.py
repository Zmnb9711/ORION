"""New typed admission only; existing streaming TTS/radio mechanics are borrowed."""
import asyncio
from datetime import UTC, datetime
import time
from typing import cast

from orion.communication_contracts import CommunicationDomain, CommunicationPriority, FinalizedCommunicationText
from orion.conversational_contracts import ConversationCleanupError, ConversationFailure, FinalizedConversationalText
from orion.conversational_core import ConversationalCore
from orion.informational_presentation import InformationalStreamingTts
from orion.protected_presentation import PresentationFailure, PresentationResult, tx_correlation
from orion.protected_streaming_presentation import StreamingProtectedPresentation
from orion.radio_contracts import RadioContext, RadioModulation
from orion.yandex_realtime_text_conversation import AiohttpConversationTransport, TextConversationProvider


class ConversationalPresentation(StreamingProtectedPresentation):
    def __init__(self, tts, router, *, authorize):
        super().__init__(tts, router)
        self.authorize = authorize

    async def present(self, finalized: object, radio: RadioContext) -> PresentationResult:
        tx = "invalid"
        try:
            if type(finalized) is not FinalizedConversationalText:
                raise ValueError("typed_conversation_only")
            raw = finalized.model_dump(mode="python", warnings="error")
            checked = FinalizedConversationalText.model_validate(raw, strict=True)
            if checked.model_dump() != raw or not self.authorize(checked):
                raise ValueError("conversation_not_admitted")
            identity = checked.candidate.request.interaction_id
            tx = tx_correlation(identity)
            context = RadioContext.model_validate(radio.model_dump(mode="python"), strict=True)
            if (context.tx_correlation_id != tx or context.interaction_id != identity
                or context.turn_id != str(identity) or context.session_id != "recovery-full-voice"
                or context.source_domain != CommunicationDomain.GENERAL
                or context.communication_priority != CommunicationPriority.ROUTINE
                or context.provenance):
                raise ValueError("conversation_radio_binding")
        except Exception:
            return PresentationResult(tx, "failed", True, PresentationFailure.INVALID_FINALIZED_TEXT)
        return await self._admit_validated(cast(FinalizedCommunicationText, checked), context)

    async def _run(self, finalized, context, operation):
        if not self.authorize(finalized):
            result = PresentationResult(str(context.tx_correlation_id), "failed", True, PresentationFailure.INVALID_FINALIZED_TEXT)
            operation.result = result
            return result
        return await super()._run(finalized, context, operation)

    async def cancel(self, tx):
        result = await super().cancel(tx)
        # Borrowed radio acknowledges abort asynchronously. Do not claim clean
        # shutdown before its terminal snapshot, or change the radio algorithm.
        limit = time.monotonic() + .4
        while not result.terminal and time.monotonic() < limit:
            await asyncio.sleep(.01)
            result = self.get(tx) or result
        if not result.terminal:
            raise ConversationCleanupError("conversation_radio_cancel_not_terminal")
        return result


class ConversationVoice:
    """Turn-scoped Conversation owner. No world/gateway/planner or global readiness.

    Invoked only after existing routes decline. Provider errors are turn-local;
    a non-terminated owned resource is a cleanup error, never false STOPPED.
    """
    def __init__(self, api_key, folder_id, endpoint, entity, *, observe=lambda _event, **_fields: None,
                 provider=None, tts=None):
        self.core = ConversationalCore()
        self.observe = observe
        self.endpoint, self.entity = endpoint, entity
        self.turn_id = None
        self.provider = provider or TextConversationProvider(
            lambda: AiohttpConversationTransport(api_key, folder_id), observe=self.emit)
        self.presentation = ConversationalPresentation(tts or InformationalStreamingTts(api_key,
            observe=lambda text: self.emit("tts_input", turn_id=self.turn_id, tts_input=text)),
            endpoint.radio_router, authorize=self.core.authorize)

    def emit(self, event, **fields):
        try:
            fields.setdefault("monotonic", time.monotonic())
            self.observe(event, **fields)
        except Exception:
            pass

    async def run(self, utterance, cancellation):
        identity = utterance.interaction_id
        self.turn_id = str(identity)
        stage = "eligibility"
        try:
            request = self.core.request(utterance)
            if request is None:
                return False
            self.emit("routing", turn_id=self.turn_id, source_text=request.source_text,
                source_sha256=request.source_sha256, route="CONVERSATION", route_source="LOCAL",
                conversation_provider_call_count=0, planner_call_count=0, tool_gateway_call_count=0)
            stage = "provider"
            candidate = await self.provider.generate(request, cancellation)
            if cancellation.cancelled:
                raise ConversationFailure("cancelled")
            stage = "admission"
            self.emit("candidate", turn_id=self.turn_id, candidate_text=candidate.draft.text)
            finalized = self.core.admit(candidate)
            self.emit("admission", turn_id=self.turn_id, status="accepted", finalized_text=finalized.text)
            context = RadioContext(tx_correlation_id=tx_correlation(identity), interaction_id=identity,
                turn_id=self.turn_id, session_id="recovery-full-voice", source_domain=CommunicationDomain.GENERAL,
                communication_priority=CommunicationPriority.ROUTINE, radio_entity=self.entity,
                target_frequency_hz=251000000, modulation=RadioModulation.AM)
            self.endpoint.response_valid_until = time.monotonic() + (request.deadline-datetime.now(UTC)).total_seconds()
            stage = "presentation"
            previous_marks, packet_before = self.endpoint.tx_marks, self.endpoint.packet_id
            # Cancel only this new owner using the existing presentation cancel
            # mechanics. No changed STOP rules or detached cleanup task.
            result = await self.provider._bounded(self.presentation.present(finalized, context), 40., cancellation, cleanup_budget=.6)
            marks = self.endpoint.tx_marks if self.endpoint.tx_marks is not previous_marks else {}
            self.emit("response_terminal", turn_id=self.turn_id, tx_id=tx_correlation(identity), status=result.state,
                frames=self.endpoint.packet_id-packet_before,
                failure_stage="presentation" if result.failure else None,
                failure_category=result.failure.value if result.failure else None,
                **{key: self.presentation.marks.get(key) for key in
                   ("tts_started", "tts_first_pcm", "tts_completed", "tts_pcm_bytes")},
                **{key: marks.get(key) for key in ("radio_first_frame", "radio_completed")})
            return True
        except ConversationCleanupError:
            self.emit("failed", turn_id=self.turn_id, failure_stage=stage, failure_category="cleanup_not_completed")
            raise
        except ConversationFailure as exc:
            self.emit("failed", turn_id=self.turn_id, failure_stage=stage, failure_category=str(exc))
            return True  # Fail closed: no fallback text, tools or Planner.
        except asyncio.CancelledError:
            self.emit("failed", turn_id=self.turn_id, failure_stage=stage, failure_category="cancelled")
            raise
        except Exception as exc:
            self.emit("failed", turn_id=self.turn_id, failure_stage=stage, failure_category=type(exc).__name__)
            return True  # Unexpected turn-local failure; shutdown still verifies ownership.

    async def shutdown(self):
        clean = await self.presentation.shutdown()
        if not clean or self.provider.owned:
            raise ConversationCleanupError("conversation_shutdown_not_completed")
