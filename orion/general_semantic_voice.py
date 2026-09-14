"""One admitted response using existing streaming presentation mechanics."""
from __future__ import annotations

from datetime import UTC, datetime
import asyncio
import time

from orion.communication_contracts import CommunicationDomain, CommunicationPriority
from orion.conversational_contracts import ConversationCleanupError
from orion.general_semantic_core import FinalizedGeneralText, GeneralSemanticCore, DialoguePlan, FactPlan, MixedPlan
from orion.informational_presentation import InformationalStreamingTts
from orion.protected_presentation import PresentationFailure, PresentationResult, tx_correlation
from orion.protected_streaming_presentation import StreamingProtectedPresentation
from orion.radio_contracts import RadioContext, RadioModulation


class GeneralPresentation(StreamingProtectedPresentation):
    def __init__(self, tts, router, *, core: GeneralSemanticCore):
        super().__init__(tts, router)
        self.core = core

    async def present(self, finalized: object, radio: RadioContext) -> PresentationResult:
        tx = "invalid"
        try:
            if type(finalized) is not FinalizedGeneralText:
                raise ValueError("general_typed_final_required")
            checked = FinalizedGeneralText.model_validate(finalized.model_dump(), strict=True)
            identity = checked.plan.request.interaction_id
            tx = tx_correlation(identity)
            context = RadioContext.model_validate(radio.model_dump(), strict=True)
            if (checked != finalized or not self.core.authorize(checked)
                or context.interaction_id != identity or context.turn_id != str(identity)
                or context.tx_correlation_id != tx or context.session_id != "recovery-full-voice"
                or context.source_domain != CommunicationDomain.GENERAL
                or context.communication_priority != CommunicationPriority.ROUTINE or context.provenance):
                raise ValueError("general_presentation_binding")
        except ValueError:
            return PresentationResult(tx, "failed", True, PresentationFailure.INVALID_FINALIZED_TEXT)
        return await self._admit_validated(checked, context)

    async def _run(self, finalized, context, operation):
        if not self.core.authorize(finalized):
            result = PresentationResult(str(context.tx_correlation_id), "failed", True, PresentationFailure.INVALID_FINALIZED_TEXT)
            operation.result = result
            return result
        return await super()._run(finalized, context, operation)


class GeneralSemanticVoice:
    """Borrowed interpreter/endpoint; owns only new semantic plans/presentation."""
    def __init__(self, api_key, gateway, router, interpreter, endpoint, entity, session_id,
                 *, observe=lambda _event, **_fields: None, clock=lambda: datetime.now(UTC)):
        self.core = GeneralSemanticCore(gateway, router, session_id, clock=clock)
        self.interpreter, self.endpoint, self.entity = interpreter, endpoint, entity
        self.observe, self.clock = observe, clock
        self.turn_id = None
        self.presentation = GeneralPresentation(InformationalStreamingTts(api_key,
            observe=lambda text: self.emit("tts_input", tts_input=text)), endpoint.radio_router, core=self.core)
        def diagnostic(stage, **fields):
            fields.pop("monotonic", None)
            self.emit("delivery_diagnostic", diagnostic_stage=stage, **fields)
        self.presentation.observe_diagnostic = diagnostic
        self.presentation.streaming_tts.observe_diagnostic = diagnostic

    def emit(self, event, **fields):
        try:
            self.observe(event, turn_id=self.turn_id, monotonic=time.monotonic(), **fields)
        except Exception:
            pass  # Evidence cannot change semantic/voice execution.

    async def run(self, utterance, hybrid, cancellation, *, epoch=None):
        self.turn_id = str(utterance.interaction_id)
        if cancellation.cancelled:
            return
        request = self.core.request(utterance, epoch=epoch)
        self.emit("request", source_text=request.source_text, source_sha256=request.source_sha256,
            context_revision=request.context.revision, context_bytes=len(request.context.model_dump_json().encode("utf-8")),
            context_projection=request.context.model_dump_json(),
            catalog_version=request.catalog_version, operation_id=str(request.operation_id))
        started = time.monotonic()
        operations_before = self.interpreter.operation_count
        try:
            proposal = await self.interpreter.interpret_general(request, cancellation)
        except ConversationCleanupError:
            raise
        except ValueError as exc:
            if cancellation.cancelled:
                return
            self.emit("failed", failure_stage="semantic_validation", failure_category=type(exc).__name__)
            finalized = self.core.unavailable(request, "ADMISSION_REJECTED")
        except Exception as exc:
            if cancellation.cancelled:
                return
            self.emit("failed", failure_stage="semantic_provider", failure_category=type(exc).__name__)
            finalized = self.core.unavailable(request, "PROVIDER_UNAVAILABLE")
        else:
            try:
                finalized = self.core.execute(utterance, proposal, cancellation, hybrid)
            except ValueError as exc:
                if cancellation.cancelled:
                    return
                self.emit("failed", failure_stage="core_admission", failure_category=type(exc).__name__)
                finalized = self.core.unavailable(request, "ADMISSION_REJECTED")
        if cancellation.cancelled:
            return
        plan = finalized.plan
        # Semantic success belongs to ORION before any fallible audio delivery.
        self.core.context.accept(finalized, delivery="pending")
        factual = plan.factual if isinstance(plan, MixedPlan) else plan
        self.emit("admitted", response_kind=plan.kind, finalized_text=finalized.text,
            semantic_provider_operations=self.interpreter.operation_count-operations_before,
            dialogue_role_selected=int(isinstance(plan, (DialoguePlan, MixedPlan))), separate_conversation_provider_operations=0,
            planner_operations=0, core_fact_reads=self.core.read_count,
            semantic_user_path_ms=(time.monotonic()-started)*1000,
            selected_capabilities=",".join(factual.capabilities) if isinstance(factual, FactPlan) else "")
        if isinstance(factual, FactPlan):
            for fact in factual.facts:
                self.emit("selected_fact", fact_key=fact.key, fact_value=fact.value, fact_unit=fact.unit,
                    fact_source=fact.source.value, fact_authority=fact.authority.value,
                    fact_generation=fact.generation, fact_age_seconds=fact.age_seconds,
                    fact_observed_at=fact.observed_at.isoformat() if fact.observed_at else None,
                    call_id=factual.receipt.call_id if factual.receipt else None)
        context = RadioContext(tx_correlation_id=tx_correlation(utterance.interaction_id),
            interaction_id=utterance.interaction_id, turn_id=self.turn_id, session_id="recovery-full-voice",
            source_domain=CommunicationDomain.GENERAL, communication_priority=CommunicationPriority.ROUTINE,
            radio_entity=self.entity, target_frequency_hz=251000000, modulation=RadioModulation.AM)
        self.endpoint.response_valid_until = time.monotonic() + (plan.deadline-self.clock()).total_seconds()
        previous_marks, packet_before = self.endpoint.tx_marks, self.endpoint.packet_id
        try:
            result = await self.interpreter._bounded(self.presentation.present(finalized, context), 40., cancellation, cleanup_budget=.6)
        except BaseException as exc:
            self.core.context.update_delivery(finalized, delivery="cancelled" if isinstance(exc, asyncio.CancelledError) or cancellation.cancelled else "failed",
                                     tts_started="tts_started" in self.presentation.marks)
            raise
        marks = self.endpoint.tx_marks if self.endpoint.tx_marks is not previous_marks else {}
        self.emit("response_terminal", status=result.state, frames=self.endpoint.packet_id-packet_before,
            failure_category=result.failure.value if result.failure else None,
            **{key: self.presentation.marks.get(key) for key in ("tts_started", "tts_first_pcm", "tts_completed", "tts_pcm_bytes")},
            **{key: marks.get(key) for key in ("radio_first_frame", "radio_completed")})
        self.core.context.update_delivery(finalized,
            delivery="cancelled" if cancellation.cancelled else result.state if result.state in {"completed", "failed", "cancelled"} else "unknown",
            tts_started="tts_started" in self.presentation.marks)
        self.emit("context_delivery", context_projection=self.core.context.project(self.core.context.epoch).model_dump_json())

    async def shutdown(self):
        self.core.context.reset()
        if not await self.presentation.shutdown():
            raise ConversationCleanupError("general_presentation_shutdown_not_completed")
