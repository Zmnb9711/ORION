"""Intent-specific aircraft projection and deterministic local social composition."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
from threading import RLock
import time
from typing import Callable, Protocol
from uuid import UUID

from orion.flight_context import aircraft_display_name
from orion.full_voice_stt import FinalizedUserUtterance
from orion.hybrid_aircraft_contracts import (
    AircraftIdentityQueryResult, FinalizedInformationalText, HybridAircraftDecomposition,
    HybridRoute, InformationalResponsePlan, SocialAct,
)
from orion.interaction_contracts import CapabilityId
from orion.planner import PlannerCancellationToken
from orion.tool_gateway import ToolGateway
from orion.tool_gateway_contracts import ExecutionContext, ToolCall, ToolReceiptStatus, ToolResultStatus
from orion.world_model_contracts import AircraftIdentity, WorldFact, WorldFactAuthority, WorldFactSource, WorldFactStatus


AIRCRAFT_FORMS = frozenset({
    "в каком самолете я нахожусь", "на каком самолете я нахожусь",
    "на каком самолете я сейчас нахожусь", "какой у меня самолет",
})
SOCIAL_FORMS = {
    "добрый день": SocialAct.GREETING, "здравствуйте": SocialAct.GREETING,
    "и добрый день": SocialAct.GREETING,
    "спасибо": SocialAct.THANKS_ACKNOWLEDGEMENT,
    "как дела": SocialAct.SOCIAL_WELLBEING_QUERY,
}
SOCIAL_TEXT = {
    SocialAct.GREETING: "Добрый день!",
    SocialAct.THANKS_ACKNOWLEDGEMENT: "Пожалуйста.",
    SocialAct.SOCIAL_WELLBEING_QUERY: "Всё нормально, я на связи.",
}
UNAVAILABLE_TEXT = "Сейчас не удалось определить тип вашего самолёта."
_DELIMITERS = " \t\r\n.!?,"


def canonical(text: str) -> str:
    # Only case, ё/е, whitespace and terminal punctuation. Quotes are NOT removed.
    return " ".join(text.casefold().replace("ё", "е").strip(_DELIMITERS).split())


def classify_aircraft_identity_query(text: str) -> HybridRoute:
    normalized = canonical(text)
    if normalized in AIRCRAFT_FORMS:
        return HybridRoute.AIRCRAFT_IDENTITY
    if normalized == "какой это самолет":
        return HybridRoute.AMBIGUOUS
    return HybridRoute.UNSUPPORTED


def eligible_decomposition(text: str) -> bool:
    """Eligibility is not decomposition: provider must return the anchored spans."""
    if not text or len(text) > 4000 or re.search(r'[^А-Яа-яЁё\s.!?,]', text):
        return False
    words = set(re.findall(r"[а-я]+", text.casefold().replace("ё", "е")))
    vocabulary = set(" ".join((*AIRCRAFT_FORMS, *SOCIAL_FORMS)).split())
    return words <= vocabulary and bool(words & {"добрый", "здравствуйте", "спасибо", "дела"})


def validate_decomposition(text: str, value: HybridAircraftDecomposition) -> HybridAircraftDecomposition:
    checked = HybridAircraftDecomposition.model_validate(value.model_dump(), strict=True)
    position = 0
    social = []
    aircraft = 0
    for span in checked.spans:
        if not position <= span.start < span.end <= len(text):
            raise ValueError("invalid_source_span")
        if text[position:span.start].strip(_DELIMITERS):
            raise ValueError("uncovered_source_residue")
        part = canonical(text[span.start:span.end])
        if span.act == "AIRCRAFT_IDENTITY_QUERY":
            if part not in AIRCRAFT_FORMS:
                raise ValueError("invalid_aircraft_span")
            aircraft += 1
        else:
            act = SocialAct(span.act)
            if SOCIAL_FORMS.get(part) != act or act in social:
                raise ValueError("invalid_social_span")
            social.append(act)
        position = span.end
    if text[position:].strip(_DELIMITERS) or aircraft > 1 or len(social) > 2:
        raise ValueError("uncovered_or_excess_intent")
    return checked


def derive_route(validated: HybridAircraftDecomposition) -> HybridRoute:
    """Core-only closed mapping; called only AFTER complete source validation."""
    acts = tuple(span.act for span in validated.spans)
    aircraft = acts.count("AIRCRAFT_IDENTITY_QUERY")
    social = tuple(act for act in acts if act != "AIRCRAFT_IDENTITY_QUERY")
    if (not acts or aircraft > 1 or len(social) > 2 or len(set(social)) != len(social)
            or any(act not in {member.value for member in SocialAct} for act in social)):
        return HybridRoute.UNSUPPORTED
    if aircraft:
        return HybridRoute.FREE_PLUS_AIRCRAFT_IDENTITY if social else HybridRoute.AIRCRAFT_IDENTITY
    return HybridRoute.FREE_ONLY


def safe_aircraft_name(raw: str) -> str | None:
    # Unknown identifiers may not introduce arbitrary speech. Known aliases use
    # the existing repository registry; unknown compact DCS IDs retain identity.
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./+() -]{0,159}", raw) is None:
        return None
    display = aircraft_display_name(raw)
    if display == " ".join(raw.replace("_", " ").split()) and " " in raw:
        return None
    return display


def validate_aircraft(value: AircraftIdentityQueryResult, now: datetime) -> None:
    r = value.receipt
    identity = str(value.interaction_id)
    if (r.call_id != f"aircraft-{identity}" or r.interaction_id != identity or r.turn_id != identity
        or r.session_id != "recovery-full-voice" or r.actor_id != "hybrid-aircraft-core"
        or r.task_id is not None or r.idempotency_key is not None
        or r.tool_name != value.tool_name or r.tool_version != value.tool_version
        or r.status != ToolReceiptStatus.COMPLETED or not r.handler_started
        or value.source != WorldFactSource.DCS_EXPORT
        or value.authority != WorldFactAuthority.AUTHORITATIVE
        or r.completed_at > now or value.expires_at.tzinfo is None or now >= value.expires_at):
        raise ValueError("aircraft_provenance_or_expiry")
    if value.aircraft_type is not None:
        if (value.fact_status != WorldFactStatus.KNOWN or value.generation is None
            or value.age_seconds is None or value.observed_at is None
            or value.observed_at > r.completed_at or safe_aircraft_name(value.aircraft_type) is None
            or value.expires_at > value.observed_at + timedelta(seconds=5)
            or value.expires_at > r.accepted_at + timedelta(seconds=5-value.age_seconds)):
            raise ValueError("invalid_current_aircraft")


def render_informational(plan: InformationalResponsePlan, now: datetime) -> str:
    plan = InformationalResponsePlan.model_validate(plan.model_dump(), strict=True)
    if now >= plan.deadline:
        raise ValueError("informational_deadline")
    parts = [SOCIAL_TEXT[act] for act in plan.social_acts]
    if plan.aircraft is not None:
        validate_aircraft(plan.aircraft, now)
        display = safe_aircraft_name(plan.aircraft.aircraft_type) if plan.aircraft.aircraft_type else None
        parts.append(f"По данным DCS, вы находитесь в {display}." if display else UNAVAILABLE_TEXT)
    return " ".join(parts)


class Decomposer(Protocol):
    def decompose_aircraft(self, text: str, identity: UUID, deadline: datetime,
                          cancellation: PlannerCancellationToken, *,
                          observe: Callable[..., None] | None = None) -> HybridAircraftDecomposition: ...


@dataclass(frozen=True)
class HybridResult:
    route: HybridRoute
    finalized: FinalizedInformationalText | None = None
    failure: str | None = None


class HybridAircraftCore:
    """Borrowed gateway/provider. Bounded replay cache, no background owners."""
    def __init__(self, gateway: ToolGateway, provider_factory: Callable[[], Decomposer], *,
                 clock=lambda: datetime.now(UTC), observe=lambda _event, **_fields: None):
        self.gateway, self.provider_factory, self.clock, self.observe = gateway, provider_factory, clock, observe
        self._completed: dict[UUID, tuple[FinalizedUserUtterance, HybridResult]] = {}
        self._lock = RLock()

    def _emit(self, event, **fields):
        try:
            self.observe(event, monotonic=time.monotonic(), **fields)
        except Exception:
            pass

    def run(self, utterance: FinalizedUserUtterance, cancellation: PlannerCancellationToken) -> HybridResult:
        with self._lock:
            previous = self._completed.get(utterance.interaction_id)
            if previous:
                if previous[0] != utterance:
                    raise ValueError("hybrid_conflicting_replay")
                return previous[1]
            if len(self._completed) >= 64:
                raise ValueError("hybrid_identity_capacity")
            result = self._run(utterance, cancellation)
            self._completed[utterance.interaction_id] = (utterance, result)
            return result

    def authorize(self, finalized: FinalizedInformationalText) -> bool:
        """Bind admission to the actual Core execution, not a plausible fake receipt."""
        with self._lock:
            executed = self._completed.get(finalized.plan.interaction_id)
            return executed is not None and executed[1].finalized == finalized

    def _run(self, utterance, cancellation):
        identity, text = utterance.interaction_id, utterance.text
        deadline = self.clock() + timedelta(seconds=15)
        route = classify_aircraft_identity_query(text)
        stage = "routing"
        count = 0
        self._emit(stage, turn_id=str(identity), route=route.value, provider_call_count=0,
                   pure_aircraft=route == HybridRoute.AIRCRAFT_IDENTITY)

        def check():
            if cancellation.cancelled:
                raise ValueError("cancelled")
            if self.clock() >= deadline:
                raise ValueError("deadline")

        try:
            check()
            if utterance.input_language != "ru-RU":
                return HybridResult(HybridRoute.UNSUPPORTED)
            social = ()
            if route == HybridRoute.AMBIGUOUS:
                return HybridResult(route)
            if route == HybridRoute.UNSUPPORTED:
                if not eligible_decomposition(text):
                    return HybridResult(route)
                stage = "decomposition"
                provider = self.provider_factory()
                check()
                count = 1
                self._emit("decomposition_started", turn_id=str(identity), provider_call_count=count)
                decomposition = provider.decompose_aircraft(text, identity, deadline, cancellation,
                    observe=lambda event, **fields: self._emit(event, turn_id=str(identity),
                        provider_call_count=count, **fields))
                check()
                stage = "decomposition_validation"
                self._emit(stage, turn_id=str(identity), decomposition=decomposition.model_dump(mode="json"),
                           status="checking", provider_call_count=count, provider_category="completed")
                decomposition = validate_decomposition(text, decomposition)
                route = derive_route(decomposition)
                self._emit(stage, turn_id=str(identity), decomposition=decomposition.model_dump(mode="json"),
                           core_derived_route=route.value, status="accepted", provider_call_count=count, provider_category="completed")
                if route in {HybridRoute.UNSUPPORTED, HybridRoute.AMBIGUOUS}:
                    return HybridResult(route)
                social = tuple(SocialAct(s.act) for s in decomposition.spans if s.act != "AIRCRAFT_IDENTITY_QUERY")
            aircraft = None
            if route != HybridRoute.FREE_ONLY:
                stage = "authoritative_read"
                check()
                call = ToolCall(call_id=f"aircraft-{identity}", name="orion.world.ownship.get", version="1.0",
                    context=ExecutionContext(actor_id="hybrid-aircraft-core", interaction_id=str(identity),
                        turn_id=str(identity), session_id="recovery-full-voice", deadline=deadline,
                        allowed_capabilities=(CapabilityId("world.ownship.read"),)))
                self._emit("authoritative_read_started", turn_id=str(identity), tool_name=call.name,
                           tool_version=call.version, call_id=call.call_id)
                tool = self.gateway.execute(call)
                self._emit("authoritative_read_returned", turn_id=str(identity), tool_name=tool.tool_name,
                           tool_version=tool.tool_version, call_id=tool.receipt.call_id, status=tool.status.value)
                check()
                if (tool.status != ToolResultStatus.COMPLETED or tool.tool_name != call.name
                    or tool.tool_version != call.version or tool.call_id != call.call_id
                    or tool.output_schema != "orion.tool.output.ownship.v1"
                    or tool.capability != "world.ownship.read" or tool.data is None or tool.provenance is None):
                    raise ValueError("invalid_aircraft_tool_result")
                # Never retain/serialize the unrestricted ToolResult. Parse only this field.
                snapshot = tool.data.root["snapshot"]
                if not isinstance(snapshot, dict) or snapshot.get("schema_version") != "ia2.world.v1" or snapshot.get("query") != "ownship.current_state":
                    raise ValueError("invalid_aircraft_snapshot")
                generated = datetime.fromisoformat(str(snapshot.get("generated_at")))
                if not tool.receipt.accepted_at <= generated <= tool.receipt.completed_at:
                    raise ValueError("aircraft_snapshot_read_binding")
                fact = WorldFact[AircraftIdentity].model_validate(snapshot["aircraft"])
                provenance = tool.provenance
                if (fact.key != "ownship.aircraft" or fact.source not in provenance.sources
                    or fact.authority not in provenance.authorities or fact.status not in provenance.fact_statuses
                    or (fact.generation is not None and fact.generation not in provenance.generations)
                    or (fact.age_seconds is not None and (provenance.max_age_seconds is None or fact.age_seconds > provenance.max_age_seconds))):
                    raise ValueError("aircraft_provenance_mismatch")
                raw = fact.value.aircraft_type if fact.status == WorldFactStatus.KNOWN and fact.value else None
                if raw is not None and safe_aircraft_name(raw) is None:
                    raw = None
                expiry = min(deadline, tool.receipt.accepted_at + timedelta(seconds=5))
                if raw is not None:
                    if fact.observed_at is None or fact.age_seconds is None:
                        raise ValueError("aircraft_freshness_missing")
                    expiry = min(expiry, fact.observed_at + timedelta(seconds=5),
                                 tool.receipt.accepted_at + timedelta(seconds=5-fact.age_seconds))
                aircraft = AircraftIdentityQueryResult(interaction_id=identity, receipt=tool.receipt,
                    fact_status=fact.status, source=fact.source, authority=fact.authority,
                    observed_at=fact.observed_at, age_seconds=fact.age_seconds, generation=fact.generation,
                    aircraft_type=raw, expires_at=expiry)
                validate_aircraft(aircraft, self.clock())
                self._emit(stage, turn_id=str(identity), aircraft=aircraft.model_dump(mode="json"))
            stage = "local_composition"
            check()
            plan = InformationalResponsePlan(interaction_id=identity, social_acts=social, aircraft=aircraft, deadline=deadline)
            finalized = FinalizedInformationalText(plan=plan, text=render_informational(plan, self.clock()))
            self._emit(stage, turn_id=str(identity), plan=plan.model_dump(mode="json"), finalized_text=finalized.text)
            return HybridResult(route, finalized)
        except Exception as exc:
            from orion.yandex_qwen_planner import YandexPlannerCleanupError, YandexPlannerTransportError
            self._emit("failed", turn_id=str(identity), failure_stage=stage,
                       provider_call_count=count,
                       provider_category=exc.category.value if isinstance(exc, YandexPlannerTransportError) else type(exc).__name__,
                       status="cancelled" if cancellation.cancelled else "failed")
            # Cleanup failures must reach the existing truthful ERROR owner.
            if isinstance(exc, YandexPlannerCleanupError):
                raise
            return HybridResult(route, failure="cancelled" if cancellation.cancelled else stage)
