"""Separate typed admission; borrowed protected streaming mechanics, not policy."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from orion.communication_contracts import CommunicationDomain, CommunicationPriority, FinalizedCommunicationText
from orion.hybrid_aircraft_contracts import FinalizedInformationalText
from orion.hybrid_aircraft_core import render_informational
from orion.protected_presentation import PresentationFailure, PresentationResult, tx_correlation
from orion.protected_streaming_presentation import StreamingProtectedPresentation
from orion.protected_streaming_tts import ProtectedStreamingTts, protected_stream_requests
from orion.radio_contracts import RadioContext


class InformationalStreamingTts(ProtectedStreamingTts):
    def __init__(self, api_key: str, *, observe=lambda _text: None):
        super().__init__(api_key)
        self.observe_input = observe

    def _requests(self, text: str) -> tuple:
        requests = protected_stream_requests(text)
        # Same installed protobuf contract and execution. Only voice differs.
        requests[0].options.voice = "jane"
        try:
            self.observe_input(requests[1].synthesis_input.text)
        except Exception:
            pass
        return requests


class InformationalPresentation(StreamingProtectedPresentation):
    def __init__(self, tts, router, *, authorize, clock=lambda: datetime.now(UTC), observe=lambda _event, **_fields: None):
        super().__init__(tts, router)
        self.clock, self.observe = clock, observe
        self.authorize = authorize

    def _observe(self, event, **fields):
        try:
            self.observe(event, **fields)
        except Exception:
            pass

    async def present(self, finalized: object, radio: RadioContext) -> PresentationResult:
        tx = "invalid"
        try:
            if type(finalized) is not FinalizedInformationalText:
                raise ValueError("typed_informational_only")
            raw = finalized.model_dump(mode="python", warnings="error")
            checked = FinalizedInformationalText.model_validate(raw, strict=True)
            if (checked.model_dump(mode="python") != raw or not self.authorize(checked)
                or checked.text != render_informational(checked.plan, self.clock())):
                raise ValueError("informational_text_mismatch")
            tx = tx_correlation(checked.plan.interaction_id)
            context = RadioContext.model_validate(radio.model_dump(mode="python"), strict=True)
            if (context.tx_correlation_id != tx or context.interaction_id != checked.plan.interaction_id
                or context.turn_id != str(checked.plan.interaction_id) or context.session_id != "recovery-full-voice"
                or context.source_domain != CommunicationDomain.GENERAL
                or context.communication_priority != CommunicationPriority.ROUTINE):
                raise ValueError("informational_radio_binding")
        except Exception:
            self._observe("presentation_rejected", tx_id=tx, status="invalid_informational_admission")
            return PresentationResult(tx, "failed", True, PresentationFailure.INVALID_FINALIZED_TEXT)
        self._observe("presentation_admitted", turn_id=str(checked.plan.interaction_id), tx_id=tx,
                      finalized_text=checked.text, status="accepted")
        # Only the extracted operation helper is shared. Streaming _run consumes
        # text; signature uses model_dump. Never convert this into protected text.
        return await self._admit_validated(cast(FinalizedCommunicationText, checked), context)

    async def _run(self, finalized, context, operation):
        try:
            if finalized.text != render_informational(finalized.plan, self.clock()):
                raise ValueError("expired_or_changed_informational_plan")
        except Exception:
            result = PresentationResult(str(context.tx_correlation_id), "failed", True, PresentationFailure.INVALID_FINALIZED_TEXT)
            operation.result = result
            return result
        return await super()._run(finalized, context, operation)
