"""Production-reusable native utterance → existing IA-6 → protected composition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import time
from threading import RLock
from typing import Callable

from orion.communication_contracts import (
    CommunicationContext, CommunicationDomain, CommunicationProfileId,
    FinalizedCommunicationText, ResponseCompositionPlan,
)
from orion.full_voice_stt import FinalizedUserUtterance
from orion.full_voice_timing import observe
from orion.interaction_contracts import InteractionRequest
from orion.interaction_router import InteractionRouter, RouterExecutionStatus
from orion.ownship_phraseology import OwnshipReportRuleset, OWNSHIP_REPORT_V1
from orion.ownship_report import map_ownship_report
from orion.phraseology_renderer import PhraseologyRenderer
from orion.planner import PlannerCancellationToken, PlannerTaskRunner, PlannerProvider
from orion.response_composer import ResponseComposer
from orion.tool_gateway import ToolGateway
from orion.tool_gateway_contracts import ToolCall, ToolDefinition, ToolResult


class RetainedOwnshipGateway(ToolGateway):
    """Observe the actual gateway, not an alternative authority implementation."""

    def __init__(self, delegate: ToolGateway, clock=time.monotonic) -> None:
        self.delegate = delegate
        self.clock = clock
        self.results: list[ToolResult] = []
        self.marks: dict[str, float] = {}

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return self.delegate.definitions()

    def execute(self, call: ToolCall) -> ToolResult:
        if self.results or call.name != "orion.world.ownship.get":
            raise RuntimeError("full_voice_tool_bound")
        self.marks["tool_started"] = self.clock()
        result = self.delegate.execute(call)
        self.marks["tool_completed"] = self.clock()
        self.results.append(result)
        return result


@dataclass(frozen=True)
class FullVoiceCoreResult:
    status: str
    finalized: FinalizedCommunicationText | None
    marks: dict[str, float]
    tool_results: tuple[ToolResult, ...]


class FullVoiceCore:
    def __init__(self, gateway: ToolGateway, provider_factory: Callable[[], PlannerProvider] | None = None, *, clock=lambda: datetime.now(UTC), deterministic: bool = True) -> None:
        self.gateway = RetainedOwnshipGateway(gateway)
        self.clock = clock
        self.router = InteractionRouter(
            planner=PlannerTaskRunner(gateway=self.gateway, clock=clock),
            provider_factory=provider_factory or _provider_not_used, clock=clock,
            bounded_ownship_gateway=self.gateway if deterministic else None,
        )
        self.context = CommunicationContext(
            profile_id=CommunicationProfileId.ICAO, domain=CommunicationDomain.NAVIGATION,
            input_language="ru-RU", operational_language="en-US",
            phraseology_version=OWNSHIP_REPORT_V1,
        )
        self.renderer = PhraseologyRenderer(OwnshipReportRuleset())
        self.composer = ResponseComposer()
        self._lock = RLock()
        self._completed: dict = {}

    def run(self, utterance: FinalizedUserUtterance, cancellation: PlannerCancellationToken) -> FullVoiceCoreResult:
        with self._lock:
            previous = self._completed.get(utterance.interaction_id)
            if previous is not None:
                if previous[0] != utterance:
                    raise ValueError("full_voice_identity_conflict")
                return previous[1]
            if len(self._completed) >= 64:
                raise ValueError("full_voice_identity_capacity")
            result = self._run(utterance, cancellation)
            self._completed[utterance.interaction_id] = (utterance, result)
            return result

    def _run(self, utterance: FinalizedUserUtterance, cancellation: PlannerCancellationToken) -> FullVoiceCoreResult:
        self.gateway.results.clear()
        self.gateway.marks.clear()
        marks = {"interaction_started": time.monotonic()}
        identity = utterance.interaction_id
        observe("T3", identity)
        request = InteractionRequest(
            interaction_id=identity, session_id="recovery-full-voice",
            turn_id=str(identity), text=utterance.text, role_hint="pilot",
            domain_hint="navigation", created_at=self.clock(),
        )
        result = self.router.execute(
            request, self.context, deadline=self.clock() + timedelta(seconds=15),
            cancellation=cancellation,
        )
        marks["interaction_completed"] = time.monotonic()
        marks.update(self.gateway.marks)
        tools = tuple(self.gateway.results)
        if result.status is not RouterExecutionStatus.COMPLETED or result.response is None:
            return FullVoiceCoreResult(result.status.value, None, marks, tools)
        if cancellation.cancelled:
            return FullVoiceCoreResult("cancelled", None, marks, tools)
        marks["semantic_response"] = time.monotonic()
        unit = map_ownship_report(result.response, tools, identity, now=self.clock())
        marks["osu_mapped"] = time.monotonic()
        fragment = self.renderer.render(unit, self.context)
        marks["protected_rendered"] = time.monotonic()
        finalized = self.composer.compose(ResponseCompositionPlan(
            interaction_id=identity, communication=self.context, priority=unit.priority,
            protected_fragments=(fragment,), suppress_conversational_envelope=True,
        ))
        marks["composed"] = time.monotonic()
        observe("T4", identity)
        return FullVoiceCoreResult("completed", finalized, marks, tools)


def _provider_not_used() -> PlannerProvider:
    raise RuntimeError("bounded_ownship_does_not_use_a_provider")
