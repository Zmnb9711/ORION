"""Core-owned context, selected facts and response admission; no provider I/O."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Callable, Literal
from uuid import UUID, uuid4

from pydantic import Field

from orion.aircraft_interpretation import source_hash
from orion.full_voice_stt import FinalizedUserUtterance
from orion.general_semantic_contracts import (
    CATALOG, Capability, CapabilityGap, Clarification, ContextExchange, ContextProjection,
    Dialogue, FactRequest, SemanticModel, SemanticProposal, SemanticRequest,
)
from orion.hybrid_aircraft_core import HybridAircraftCore
from orion.hybrid_aircraft_contracts import AircraftIdentityQueryResult
from orion.interaction_contracts import CapabilityId
from orion.interaction_router import InteractionRouter
from orion.planner import PlannerCancellationToken
from orion.tool_gateway import ToolGateway
from orion.tool_gateway_contracts import ExecutionContext, ToolCall, ToolReceipt, ToolResultStatus
from orion.world_model import WorldModelFacade
from orion.world_model_contracts import WorldFact, WorldPosition, WorldFactStatus, WorldFactAuthority, WorldFactSource


class PlanBase(SemanticModel):
    request: SemanticRequest
    owner: Literal["core.general-semantic"] = "core.general-semantic"
    deadline: datetime


class DialoguePlan(PlanBase):
    kind: Literal["DIALOGUE_NON_AUTHORITATIVE"] = "DIALOGUE_NON_AUTHORITATIVE"
    text: str = Field(min_length=1, max_length=300, repr=False)
    response_id: str


class FactPlan(PlanBase):
    kind: Literal["CORE_FACT_AUTHORITATIVE"] = "CORE_FACT_AUTHORITATIVE"
    capabilities: tuple[Capability, ...]
    facts: tuple[WorldFact[float], ...] = ()
    receipt: ToolReceipt | None = None
    aircraft: AircraftIdentityQueryResult | None = None


class ClarificationPlan(PlanBase):
    kind: Literal["CLARIFICATION"] = "CLARIFICATION"
    slot: Literal["object", "meaning", "reference", "action"]


class UnavailablePlan(PlanBase):
    kind: Literal["TRUTHFUL_UNAVAILABLE"] = "TRUTHFUL_UNAVAILABLE"
    reason: Literal["CAPABILITY_NOT_EXPOSED", "FACT_UNKNOWN", "FACT_STALE", "SOURCE_UNAVAILABLE",
                    "RESTRICTED", "NOT_IMPLEMENTED", "PROVIDER_UNAVAILABLE", "ADMISSION_REJECTED"]


ResponsePlan = Annotated[DialoguePlan | FactPlan | ClarificationPlan | UnavailablePlan, Field(discriminator="kind")]


class FinalizedGeneralText(SemanticModel):
    plan: ResponsePlan
    text: str = Field(min_length=1, max_length=1000, repr=False)


def render_general(plan: ResponsePlan, now: datetime) -> str:
    if now >= plan.deadline:
        raise ValueError("general_plan_expired")
    if isinstance(plan, DialoguePlan):
        if any(ord(char) < 32 and char not in "\t\r\n" for char in plan.text):
            raise ValueError("dialogue_control_character")
        return plan.text
    if isinstance(plan, ClarificationPlan):
        return {"object": "Уточните, о каком объекте вы спрашиваете.",
                "meaning": "Уточните, что именно вы хотите узнать.",
                "reference": "Уточните, к чему относится ваш вопрос.",
                "action": "Уточните, какое действие вы имеете в виду."}[plan.slot]
    if isinstance(plan, UnavailablePlan):
        return {"CAPABILITY_NOT_EXPOSED": "Пока не могу получить эти данные через доступные мне возможности.",
                "FACT_UNKNOWN": "Запрошенные текущие данные неизвестны.",
                "FACT_STALE": "Данные устарели. Сейчас не могу сообщить актуальное значение.",
                "SOURCE_UNAVAILABLE": "Источник текущих данных сейчас недоступен.",
                "RESTRICTED": "Доступ к этим данным ограничен.",
                "NOT_IMPLEMENTED": "Такой запрос я пока не могу выполнить.",
                "PROVIDER_UNAVAILABLE": "Сейчас недоступна обработка естественной речи.",
                "ADMISSION_REJECTED": "Не удалось безопасно обработать этот запрос."}[plan.reason]
    if plan.aircraft is not None:
        from orion.hybrid_aircraft_core import render_informational
        from orion.hybrid_aircraft_contracts import InformationalResponsePlan
        return render_informational(InformationalResponsePlan(interaction_id=plan.request.interaction_id,
            aircraft=plan.aircraft, deadline=plan.deadline), now)
    values = {fact.key: fact.value for fact in plan.facts}
    parts: list[str] = []
    for capability in plan.capabilities:
        if capability == "ownship.position":
            lat, lon = values["ownship.position.latitude"], values["ownship.position.longitude"]
            if lat is None or lon is None:
                raise ValueError("position_missing")
            parts.append("Координаты: " + WorldModelFacade._format_coordinates(lat, lon) + ".")
        elif capability == "ownship.heading":
            heading = values["ownship.heading_deg"]
            if heading is None:
                raise ValueError("heading_missing")
            parts.append("Текущий курс " + format(Decimal(str(heading)), "f") + " градусов.")
        else:
            raise ValueError("unsupported_fact_plan")
    return " ".join(parts)


class InteractionContext:
    """Two exchanges / 4096 UTF-8 bytes / 300 seconds, in-memory only."""
    def __init__(self, session_id: str, clock: Callable[[], datetime]):
        self.clock, self.session_id = clock, session_id
        self.revision = 0
        self.exchanges: tuple[ContextExchange, ...] = ()
        self.expires = clock()
        self.epoch: str | None = None

    def reset(self, epoch: str | None = None) -> None:
        self.exchanges = ()
        self.revision += 1
        self.epoch = epoch
        self.expires = self.clock() + timedelta(seconds=300)

    def project(self, epoch: str | None = None) -> ContextProjection:
        if self.clock() >= self.expires or epoch != self.epoch:
            self.reset(epoch)
        return ContextProjection(revision=self.revision, session_id=self.session_id, exchanges=self.exchanges)

    def accept(self, finalized: FinalizedGeneralText) -> None:
        plan = finalized.plan
        if plan.request.context.revision != self.revision:
            raise ValueError("context_revision_changed")
        topic = plan.capabilities[-1] if isinstance(plan, FactPlan) else None
        entry = ContextExchange(user=plan.request.source_text,
            reply=finalized.text if isinstance(plan, DialoguePlan) else None,
            topic=topic, language=plan.request.language)
        self.exchanges = (*self.exchanges, entry)[-2:]
        self.revision += 1
        while len(ContextProjection(revision=self.revision, session_id=self.session_id,
                exchanges=self.exchanges).model_dump_json().encode("utf-8")) > 4096:
            self.exchanges = self.exchanges[1:]
        self.expires = self.clock() + timedelta(seconds=300)


class GeneralSemanticCore:
    def __init__(self, gateway: ToolGateway, router: InteractionRouter, session_id: str,
                 *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.gateway, self.router, self.clock = gateway, router, clock
        self.context = InteractionContext(session_id, clock)
        self.pending: dict[UUID, SemanticRequest] = {}
        self.completed: dict[UUID, FinalizedGeneralText] = {}
        self.read_count: int | None = 0

    def request(self, utterance: FinalizedUserUtterance, *, epoch: str | None = None) -> SemanticRequest:
        if utterance.interaction_id in self.pending or len(self.pending) >= 64:
            raise ValueError("general_turn_replay_or_capacity")
        now = self.clock()
        self.read_count = 0
        request = SemanticRequest(interaction_id=utterance.interaction_id, operation_id=uuid4(),
            source_text=utterance.text, source_sha256=source_hash(utterance.text), language=utterance.input_language,
            context=self.context.project(epoch), created_at=now, deadline=now + timedelta(seconds=12))
        self.pending[utterance.interaction_id] = request
        return request

    def unavailable(self, request: SemanticRequest, reason: Literal["PROVIDER_UNAVAILABLE", "ADMISSION_REJECTED"]
                    ) -> FinalizedGeneralText:
        return self._finalize(UnavailablePlan(request=request, deadline=self.clock()+timedelta(seconds=12), reason=reason))

    def execute(self, utterance: FinalizedUserUtterance, proposal: SemanticProposal,
                cancellation: PlannerCancellationToken, hybrid: HybridAircraftCore) -> FinalizedGeneralText:
        request = self.pending.get(utterance.interaction_id)
        if request is None or request.source_text != utterance.text:
            raise ValueError("general_request_not_owned")
        grant = self.router.admit_general(request, proposal, cancellation, context_revision=self.context.revision)
        result = proposal.result
        if isinstance(result, FactRequest):
            definitions = [item for item in self.gateway.definitions() if item.name == CATALOG[0].tool
                           and item.version == "1.0" and item.capability == "world.ownship.read"]
            if len(definitions) != 1:
                raise ValueError("semantic_catalog_binding")
        if isinstance(result, FactRequest) and result.capabilities == ("aircraft.identity",):
            self.read_count = None  # A failed borrowed identity tail may not expose a receipt.
            identity = hybrid.run_semantic_identity(utterance, cancellation, grant, self.router)
            if identity.finalized is None or identity.finalized.plan.aircraft is None:
                plan: ResponsePlan = UnavailablePlan(request=request, deadline=request.deadline, reason="SOURCE_UNAVAILABLE")
            else:
                aircraft = identity.finalized.plan.aircraft
                self.read_count = 1
                plan = FactPlan(request=request, deadline=min(request.deadline, aircraft.expires_at),
                                capabilities=result.capabilities, aircraft=aircraft)
        else:
            if not self.router.consume_general_admission(grant, utterance.interaction_id, utterance.text, cancellation):
                raise ValueError("general_grant_not_owned")
            if isinstance(result, Dialogue):
                plan = DialoguePlan(request=request, deadline=self.clock()+timedelta(seconds=12),
                                    text=result.text, response_id=proposal.response_id)
            elif isinstance(result, FactRequest):
                plan = self._facts(request, result, cancellation)
            elif isinstance(result, Clarification):
                plan = ClarificationPlan(request=request, deadline=request.deadline, slot=result.slot)
            else:
                plan = UnavailablePlan(request=request, deadline=request.deadline,
                    reason="CAPABILITY_NOT_EXPOSED" if isinstance(result, CapabilityGap) else "NOT_IMPLEMENTED")
        if cancellation.cancelled:
            raise ValueError("general_cancelled")
        return self._finalize(plan)

    def _finalize(self, plan: ResponsePlan) -> FinalizedGeneralText:
        identity = plan.request.interaction_id
        if identity in self.completed or self.pending.get(identity) != plan.request:
            raise ValueError("general_response_not_owned")
        finalized = FinalizedGeneralText(plan=plan, text=render_general(plan, self.clock()))
        self.completed[identity] = finalized
        return finalized

    def authorize(self, value: FinalizedGeneralText) -> bool:
        try:
            return (type(value) is FinalizedGeneralText
                and self.completed.get(value.plan.request.interaction_id) == value
                and value.text == render_general(value.plan, self.clock()))
        except ValueError:
            return False

    def _facts(self, request: SemanticRequest, wanted: FactRequest,
               cancellation: PlannerCancellationToken) -> ResponsePlan:
        if "aircraft.identity" in wanted.capabilities:
            return UnavailablePlan(request=request, deadline=request.deadline, reason="NOT_IMPLEMENTED")
        matches = [d for d in self.gateway.definitions() if d.name == CATALOG[0].tool and d.version == "1.0"
                   and d.capability == "world.ownship.read"]
        if len(matches) != 1 or cancellation.cancelled:
            raise ValueError("semantic_catalog_binding")
        call = ToolCall(call_id=f"general-{request.interaction_id}", name=CATALOG[0].tool, version="1.0",
            context=ExecutionContext(actor_id="general-semantic-core", interaction_id=str(request.interaction_id),
                session_id=request.context.session_id, turn_id=str(request.interaction_id),
                allowed_capabilities=(CapabilityId("world.ownship.read"),), permissions=("world.read",),
                deadline=request.deadline))
        self.read_count = 1
        tool = self.gateway.execute(call)
        if cancellation.cancelled or self.clock() >= request.deadline:
            raise ValueError("general_fact_cancelled_or_expired")
        r, p = tool.receipt, tool.provenance
        if (tool.status != ToolResultStatus.COMPLETED or tool.data is None or p is None
            or tool.call_id != call.call_id or tool.tool_name != call.name or tool.tool_version != call.version
            or tool.capability != "world.ownship.read" or tool.output_schema != "orion.tool.output.ownship.v1"
            or r.call_id != call.call_id or r.actor_id != call.context.actor_id
            or r.tool_name != call.name or r.tool_version != call.version or r.task_id is not None
            or r.idempotency_key is not None
            or r.interaction_id != call.context.interaction_id or r.turn_id != call.context.turn_id
            or r.session_id != call.context.session_id or r.status != "completed" or not r.handler_started):
            raise ValueError("general_fact_receipt")
        snapshot = tool.data.root.get("snapshot")
        if not isinstance(snapshot, dict) or snapshot.get("schema_version") != "ia2.world.v1" or snapshot.get("query") != "ownship.current_state":
            raise ValueError("general_fact_snapshot")
        generated = datetime.fromisoformat(str(snapshot.get("generated_at")))
        if not r.accepted_at <= generated <= r.completed_at <= self.clock():
            raise ValueError("general_fact_time_binding")
        selected: list[WorldFact[float]] = []
        expires = request.deadline
        for capability in wanted.capabilities:
            if capability == "ownship.position":
                position = WorldFact[WorldPosition].model_validate(snapshot.get("position"))
                fact = position
            else:
                heading = WorldFact[float].model_validate(snapshot.get("heading_deg"))
                fact = heading
            expected_key = "ownship.position" if capability == "ownship.position" else "ownship.heading_deg"
            if (fact.key != expected_key or fact.source != WorldFactSource.DCS_EXPORT
                or fact.authority != WorldFactAuthority.AUTHORITATIVE or fact.unit != (None if capability == "ownship.position" else "deg")
                or fact.source not in p.sources or fact.authority not in p.authorities or fact.status not in p.fact_statuses
                or (fact.generation is not None and fact.generation not in p.generations)):
                raise ValueError("general_fact_authority")
            if fact.status != WorldFactStatus.KNOWN:
                reason = {WorldFactStatus.STALE: "FACT_STALE", WorldFactStatus.UNKNOWN: "FACT_UNKNOWN",
                          WorldFactStatus.UNAVAILABLE: "SOURCE_UNAVAILABLE", WorldFactStatus.RESTRICTED: "RESTRICTED"}[fact.status]
                return UnavailablePlan.model_validate({"request": request.model_dump(), "deadline": request.deadline, "reason": reason})
            if (fact.observed_at is None or fact.age_seconds is None or fact.generation is None
                or len(p.generations) != 1 or p.max_age_seconds is None or fact.age_seconds > p.max_age_seconds
                or fact.observed_at > r.accepted_at or fact.age_seconds + (self.clock()-r.accepted_at).total_seconds() > 5):
                raise ValueError("general_fact_freshness")
            expires = min(expires, fact.observed_at+timedelta(seconds=5), r.accepted_at+timedelta(seconds=5-fact.age_seconds))
            metadata = fact.model_dump(exclude={"key", "value"})
            if capability == "ownship.position":
                if position.value is None:
                    raise ValueError("position_null")
                for axis in ("latitude", "longitude"):
                    selected.append(WorldFact[float](key="ownship.position."+axis, value=getattr(position.value, axis), **metadata))
            else:
                if heading.value is None or not 0 <= heading.value < 360:
                    raise ValueError("heading_range")
                selected.append(heading)
        return FactPlan(request=request, deadline=expires, capabilities=wanted.capabilities, facts=tuple(selected), receipt=r)
