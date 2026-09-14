"""Core-owned context, selected facts and response admission; no provider I/O."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import Annotated, Callable, Literal
from uuid import UUID, uuid4

from pydantic import Field

from orion.aircraft_interpretation import source_hash
from orion.full_voice_stt import FinalizedUserUtterance
from orion.general_semantic_contracts import (
    CATALOG, Capability, CapabilityGap, Clarification, ContextExchange, ContextProjection,
    DIALOGUE_MAX_CHARS, Dialogue, FactRequest, MetaRequest, Mixed, SemanticModel, SemanticProposal, SemanticRequest, StateSummary,
)
from orion.general_fact_registry import require_exposed
from orion.general_fact_presentation import LABELS, EN_LABELS, scalar_text, spoken_coordinates
from orion.personal_context import load_personal_context
from orion.hybrid_aircraft_core import HybridAircraftCore
from orion.hybrid_aircraft_contracts import AircraftIdentityQueryResult
from orion.interaction_contracts import CapabilityId
from orion.interaction_router import InteractionRouter
from orion.planner import PlannerCancellationToken
from orion.tool_gateway import ToolGateway
from orion.tool_gateway_contracts import ExecutionContext, ToolCall, ToolReceipt, ToolResultStatus
from orion.world_model_contracts import AircraftIdentity, WorldAttitude, WorldFact, WorldPosition, WorldFactStatus


class PlanBase(SemanticModel):
    request: SemanticRequest
    owner: Literal["core.general-semantic"] = "core.general-semantic"
    deadline: datetime


class DialoguePlan(PlanBase):
    kind: Literal["DIALOGUE_NON_AUTHORITATIVE"] = "DIALOGUE_NON_AUTHORITATIVE"
    text: str = Field(min_length=1, max_length=DIALOGUE_MAX_CHARS, repr=False)
    response_id: str


# Output policies, not user-language recognition. Registry growth never expands
# a status request automatically; all other facts remain explicitly selectable.
SUMMARY_CAPABILITIES = ("ownship.heading", "ownship.altitude_msl", "ownship.pitch", "ownship.bank")
META_MAX_CATEGORIES = 8


class MetaPlan(PlanBase):
    kind: Literal["CORE_CAPABILITY_METADATA"] = "CORE_CAPABILITY_METADATA"
    topic: Literal["capabilities", "identity", "help"]
    capabilities: tuple[Capability, ...] = Field(default=(), max_length=META_MAX_CATEGORIES)
    additional_categories: bool = False


class FactPlan(PlanBase):
    kind: Literal["CORE_FACT_AUTHORITATIVE"] = "CORE_FACT_AUTHORITATIVE"
    capabilities: tuple[Capability, ...]
    facts: tuple[WorldFact[float | str], ...] = ()
    receipt: ToolReceipt | None = None
    aircraft: AircraftIdentityQueryResult | None = None
    unavailable: tuple[UnavailableFact, ...] = ()
    summary: bool = False


class UnavailableFact(SemanticModel):
    capability: str
    reason: Literal["FACT_UNKNOWN", "FACT_STALE", "SOURCE_UNAVAILABLE", "RESTRICTED"]


class ClarificationPlan(PlanBase):
    kind: Literal["CLARIFICATION"] = "CLARIFICATION"
    slot: Literal["object", "meaning", "reference", "action"]


class UnavailablePlan(PlanBase):
    kind: Literal["TRUTHFUL_UNAVAILABLE"] = "TRUTHFUL_UNAVAILABLE"
    capabilities: tuple[Capability, ...] = ()
    reason: Literal["CAPABILITY_NOT_EXPOSED", "FACT_UNKNOWN", "FACT_STALE", "SOURCE_UNAVAILABLE",
                    "RESTRICTED", "NOT_IMPLEMENTED", "PROVIDER_UNAVAILABLE", "ADMISSION_REJECTED"]


class MixedPlan(PlanBase):
    kind: Literal["MIXED"] = "MIXED"
    dialogue: DialoguePlan
    factual: FactPlan | UnavailablePlan


ResponsePlan = Annotated[DialoguePlan | MetaPlan | FactPlan | MixedPlan | ClarificationPlan | UnavailablePlan, Field(discriminator="kind")]


class FinalizedGeneralText(SemanticModel):
    plan: ResponsePlan
    text: str = Field(min_length=1, max_length=1000, repr=False)


def render_general(plan: ResponsePlan, now: datetime) -> str:
    if now >= plan.deadline:
        raise ValueError("general_plan_expired")
    english = plan.request.language.startswith("en")
    labels_by_language = EN_LABELS if english else LABELS
    if isinstance(plan, MixedPlan):
        if (plan.dialogue.request != plan.request or plan.factual.request != plan.request
            or plan.deadline > min(plan.dialogue.deadline, plan.factual.deadline)):
            raise ValueError("mixed_plan_binding")
        return render_general(plan.dialogue, now) + " " + render_general(plan.factual, now)
    if isinstance(plan, DialoguePlan):
        if any(ord(char) < 32 and char not in "\t\r\n" for char in plan.text):
            raise ValueError("dialogue_control_character")
        return plan.text
    if isinstance(plan, MetaPlan):
        if plan.topic == "identity":
            return "I am ORION, a conversational assistant in DCS." if english else "Я ORION, разговорный помощник в DCS."
        labels = [labels_by_language[require_exposed(key).presentation].lower() for key in plan.capabilities]  # type: ignore[index]
        if english:
            description = "The current catalog includes: " + ", ".join(labels) + "." if labels else "No data categories are currently exposed."
            if plan.additional_categories:
                description += " This is part of the catalog."
            if plan.topic == "help":
                description = "You can converse or ask for current data in your own words. " + description
            return description + " Actual value availability is checked when requested."
        description = ("В текущем каталоге есть: " + ", ".join(labels) + ".") if labels else "В текущем каталоге нет доступных категорий данных."
        if plan.additional_categories:
            description += " Это часть категорий каталога."
        if plan.topic == "help":
            description = "Можно общаться или запрашивать текущие данные своими словами. " + description
        return description + " Наличие актуальных значений проверяется отдельно при запросе."
    if isinstance(plan, ClarificationPlan):
        if english:
            return {"object": "Which object do you mean?", "meaning": "What would you like to know?",
                    "reference": "What does your question refer to?", "action": "Which action do you mean?"}[plan.slot]
        return {"object": "Уточните, о каком объекте вы спрашиваете.",
                "meaning": "Уточните, что именно вы хотите узнать.",
                "reference": "Уточните, к чему относится ваш вопрос.",
                "action": "Уточните, какое действие вы имеете в виду."}[plan.slot]
    if isinstance(plan, UnavailablePlan):
        if english:
            return {"CAPABILITY_NOT_EXPOSED": "I cannot safely obtain those data through my currently available capabilities.",
                    "FACT_UNKNOWN": "The requested current data are unknown.",
                    "FACT_STALE": "The data are stale; I cannot report a current value.",
                    "SOURCE_UNAVAILABLE": "The current data source is unavailable.",
                    "RESTRICTED": "Access to those data is restricted.",
                    "NOT_IMPLEMENTED": "I cannot carry out that request yet.",
                    "PROVIDER_UNAVAILABLE": "Natural-language processing is currently unavailable.",
                    "ADMISSION_REJECTED": "I could not safely process that request."}[plan.reason]
        return {"CAPABILITY_NOT_EXPOSED": "Пока не могу получить эти данные через доступные мне возможности.",
                "FACT_UNKNOWN": "Запрошенные текущие данные неизвестны.",
                "FACT_STALE": "Данные устарели. Сейчас не могу сообщить актуальное значение.",
                "SOURCE_UNAVAILABLE": "Источник текущих данных сейчас недоступен.",
                "RESTRICTED": "Доступ к этим данным ограничен.",
                "NOT_IMPLEMENTED": "Такой запрос я пока не могу выполнить.",
                "PROVIDER_UNAVAILABLE": "Сейчас недоступна обработка естественной речи.",
                "ADMISSION_REJECTED": "Не удалось безопасно обработать этот запрос."}[plan.reason]
    if plan.aircraft is not None:
        if english:
            from orion.hybrid_aircraft_core import safe_aircraft_name
            if plan.aircraft.fact_status != WorldFactStatus.KNOWN or plan.aircraft.aircraft_type is None:
                return "The current aircraft type is unavailable."
            display = safe_aircraft_name(plan.aircraft.aircraft_type)
            if display is None:
                raise ValueError("aircraft_name_invalid")
            return "You are in " + display + "."
        from orion.hybrid_aircraft_core import render_informational
        from orion.hybrid_aircraft_contracts import InformationalResponsePlan
        return render_informational(InformationalResponsePlan(interaction_id=plan.request.interaction_id,
            aircraft=plan.aircraft, deadline=plan.deadline), now)
    from orion.hybrid_aircraft_core import safe_aircraft_name
    values = {fact.key: fact.value for fact in plan.facts}
    missing = {item.capability: item.reason for item in plan.unavailable}
    parts: list[str] = []
    for capability in plan.capabilities:
        definition = require_exposed(capability)
        presentation = definition.presentation
        if presentation is None:
            raise ValueError("fact_presentation_missing")
        if capability in missing:
            reason_text = {"FACT_UNKNOWN":"неизвестно", "FACT_STALE":"данные устарели",
                           "SOURCE_UNAVAILABLE":"источник недоступен", "RESTRICTED":"доступ ограничен"}[missing[capability]]
            if english:
                reason_text = {"FACT_UNKNOWN":"unknown", "FACT_STALE":"stale data",
                               "SOURCE_UNAVAILABLE":"source unavailable", "RESTRICTED":"restricted"}[missing[capability]]
            parts.append(f"{labels_by_language[presentation]}: {reason_text}.")
        elif presentation == "position":
            lat, lon = (values[key] for key in definition.leaves)
            if not isinstance(lat, float) or not isinstance(lon, float):
                raise ValueError("position_missing")
            parts.append(("Coordinates: " if english else "Координаты: ") + spoken_coordinates(lat, lon, plan.request.language) + ".")
        elif presentation == "identity":
            raw = values[definition.leaves[0]]
            display = safe_aircraft_name(raw) if isinstance(raw, str) else None
            if display is None:
                raise ValueError("aircraft_name_invalid")
            parts.append(("You are in " if english else "Вы находитесь в ") + display + ".")
        else:
            value = values[definition.leaves[0]]
            if not isinstance(value, float):
                raise ValueError("numeric_fact_missing")
            parts.append(scalar_text(value, presentation, plan.request.language))
    if plan.summary:
        parts.append("This is a limited parameter summary, not a full aircraft assessment." if english else
                     "Это ограниченная сводка доступных параметров, не полная оценка состояния самолёта.")
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

    def accept(self, finalized: FinalizedGeneralText, *, delivery: Literal["pending", "completed", "failed", "cancelled", "unknown"] = "unknown",
               tts_started: bool = False) -> None:
        plan = finalized.plan
        if plan.request.context.revision != self.revision:
            raise ValueError("context_revision_changed")
        factual = plan.factual if isinstance(plan, MixedPlan) else plan
        capabilities = factual.capabilities if isinstance(factual, (FactPlan, UnavailablePlan)) else ()
        topic = capabilities[-1] if capabilities else "meta."+plan.topic if isinstance(plan, MetaPlan) else None
        entry = ContextExchange(interaction_id=plan.request.interaction_id, user=plan.request.source_text,
            reply=plan.dialogue.text if isinstance(plan, MixedPlan) else finalized.text if not isinstance(plan, (FactPlan, MetaPlan)) else None,
            requested_capabilities=capabilities,
            described_capabilities=plan.capabilities if isinstance(plan, MetaPlan) else (),
            topic=topic, language=plan.request.language, outcome=plan.kind,
            clarification_slot=plan.slot if isinstance(plan, ClarificationPlan) else None,
            unavailable_reason=plan.reason if isinstance(plan, UnavailablePlan) else None,
            semantic_understood=not (isinstance(plan, UnavailablePlan) and plan.reason in {"PROVIDER_UNAVAILABLE", "ADMISSION_REJECTED"}),
            core_fact_produced=isinstance(factual, FactPlan), delivery=delivery, tts_started=tts_started,
            response_fingerprint=source_hash(finalized.text))
        self._append(entry)

    def accept_fast_path(self, utterance: FinalizedUserUtterance, capabilities: tuple[str, ...],
                         text: str, *, epoch: str | None) -> None:
        """Observe an already admitted fast-path answer; no grant, value or new read."""
        self.project(epoch)
        for capability in capabilities:
            require_exposed(capability)
        if any(entry.interaction_id == utterance.interaction_id for entry in self.exchanges):
            raise ValueError("context_duplicate_fast_path")
        self._append(ContextExchange(interaction_id=utterance.interaction_id, user=utterance.text,
            language=utterance.input_language, topic=capabilities[-1], requested_capabilities=capabilities,
            outcome="CORE_FACT_AUTHORITATIVE", core_fact_produced=True, delivery="pending",
            response_fingerprint=source_hash(text)))

    def _append(self, entry: ContextExchange) -> None:
        self.exchanges = (*self.exchanges, entry)[-2:]
        self.revision += 1
        while len(ContextProjection(revision=self.revision, session_id=self.session_id,
                exchanges=self.exchanges).model_dump_json().encode("utf-8")) > 4096:
            self.exchanges = self.exchanges[1:]
        self.expires = self.clock() + timedelta(seconds=300)

    def update_delivery(self, finalized: FinalizedGeneralText, *,
                        delivery: Literal["completed", "failed", "cancelled", "unknown"],
                        tts_started: bool = False) -> None:
        """Update an accepted response, never re-admit semantics or infer hearing.

        An expired/reset/evicted exchange is not resurrected by a late delivery.
        This metadata update does not advance the semantic context revision.
        """
        self.record_delivery(finalized.plan.request.interaction_id, source_hash(finalized.text),
                             delivery=delivery, tts_started=tts_started)

    def record_delivery(self, identity: UUID, fingerprint: str, *,
                        delivery: Literal["completed", "failed", "cancelled", "unknown"],
                        tts_started: bool = False) -> None:
        if self.clock() >= self.expires:
            return
        self.exchanges = tuple(
            entry.model_copy(update={"delivery": delivery, "tts_started": tts_started})
            if entry.interaction_id == identity and entry.response_fingerprint == fingerprint
            and entry.delivery == "pending" else entry
            for entry in self.exchanges)
        while len(ContextProjection(revision=self.revision, session_id=self.session_id,
                exchanges=self.exchanges).model_dump_json().encode("utf-8")) > 4096:
            self.exchanges = self.exchanges[1:]


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
            context=self.context.project(epoch), personal_context=load_personal_context(),
            created_at=now, deadline=now + timedelta(seconds=12))
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
        if isinstance(result, StateSummary):
            result = FactRequest(kind="FACT_REQUEST", capabilities=SUMMARY_CAPABILITIES)
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
            elif isinstance(result, MetaRequest):
                described = () if result.topic == "identity" else tuple(item.capability for item in CATALOG[:META_MAX_CATEGORIES])
                plan = MetaPlan(request=request, deadline=request.deadline, topic=result.topic,
                    capabilities=described, additional_categories=result.topic != "identity" and len(CATALOG) > META_MAX_CATEGORIES)
            elif isinstance(result, FactRequest):
                plan = self._facts(request, result, cancellation)
                if isinstance(proposal.result, StateSummary) and isinstance(plan, FactPlan):
                    plan = plan.model_copy(update={"summary": True})
            elif isinstance(result, Mixed):
                factual = self._facts(request, result.facts, cancellation)
                if not isinstance(factual, (FactPlan, UnavailablePlan)):
                    raise ValueError("mixed_fact_plan_required")
                dialogue = DialoguePlan(request=request, deadline=request.deadline,
                                        text=result.dialogue.text, response_id=proposal.response_id)
                plan = MixedPlan(request=request, deadline=min(dialogue.deadline, factual.deadline),
                                 dialogue=dialogue, factual=factual)
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
        matches = [d for d in self.gateway.definitions() if d.name == CATALOG[0].tool and d.version == "1.0"
                   and d.capability == "world.ownship.read"]
        if len(matches) != 1 or cancellation.cancelled:
            raise ValueError("semantic_catalog_binding")
        tool_name = CATALOG[0].tool
        if tool_name is None:
            raise ValueError("fact_registry_read_binding")
        call = ToolCall(call_id=f"general-{request.interaction_id}", name=tool_name, version="1.0",
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
        selected: list[WorldFact[float | str]] = []
        unavailable: list[UnavailableFact] = []
        expires = request.deadline
        ordered = tuple(item.capability for item in CATALOG if item.capability in wanted.capabilities)
        if len(ordered) != len(wanted.capabilities):
            raise ValueError("fact_selection_not_exposed")
        for capability in ordered:
            definition = require_exposed(capability)
            if definition.snapshot_field is None:
                raise ValueError("fact_registry_selector")
            if definition.snapshot_field == "position":
                fact = WorldFact[WorldPosition].model_validate_json(json.dumps(snapshot.get("position")), strict=True)
            elif definition.snapshot_field == "aircraft":
                fact = WorldFact[AircraftIdentity].model_validate_json(json.dumps(snapshot.get("aircraft")), strict=True)
            elif definition.snapshot_field == "attitude":
                fact = WorldFact[WorldAttitude].model_validate_json(json.dumps(snapshot.get("attitude")), strict=True)
            else:
                fact = WorldFact[float].model_validate_json(json.dumps(snapshot.get(definition.snapshot_field)), strict=True)
            if (definition.tool != call.name or definition.version != call.version or definition.permission != tool.capability
                or fact.key != definition.world_key or fact.source != definition.source
                or fact.authority != definition.authority or fact.unit != definition.source_unit
                or fact.source not in p.sources or fact.authority not in p.authorities or fact.status not in p.fact_statuses
                or (fact.generation is not None and fact.generation not in p.generations)):
                raise ValueError("general_fact_authority")
            if fact.status != WorldFactStatus.KNOWN:
                reason = {WorldFactStatus.STALE: "FACT_STALE", WorldFactStatus.UNKNOWN: "FACT_UNKNOWN",
                          WorldFactStatus.UNAVAILABLE: "SOURCE_UNAVAILABLE", WorldFactStatus.RESTRICTED: "RESTRICTED"}[fact.status]
                unavailable.append(UnavailableFact.model_validate({"capability": capability, "reason": reason}))
                continue
            if (fact.observed_at is None or fact.age_seconds is None or fact.generation is None
                or len(p.generations) != 1 or p.max_age_seconds is None or fact.age_seconds > p.max_age_seconds
                or fact.observed_at > r.accepted_at
                or fact.age_seconds + (self.clock()-r.accepted_at).total_seconds() > definition.freshness_seconds):
                raise ValueError("general_fact_freshness")
            expires = min(expires, fact.observed_at+timedelta(seconds=definition.freshness_seconds),
                          r.accepted_at+timedelta(seconds=definition.freshness_seconds-fact.age_seconds))
            metadata = fact.model_dump(exclude={"key", "value", "unit"})
            projected: list[WorldFact[float | str]] = []
            for key in definition.leaves:
                value = fact.value if isinstance(fact.value, float) else getattr(fact.value, key.rsplit(".", 1)[-1], None)
                if value is None:
                    unavailable.append(UnavailableFact(capability=capability, reason="FACT_UNKNOWN"))
                    projected = []
                    break
                if isinstance(value, float):
                    if (definition.minimum is not None and value < definition.minimum
                        or definition.maximum is not None and (value > definition.maximum or
                            definition.presentation in {"heading", "yaw"} and value == definition.maximum)):
                        raise ValueError("selected_fact_range")
                elif isinstance(value, str) and definition.presentation == "identity":
                    from orion.hybrid_aircraft_core import safe_aircraft_name
                    if safe_aircraft_name(value) is None:
                        raise ValueError("selected_aircraft_name")
                else:
                    raise ValueError("selected_fact_type")
                projected.append(WorldFact[float | str](key=key, value=value, unit=definition.unit, **metadata))
            selected.extend(projected)
        if not selected:
            return UnavailablePlan.model_validate({"request": request.model_dump(), "deadline": request.deadline,
                                                   "reason": unavailable[0].reason if unavailable else "FACT_UNKNOWN",
                                                   "capabilities": ordered})
        return FactPlan(request=request, deadline=expires, capabilities=ordered, facts=tuple(selected), receipt=r,
                        unavailable=tuple(unavailable))
