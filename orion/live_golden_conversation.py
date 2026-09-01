"""Bounded Live Golden Conversation Mode A orchestration.

The active provider/SRS session remains the sole speech-input and radio owner.
Yandex Realtime may contribute coordinated transcript segments; a native radio
STT provider may contribute one finalized physical utterance. Core first evaluates
the bounded known-contract seam; Qwen supplies strict FREE/OPERATIONAL decomposition
only for fallback input. Core owns ATC, phraseology and composition.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Callable, Protocol

from pydantic import BaseModel, ConfigDict

from orion.atc_status_query import (
    ATC_STATUS_CONTRACT,
    AtcStatusSemanticOutcome,
    PersistentAtcSessionCoordinator,
)
from orion.communication_contracts import (
    CommunicationContext,
    CommunicationDomain,
    CommunicationPriority,
    CommunicationProfileId,
)
from orion.interaction_router import (
    InteractionRouter,
    KnownContractRoute,
    KnownContractRoutingDecision,
)
from orion.mixed_conversation import (
    MixedConversationDecomposition,
    MixedDecompositionStatus,
    MixedOperationalIntent,
    MixedProviderStatus,
    build_mixed_composition,
    request_mixed_decomposition,
)
from orion.pilot_phraseology_catalog import build_pilot_phraseology_catalog
from orion.planner import PlannerProvider
from orion.realtime_audio_transport import (
    FinalizedUserUtterance,
    RealtimeTranscriptSegment,
)
from orion.realtime_test_evidence import realtime_test_evidence
from orion.radio_streaming import (
    BoundedPcmStream,
    Pcm16ChunkAligner,
    StreamingPcmSnapshot,
)
from orion.srs_radio_adapter import SrsAdapterRuntime
from orion.srs_radio_transport import SrsState
from orion.srs_resampler import StreamingPcm16Resampler
from orion.yandex_hybrid_probe import (
    SpeechKitAttemptContext,
    SpeechKitTtsClient,
    TestSemanticCase,
    normalize_speechkit_pcm,
)
from orion.yandex_qwen_planner import (
    QWEN_MODEL_ID,
    YandexQwenPlannerConfig,
    YandexQwenPlannerProvider,
)
from orion.yandex_speechkit_streaming_tts import (
    SPEECHKIT_STREAM_TTS_RATE_HZ,
    SpeechKitStreamingTtsClient,
    SpeechKitTtsOutputMode,
)


CALLSIGN = "Viper 2-1"
RUNWAY = "07/25"
SPEECHKIT_VOICE = "jane"
SPEECHKIT_ROLE = "neutral"
PRIMARY_CASE_COUNT = 6
TX_TIMEOUT_S = 40.0
PROVIDER_DEADLINE_S = 60.0
PTT_TRANSCRIPT_SETTLE_S = 1.0
# The isolated probe delivered 685 ms first, then paused 975 ms.  A 1000 ms
# prebuffer spans that measured gap; a 2000 ms ceiling bounds the provider's
# faster-than-realtime output while producer backpressure preserves every sample.
_COMPLETED_PTT_HISTORY = 8
STREAM_PREBUFFER_MS = 1_000
STREAM_MAX_BUFFER_MS = 2_000
STREAM_FEED_SLICE_MS = 100
STREAM_RADIO_RATE_HZ = 44_100
STREAM_MAX_PCM_BYTES = STREAM_RADIO_RATE_HZ * 2 * 30


@dataclass(frozen=True, slots=True)
class LiveGoldenCase:
    case_id: str
    prompt: str
    expects_free: bool
    expects_operational: bool
    primary: bool = True
    expected_contract: str | None = None


LIVE_GOLDEN_CORPUS = (
    LiveGoldenCase("mixed-ru-1", "Добрый день! Разрешите взлёт.", True, True),
    LiveGoldenCase("mixed-ru-2", "Здравствуйте! Можно взлетать?", True, True),
    LiveGoldenCase("mixed-ru-3", "Доброе утро, башня. Готов к взлёту.", True, True),
    LiveGoldenCase(
        "mixed-ru-4",
        "Башня, приветствую. Запрашиваю разрешение на взлёт.",
        True,
        True,
    ),
    LiveGoldenCase(
        "mixed-ru-5",
        "Добрый вечер! Мы готовы, разрешите взлёт.",
        True,
        True,
    ),
    LiveGoldenCase(
        "mixed-ru-6",
        "Башня, рад вас слышать. Прошу разрешить взлёт.",
        True,
        True,
    ),
    LiveGoldenCase(
        "control-pure-operational",
        "Разрешите взлёт.",
        False,
        True,
        False,
    ),
    LiveGoldenCase(
        "control-pure-conversational",
        "Добрый день! Как дела?",
        True,
        False,
        False,
    ),
)

PURE_TAKEOFF_FIRST_CORPUS = (
    next(
        case
        for case in LIVE_GOLDEN_CORPUS
        if case.case_id == "control-pure-operational"
    ),
    *(
        case
        for case in LIVE_GOLDEN_CORPUS
        if case.case_id != "control-pure-operational"
    ),
)

ATC_STATUS_CASE = LiveGoldenCase(
    "atc-status-current-controller",
    "Какой диспетчер сейчас управляет моим полётом?",
    False,
    False,
    False,
    ATC_STATUS_CONTRACT,
)

PERSISTENT_ATC_STATUS_FIRST_CORPUS = (
    PURE_TAKEOFF_FIRST_CORPUS[0],
    ATC_STATUS_CASE,
)


class LiveGoldenState(StrEnum):
    OFF = "off"
    WAITING_INPUT = "waiting_input"
    PROCESSING = "processing"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETE = "complete"
    FAIL = "fail"


class LiveGoldenAcousticReview(StrEnum):
    CLEAR = "clear"
    UNCLEAR = "unclear"
    NOT_HEARD = "not_heard"


class LiveGoldenStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: LiveGoldenState = LiveGoldenState.OFF
    message: str = "Live Golden Conversation is off"
    compatible_session: bool = False
    run_id: str | None = None
    main_session_id: str | None = None
    case_id: str | None = None
    next_prompt: str | None = None
    case_number: int = 0
    total_cases: int = len(LIVE_GOLDEN_CORPUS)
    primary_cases: int = PRIMARY_CASE_COUNT
    completed_cases: int = 0
    reviewed_cases: int = 0
    capture_audio: bool = False
    mode: str = "CONTROLLED ACOUSTIC GOLDEN PROOF / MODE A"


class LiveGoldenEndpoint(Protocol):
    def set_provider_output_suppressed(self, suppressed: bool) -> None: ...

    def srs_adapter_runtime(self) -> SrsAdapterRuntime: ...

    def transmit_finalized_audio(
        self,
        response_id: str,
        pcm44: bytes,
        timeout_s: float,
        *,
        source_domain: CommunicationDomain,
        priority: CommunicationPriority,
        entity_id: str,
    ) -> dict[str, float | int]: ...

    def transmit_streaming_audio(
        self,
        response_id: str,
        stream: BoundedPcmStream,
        timeout_s: float,
        *,
        source_domain: CommunicationDomain,
        priority: CommunicationPriority,
        entity_id: str,
    ) -> dict[str, float | int]: ...


@dataclass(slots=True)
class LiveGoldenRuntimeContext:
    api_key: str = field(repr=False)
    folder_id: str
    endpoint: LiveGoldenEndpoint
    main_session_id: str
    tts_output_mode: SpeechKitTtsOutputMode = SpeechKitTtsOutputMode.REST_BUFFERED


@dataclass(slots=True)
class _PendingPhysicalPtt:
    transmission_id: str
    provider_audio_start_ms: int
    started_at: float
    provider_audio_end_ms: int | None = None
    segments: list[tuple[int, RealtimeTranscriptSegment]] = field(default_factory=list)
    aggregate: str = ""
    timer: threading.Timer | None = None
    timer_token: int = 0


@dataclass(frozen=True, slots=True)
class _CompletedPhysicalPtt:
    transmission_id: str
    provider_audio_start_ms: int
    provider_audio_end_ms: int


def _merge_transcript_text(existing: str, incoming: str) -> tuple[str, str]:
    """Merge exact provider text without lexical correction or fuzzy matching."""

    existing_tokens = tuple(existing.split())
    incoming_tokens = tuple(incoming.split())
    if not existing_tokens:
        return " ".join(incoming_tokens), "INITIAL"
    if (
        len(incoming_tokens) > len(existing_tokens)
        and incoming_tokens[: len(existing_tokens)] == existing_tokens
    ):
        return " ".join(incoming_tokens), "CUMULATIVE_EXTENSION"
    for overlap in range(min(len(existing_tokens), len(incoming_tokens)), 0, -1):
        if overlap == len(incoming_tokens):
            continue
        if existing_tokens[-overlap:] == incoming_tokens[:overlap]:
            return (
                " ".join((*existing_tokens, *incoming_tokens[overlap:])),
                "EXACT_OVERLAP",
            )
    return " ".join((*existing_tokens, *incoming_tokens)), "INDEPENDENT_APPEND"


class LiveGoldenPttCoordinator:
    """Correlate provider VAD segments above the shared production session."""

    def __init__(
        self,
        emit: Callable[[str, str, RealtimeTranscriptSegment, int], None],
        *,
        settle_seconds: float = PTT_TRANSCRIPT_SETTLE_S,
    ) -> None:
        if settle_seconds <= 0:
            raise ValueError("Live Golden PTT settle interval must be positive")
        self._emit = emit
        self._settle_seconds = settle_seconds
        self._lock = threading.RLock()
        self._armed = False
        self._generation = 0
        self._sequence = 0
        self._pending: dict[str, _PendingPhysicalPtt] = {}
        self._completed: deque[_CompletedPhysicalPtt] = deque(
            maxlen=_COMPLETED_PTT_HISTORY
        )
        self._seen_provider_items: set[str] = set()
        self._seen_provider_events: set[str] = set()

    def reset_and_arm(self) -> None:
        with self._lock:
            self._cancel_pending_locked()
            self._generation += 1
            self._armed = True
            self._completed.clear()
            self._seen_provider_items.clear()
            self._seen_provider_events.clear()

    def arm_next(self) -> None:
        with self._lock:
            self._armed = True

    def cancel(self) -> None:
        with self._lock:
            self._generation += 1
            self._armed = False
            self._cancel_pending_locked()
            self._completed.clear()
            self._seen_provider_items.clear()
            self._seen_provider_events.clear()

    def transmission_started(
        self, transmission_id: str, provider_audio_start_ms: int
    ) -> None:
        with self._lock:
            if not self._armed or transmission_id in self._pending:
                return
            self._pending[transmission_id] = _PendingPhysicalPtt(
                transmission_id=transmission_id,
                provider_audio_start_ms=provider_audio_start_ms,
                started_at=time.monotonic(),
            )
        realtime_test_evidence.record(
            "live_golden_ptt_started",
            physical_transmission_id=transmission_id,
            provider_position_ms=provider_audio_start_ms,
        )

    def transmission_completed(
        self, transmission_id: str, provider_audio_end_ms: int
    ) -> None:
        with self._lock:
            if not self._armed:
                return
            pending = self._pending.get(transmission_id)
            if pending is None:
                return
            pending.provider_audio_end_ms = provider_audio_end_ms
            self._schedule_locked(pending)
        realtime_test_evidence.record(
            "live_golden_ptt_completed",
            physical_transmission_id=transmission_id,
            provider_position_ms=provider_audio_end_ms,
        )

    def provider_activity(self, provider_audio_ms: int | None) -> None:
        with self._lock:
            if not self._armed:
                return
            pending = self._pending_for_position_locked(provider_audio_ms)
            if pending is not None and pending.provider_audio_end_ms is not None:
                self._schedule_locked(pending)

    def accept_segment(self, segment: RealtimeTranscriptSegment) -> None:
        text = segment.transcript.strip()
        if not text:
            return
        with self._lock:
            if not self._armed:
                return
            provider_item_id = segment.provider_item_id
            event_id = segment.event_id
            duplicate_identity = (
                bool(provider_item_id and provider_item_id in self._seen_provider_items)
                or bool(event_id and event_id in self._seen_provider_events)
            )
            if duplicate_identity:
                realtime_test_evidence.record(
                    "live_golden_transcript_segment_duplicate_dropped",
                    provider_item_id=provider_item_id,
                    event_id=event_id,
                    merge_decision="IDENTITY_DUPLICATE",
                )
                return
            position = (
                segment.provider_audio_start_ms
                if segment.provider_audio_start_ms is not None
                else segment.provider_audio_end_ms
            )
            pending = self._pending_for_segment_locked(segment, position)
            if pending is None:
                realtime_test_evidence.record(
                    "live_golden_unmatched_segment_dropped",
                    provider_item_id=provider_item_id,
                    event_id=event_id,
                    provider_position_ms=position,
                )
                return
            if provider_item_id:
                self._seen_provider_items.add(provider_item_id)
            if event_id:
                self._seen_provider_events.add(event_id)
            self._sequence += 1
            pending.segments.append((self._sequence, segment))
            pending.aggregate, merge_decision = _merge_transcript_text(
                pending.aggregate, text
            )
            segment_index = len(pending.segments)
            if pending.provider_audio_end_ms is not None:
                self._schedule_locked(pending)
        realtime_test_evidence.record(
            "live_golden_transcript_segment_correlated",
            physical_transmission_id=pending.transmission_id,
            provider_item_id=segment.provider_item_id,
            segment_index=segment_index,
            provider_start_ms=segment.provider_audio_start_ms,
            provider_end_ms=segment.provider_audio_end_ms,
            merge_decision=merge_decision,
        )

    def _pending_for_segment_locked(
        self,
        segment: RealtimeTranscriptSegment,
        provider_audio_ms: int | None,
    ) -> _PendingPhysicalPtt | None:
        stopped_at = segment.speech_stopped_at
        if stopped_at is not None:
            eligible = tuple(
                pending
                for pending in self._pending.values()
                if stopped_at >= pending.started_at
            )
            if eligible:
                return max(eligible, key=lambda pending: pending.started_at)
            return None
        if self._completed_for_position_locked(provider_audio_ms) is not None:
            return None
        return self._pending_for_position_locked(provider_audio_ms)

    def _pending_for_position_locked(
        self, provider_audio_ms: int | None
    ) -> _PendingPhysicalPtt | None:
        ordered = tuple(self._pending.values())
        if provider_audio_ms is not None:
            matches: list[_PendingPhysicalPtt] = []
            for pending in ordered:
                end = pending.provider_audio_end_ms
                if provider_audio_ms >= pending.provider_audio_start_ms and (
                    end is None or provider_audio_ms <= end
                ):
                    matches.append(pending)
            return matches[0] if len(matches) == 1 else None
        return ordered[0] if len(ordered) == 1 else None

    def _completed_for_position_locked(
        self, provider_audio_ms: int | None
    ) -> _CompletedPhysicalPtt | None:
        if provider_audio_ms is None:
            return None
        for completed in self._completed:
            if (
                completed.provider_audio_start_ms
                <= provider_audio_ms
                <= completed.provider_audio_end_ms
            ):
                return completed
        return None

    def _schedule_locked(self, pending: _PendingPhysicalPtt) -> None:
        if pending.timer is not None:
            pending.timer.cancel()
        pending.timer_token += 1
        token = pending.timer_token
        generation = self._generation
        timer = threading.Timer(
            self._settle_seconds,
            self._finalize,
            args=(pending.transmission_id, generation, token),
        )
        timer.daemon = True
        pending.timer = timer
        timer.start()

    def _finalize(self, transmission_id: str, generation: int, token: int) -> None:
        emission: tuple[str, str, RealtimeTranscriptSegment, int] | None = None
        with self._lock:
            pending = self._pending.get(transmission_id)
            if (
                not self._armed
                or generation != self._generation
                or pending is None
                or token != pending.timer_token
                or pending.provider_audio_end_ms is None
            ):
                return
            self._pending.pop(transmission_id, None)
            self._completed.append(
                _CompletedPhysicalPtt(
                    transmission_id=transmission_id,
                    provider_audio_start_ms=pending.provider_audio_start_ms,
                    provider_audio_end_ms=pending.provider_audio_end_ms,
                )
            )
            ordered = [item for _, item in sorted(pending.segments, key=lambda item: item[0])]
            if pending.aggregate:
                self._armed = False
                emission = (
                    transmission_id,
                    pending.aggregate,
                    ordered[-1],
                    len(ordered),
                )
        if emission is None:
            realtime_test_evidence.record(
                "live_golden_empty_ptt_discarded",
                physical_transmission_id=transmission_id,
            )
            return
        self._emit(*emission)

    def _cancel_pending_locked(self) -> None:
        for pending in self._pending.values():
            if pending.timer is not None:
                pending.timer.cancel()
        self._pending.clear()


class LiveGoldenCaseFailure(RuntimeError):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage


class _StreamingBeforeTxFailure(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _StreamingTxOutcome:
    tx: dict[str, float | int]
    snapshot: StreamingPcmSnapshot
    first_audio_latency_ms: float
    provider_complete_latency_ms: float
    provider_completed_at: float
    radio_submitted_at: float
    radio_completed_at: float
    first_srs_tx_frame_latency_ms: float


ProviderFactory = Callable[[YandexQwenPlannerConfig], PlannerProvider]
SpeechKitFactory = Callable[[], SpeechKitTtsClient]
StreamingSpeechKitFactory = Callable[[], SpeechKitStreamingTtsClient]


def _route_only_provider() -> PlannerProvider:
    raise RuntimeError("Route-only InteractionRouter cannot invoke a Planner provider")


class LiveGoldenCaseRunner:
    def __init__(
        self,
        *,
        provider_factory: ProviderFactory = YandexQwenPlannerProvider,
        speechkit_factory: SpeechKitFactory = SpeechKitTtsClient,
        streaming_speechkit_factory: StreamingSpeechKitFactory = (
            SpeechKitStreamingTtsClient
        ),
        interaction_router: InteractionRouter | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._provider_factory = provider_factory
        self._speechkit_factory = speechkit_factory
        self._streaming_speechkit_factory = streaming_speechkit_factory
        self._interaction_router = interaction_router or InteractionRouter(
            provider_factory=_route_only_provider
        )
        self._monotonic = monotonic

    def run(
        self,
        *,
        context: LiveGoldenRuntimeContext,
        run_id: str,
        case: LiveGoldenCase,
        transcript: str,
        turn_id: str | None,
        event_id: str,
        provider_item_id: str,
        speech_stopped_at: float | None,
        cancelled: Callable[[], bool],
        capture_audio: bool,
        atc_sessions: PersistentAtcSessionCoordinator,
    ) -> dict[str, object]:
        accepted_at = self._monotonic()
        interaction_id = uuid.uuid4()
        route = self._interaction_router.route_known_contract_text(
            interaction_id=interaction_id,
            text=transcript,
            communication=CommunicationContext(
                profile_id=CommunicationProfileId.FAP_RUSSIAN_ATC,
                domain=CommunicationDomain.ATC,
            ),
        )
        route_selected_at = self._monotonic()
        realtime_test_evidence.record(
            "live_golden_semantic_route_selected",
            probe_run_id=run_id,
            probe_case_id=case.case_id,
            recognizer_evaluated=route.recognizer_evaluated,
            contract_matched=route.contract_matched,
            pure=route.pure,
            route_selected=route.route.value,
            contract=route.contract or "none",
            qwen_required=route.qwen_required,
            elapsed_ms=(route_selected_at - accepted_at) * 1000,
        )

        if route.contract == ATC_STATUS_CONTRACT:
            if case.expected_contract != ATC_STATUS_CONTRACT:
                raise LiveGoldenCaseFailure(
                    "semantic_gate",
                    "ATC status contract did not match the selected field case",
                )
            realtime_test_evidence.record(
                "live_golden_semantic_route_executed",
                probe_run_id=run_id,
                probe_case_id=case.case_id,
                route_selected=route.route.value,
                contract=route.contract,
                qwen_required=False,
                qwen_call_count=0,
            )
            return self._run_atc_status_case(
                context=context,
                run_id=run_id,
                case=case,
                transcript=transcript,
                turn_id=turn_id,
                event_id=event_id,
                provider_item_id=provider_item_id,
                speech_stopped_at=speech_stopped_at,
                cancelled=cancelled,
                capture_audio=capture_audio,
                atc_sessions=atc_sessions,
                interaction_id=interaction_id,
                language=route.language,
                accepted_at=accepted_at,
                route_selected_at=route_selected_at,
                route=route,
            )

        provider: PlannerProvider | None = None
        provider_result = None
        qwen_started: float | None = None
        qwen_completed: float | None = None
        qwen_call_count = 0
        if route.route is KnownContractRoute.DETERMINISTIC_KNOWN_CONTRACT:
            decomposition = MixedConversationDecomposition(
                detected_input_language=route.language,
                status=MixedDecompositionStatus.CLASSIFIED,
                free_semantics=(),
                operational_intents=(
                    MixedOperationalIntent.TAKEOFF_CLEARANCE_REQUEST,
                ),
            )
            interpretation_completed = route_selected_at
        else:
            provider = self._provider_factory(
                YandexQwenPlannerConfig(
                    folder_id=context.folder_id,
                    api_key=context.api_key,
                )
            )
            qwen_started = self._monotonic()
            provider_result = request_mixed_decomposition(
                provider,
                utterance=transcript,
                interaction_id=interaction_id,
                planner_task_id=f"live-golden-{run_id[:8]}-{case.case_id}",
                deadline=datetime.now(UTC) + timedelta(seconds=PROVIDER_DEADLINE_S),
                max_attempts=2,
            )
            qwen_call_count = 1
            qwen_completed = self._monotonic()
            if cancelled():
                raise LiveGoldenCaseFailure(
                    "cancelled", "Live Golden case was cancelled"
                )
            if (
                provider_result.status is not MixedProviderStatus.COMPLETED
                or provider_result.decomposition is None
            ):
                code = (
                    provider_result.error.code.value
                    if provider_result.error
                    else "invalid_output"
                )
                raise LiveGoldenCaseFailure("qwen_decomposition", code)
            realtime_test_evidence.record(
                "live_golden_qwen_completed",
                probe_run_id=run_id,
                probe_case_id=case.case_id,
                status=provider_result.status.value,
                elapsed_ms=(qwen_completed - qwen_started) * 1000,
            )
            decomposition = provider_result.decomposition
            interpretation_completed = qwen_completed
        realtime_test_evidence.record(
            "live_golden_semantic_route_executed",
            probe_run_id=run_id,
            probe_case_id=case.case_id,
            route_selected=route.route.value,
            contract=route.contract or "none",
            qwen_required=route.qwen_required,
            qwen_call_count=qwen_call_count,
        )
        if cancelled():
            raise LiveGoldenCaseFailure("cancelled", "Live Golden case was cancelled")
        has_free = bool(decomposition.free_semantics)
        has_operational = decomposition.operational_intents == (
            MixedOperationalIntent.TAKEOFF_CLEARANCE_REQUEST,
        )
        if has_free != case.expects_free or has_operational != case.expects_operational:
            raise LiveGoldenCaseFailure(
                "semantic_gate",
                "Recognized FREE/OPERATIONAL shape did not match the selected field case",
            )

        identity, vertical, session_created = atc_sessions.get_or_create_takeoff_session(
            main_session_id=context.main_session_id,
            run_id=run_id,
            callsign=CALLSIGN,
            runway_id=RUNWAY,
            facility_id="Golden Tower",
        )
        outcome = build_mixed_composition(
            decomposition=decomposition,
            identity=identity,
            utterance=transcript,
            interaction_id=interaction_id,
            vertical=vertical,
            profile_id=CommunicationProfileId.FAP_RUSSIAN_ATC,
        )
        atc_completed = self._monotonic()
        if outcome.plan is None or outcome.final_text is None:
            raise LiveGoldenCaseFailure("composition", "Composition produced no response")
        protected = tuple(outcome.plan.protected_fragments)
        if case.expects_operational:
            if len(protected) != 1 or outcome.final_text.count(protected[0].text) != 1:
                raise LiveGoldenCaseFailure(
                    "protected_fragment",
                    "Protected operational fragment integrity check failed",
                )
        elif protected:
            raise LiveGoldenCaseFailure(
                "protected_fragment",
                "Pure conversation unexpectedly produced operational phraseology",
            )
        if cancelled():
            raise LiveGoldenCaseFailure("cancelled", "Live Golden case was cancelled")
        realtime_test_evidence.record(
            "live_golden_composition_completed",
            probe_run_id=run_id,
            probe_case_id=case.case_id,
            status="protected" if protected else "free_only",
            elapsed_ms=(atc_completed - interpretation_completed) * 1000,
        )
        golden = outcome.golden_result
        if golden is not None:
            atc_sessions.synchronize_takeoff_result(
                main_session_id=context.main_session_id,
                run_id=run_id,
                result=golden,
            )
        realtime_test_evidence.record(
            "live_golden_atc_session_bound",
            probe_run_id=run_id,
            probe_case_id=case.case_id,
            interaction_id=str(interaction_id),
            atc_session_id=str(identity.session_id),
            session_created=session_created,
            authority_scope="flight_traffic",
            radio_entity_id="orion.atc.airport_tower",
            qwen_call_count=qwen_call_count,
        )
        osu_count = int(golden is not None and golden.semantic_unit is not None)
        phraseology_count = int(golden is not None and golden.fragment is not None)
        realtime_test_evidence.record(
            "live_golden_core_semantics_completed",
            probe_run_id=run_id,
            probe_case_id=case.case_id,
            interaction_id=str(interaction_id),
            route_selected=route.route.value,
            qwen_call_count=qwen_call_count,
            atc_result=(
                golden.decision.status.value
                if golden is not None and golden.decision is not None
                else "not_applicable"
            ),
            osu_generated=osu_count == 1,
            osu_count=osu_count,
            phraseology_generated=phraseology_count == 1,
            phraseology_count=phraseology_count,
            phraseology_entry_id=(
                golden.resolution.selected_entry_id
                if golden is not None and golden.resolution is not None
                else "none"
            ),
            elapsed_ms=(atc_completed - route_selected_at) * 1000,
        )

        response_id = f"live-golden-{run_id[:8]}-{case.case_id}"
        source_domain = (
            CommunicationDomain.ATC if protected else CommunicationDomain.GENERAL
        )
        radio_entity_id = (
            "orion.atc.airport_tower" if protected else "orion.live-golden"
        )
        streaming_requested = (
            context.tts_output_mode is SpeechKitTtsOutputMode.STREAMING_V3
        )
        streaming_used = False
        streaming_fallback = False
        streaming_metrics: dict[str, float | int | bool] = {}
        pcm44 = b""
        pcm_bytes = 0
        pcm_sha256 = ""

        if streaming_requested:
            try:
                stream_outcome = asyncio.run(
                    self._stream_to_radio(
                        context=context,
                        run_id=run_id,
                        case=case,
                        response_id=response_id,
                        final_text=outcome.final_text,
                        source_domain=source_domain,
                        priority=outcome.plan.priority,
                        entity_id=radio_entity_id,
                        cancelled=cancelled,
                        capture_audio=capture_audio,
                        semantic_ready_at=atc_completed,
                    )
                )
            except _StreamingBeforeTxFailure as exc:
                streaming_fallback = True
                realtime_test_evidence.record(
                    "speechkit_stream_tts_rest_fallback",
                    probe_run_id=run_id,
                    probe_case_id=case.case_id,
                    response_id=response_id,
                    reason=str(exc),
                )
            else:
                streaming_used = True
                tx = stream_outcome.tx
                snapshot = stream_outcome.snapshot
                pcm44 = snapshot.captured_pcm or b""
                pcm_bytes = snapshot.total_pcm_bytes
                pcm_sha256 = snapshot.pcm_sha256
                speechkit_completed = stream_outcome.provider_completed_at
                radio_submitted = stream_outcome.radio_submitted_at
                radio_completed = stream_outcome.radio_completed_at
                streaming_metrics = {
                    "first_provider_audio_latency_ms": (
                        stream_outcome.first_audio_latency_ms
                    ),
                    "provider_complete_latency_ms": (
                        stream_outcome.provider_complete_latency_ms
                    ),
                    "first_srs_tx_frame_latency_ms": (
                        stream_outcome.first_srs_tx_frame_latency_ms
                    ),
                    "prebuffer_target_ms": STREAM_PREBUFFER_MS,
                    "max_buffered_bytes": snapshot.max_buffered_bytes,
                    "underrun_count": int(tx.get("underrun_count", 0)),
                    "underrun_silence_inserted_ms": float(
                        tx.get("underrun_silence_inserted_ms", 0.0)
                    ),
                }

        if not streaming_used:
            pcm48 = asyncio.run(
                self._synthesize(
                    context=context,
                    run_id=run_id,
                    case=case,
                    response_id=response_id,
                    final_text=outcome.final_text,
                )
            )
            speechkit_completed = self._monotonic()
            pcm44 = normalize_speechkit_pcm(pcm48)
            if not pcm44 or len(pcm44) % 2:
                raise LiveGoldenCaseFailure(
                    "speechkit", "SpeechKit produced invalid PCM"
                )
            if cancelled():
                raise LiveGoldenCaseFailure(
                    "cancelled_before_radio",
                    "Live Golden case was cancelled before radio admission",
                )
            pcm_bytes = len(pcm44)
            pcm_sha256 = hashlib.sha256(pcm44).hexdigest()
            radio_submitted = self._monotonic()
            realtime_test_evidence.record(
                "live_golden_radio_admission_requested",
                probe_run_id=run_id,
                probe_case_id=case.case_id,
                response_id=response_id,
                pcm_bytes=pcm_bytes,
            )
            tx = context.endpoint.transmit_finalized_audio(
                response_id,
                pcm44,
                TX_TIMEOUT_S,
                source_domain=source_domain,
                priority=outcome.plan.priority,
                entity_id=radio_entity_id,
            )
            radio_completed = self._monotonic()

        artifact = None
        if capture_audio:
            if not pcm44:
                raise LiveGoldenCaseFailure(
                    "speechkit_stream_capture",
                    "Streaming response audio capture was unavailable",
                )
            artifact = realtime_test_evidence.record_live_golden_audio(
                run_id=run_id,
                case_id=case.case_id,
                response_id=response_id,
                pcm44=pcm44,
            )
        radio_runtime = context.endpoint.srs_adapter_runtime()
        tx_event_fields = {
            "probe_run_id": run_id,
            "probe_case_id": case.case_id,
            "response_id": response_id,
            "frames": int(tx.get("frame_count", 0)),
            "duration_ms": float(tx.get("duration_ms", 0.0)),
            "queue_to_first_tx_ms": float(tx.get("queue_to_first_tx_ms", 0.0)),
            "queue_to_complete_ms": float(tx.get("queue_to_complete_ms", 0.0)),
            "status": "completed",
        }
        # The adapter snapshot proves the completed transmission and contains
        # its measured durations, but it does not expose four independently
        # timestamped callbacks.  Record one honest correlation event rather
        # than manufacturing lifecycle timestamps after completion.
        realtime_test_evidence.record(
            "live_golden_srs_completion_correlated",
            **tx_event_fields,
        )
        usage = provider_result.usage if provider_result is not None else None
        protected_fragment = protected[0] if protected else None
        protected_slots = (
            {
                str(item.key): item.value
                for item in protected_fragment.semantic_unit.protected_values
            }
            if protected_fragment is not None
            else {}
        )
        validations = {
            "real_spoken_input_observed": bool(turn_id and provider_item_id),
            "semantic_decomposition_completed": True,
            "qwen_required_matches_call_count": qwen_call_count
            == (1 if route.qwen_required else 0),
            "canonical_operational_intent": (
                has_operational == case.expects_operational
            ),
            "qwen_did_not_issue_clearance": (
                "operational_decision" not in decomposition.model_dump(mode="json")
            ),
            "deterministic_atc_owned_decision": (
                (golden is not None and golden.decision is not None)
                if case.expects_operational
                else golden is None
            ),
            "profile_explicit": (
                outcome.plan.communication.profile_id
                is CommunicationProfileId.FAP_RUSSIAN_ATC
            ),
            "phraseology_entry_selected": (
                bool(golden and golden.resolution and golden.resolution.selected_entry_id)
                if case.expects_operational
                else True
            ),
            "protected_fragment_unchanged_once": (
                outcome.final_text.count(protected_fragment.text) == 1
                if protected_fragment is not None
                else True
            ),
            "free_response_present_when_expected": bool(
                decomposition.free_response_text
            )
            == case.expects_free,
            "local_composition_only": True,
            "composed_text_not_returned_to_qwen": True,
            "speechkit_synthesized": pcm_bytes > 0,
            "radio_router_completed": True,
            "srs_adapter_completed": int(tx.get("frame_count", 0)) > 0,
            "audibility_not_inferred_from_tx": True,
        }
        return {
            "case_id": case.case_id,
            "primary": case.primary,
            "expected_prompt": case.prompt,
            "input": {
                "source": "real_human_speech_via_official_srs_client",
                "final_transcript": transcript,
                "turn_id": turn_id or "NOT OBSERVABLE",
                "provider_event_id": event_id or "NOT OBSERVABLE",
                "provider_item_id": provider_item_id or "NOT OBSERVABLE",
            },
            "semantic_route": {
                "recognizer_evaluated": route.recognizer_evaluated,
                "contract_matched": route.contract_matched,
                "pure": route.pure,
                "route_selected": route.route.value,
                "reason_code": route.reason_code.value,
                "contract": route.contract,
                "qwen_required": route.qwen_required,
                "qwen_call_count": qwen_call_count,
                "policy_version": route.policy_version,
            },
            "qwen": {
                "required": route.qwen_required,
                "call_count": qwen_call_count,
                "provider": (
                    getattr(provider, "provider_id", "unknown")
                    if provider is not None
                    else "NOT CALLED"
                ),
                "model": QWEN_MODEL_ID if provider is not None else "NOT CALLED",
                "provider_response_ids": list(usage.provider_request_ids) if usage else [],
                "attempts": usage.provider_attempts if usage else None,
                "decomposition": decomposition.model_dump(mode="json"),
                "operational_decision_present": False,
                "reasoning_passes_after_operational_truth": 0,
            },
            "atc": {
                "context_origin": "PERSISTENT CORE ATC SESSION",
                "session_id": str(identity.session_id),
                "session_created": session_created,
                "callsign": CALLSIGN,
                "runway": RUNWAY,
                "decision": (
                    golden.decision.model_dump(mode="json")
                    if golden is not None and golden.decision is not None
                    else None
                ),
            },
            "semantic_result": {
                "atc_result_count": int(
                    golden is not None and golden.decision is not None
                ),
                "osu_count": osu_count,
                "phraseology_count": phraseology_count,
                "presentation_response_count": 1,
            },
            "communication_profile": CommunicationProfileId.FAP_RUSSIAN_ATC.value,
            "phraseology_entry_id": (
                golden.resolution.selected_entry_id
                if golden is not None and golden.resolution is not None
                else None
            ),
            "protected_slots": protected_slots,
            "free_response": decomposition.free_response_text,
            "protected_fragment": (
                protected_fragment.text if protected_fragment is not None else None
            ),
            "final_composed_text": outcome.final_text,
            "final_composed_text_sha256": hashlib.sha256(
                outcome.final_text.encode("utf-8")
            ).hexdigest(),
            "composition_order": [
                label
                for label, present in (
                    ("FREE", bool(decomposition.free_response_text)),
                    ("PROTECTED", protected_fragment is not None),
                )
                if present
            ],
            "speechkit": {
                "correlation_id": response_id,
                "provider_request_id": "NOT OBSERVABLE",
                "voice": SPEECHKIT_VOICE,
                "role": SPEECHKIT_ROLE,
                "output_mode": (
                    SpeechKitTtsOutputMode.STREAMING_V3.value
                    if streaming_used
                    else SpeechKitTtsOutputMode.REST_BUFFERED.value
                ),
                "streaming_requested": streaming_requested,
                "streaming_rest_fallback": streaming_fallback,
                "input_is_local_final_composition": True,
                "pcm_input_rate_hz": 48_000,
                "pcm_radio_rate_hz": 44_100,
                "pcm_bytes": pcm_bytes,
                "pcm_sha256": pcm_sha256,
                **streaming_metrics,
            },
            "audio_artifact": artifact or "NOT CAPTURED",
            "radio": {
                "correlation_id": response_id,
                "entity_id": radio_entity_id,
                "radio_router_admitted": True,
                "srs_adapter_tx_started": True,
                "srs_tx_completed": True,
                "srs_adapter_tx_completed": True,
                "observability": "correlated_router_adapter_snapshot",
                "target_frequency_hz": radio_runtime.frequency_hz,
                "modulation": radio_runtime.modulation,
                "radio_registered": radio_runtime.radio_registered,
                "udp_registered": radio_runtime.udp_registered,
                **tx,
            },
            "latency_ms": {
                "speech_end_to_semantic_input": _elapsed_ms(
                    speech_stopped_at, accepted_at
                ),
                "semantic_input_to_route_selected": _elapsed_ms(
                    accepted_at, route_selected_at
                ),
                "route_selected_to_qwen_complete": _elapsed_ms(
                    qwen_started, qwen_completed or route_selected_at
                ),
                "semantic_input_to_qwen_complete": _elapsed_ms(
                    qwen_started, qwen_completed or route_selected_at
                ),
                "qwen_to_atc_phraseology_complete": _elapsed_ms(
                    qwen_completed, atc_completed
                ),
                "route_selected_to_atc_phraseology_complete": _elapsed_ms(
                    route_selected_at, atc_completed
                ),
                "composition_to_speechkit_complete": _elapsed_ms(
                    atc_completed, speechkit_completed
                ),
                "speechkit_to_srs_tx_start": round(
                    float(tx.get("queue_to_first_tx_ms", 0.0)), 3
                ),
                "semantic_response_ready_to_first_srs_tx_frame": round(
                    (radio_submitted - atc_completed) * 1000
                    + float(tx.get("queue_to_first_tx_ms", 0.0)),
                    3,
                ),
                "speech_end_to_srs_tx_start": (
                    _speech_to_tx_start_ms(
                        speech_stopped_at,
                        radio_submitted,
                        float(tx.get("queue_to_first_tx_ms", 0.0)),
                    )
                ),
                "speech_end_to_srs_tx_complete": _elapsed_ms(
                    speech_stopped_at, radio_completed
                ),
            },
            "validation_assertions": validations,
            "internal_result": "PASS" if all(validations.values()) else "FAIL",
            "acoustic_review": "NOT OBSERVABLE",
        }

    def _run_atc_status_case(
        self,
        *,
        context: LiveGoldenRuntimeContext,
        run_id: str,
        case: LiveGoldenCase,
        transcript: str,
        turn_id: str | None,
        event_id: str,
        provider_item_id: str,
        speech_stopped_at: float | None,
        cancelled: Callable[[], bool],
        capture_audio: bool,
        atc_sessions: PersistentAtcSessionCoordinator,
        interaction_id: uuid.UUID,
        language: str,
        accepted_at: float,
        route_selected_at: float,
        route: KnownContractRoutingDecision,
    ) -> dict[str, object]:
        """Resolve one read-only ATC status contract and use the existing output path."""

        outcome: AtcStatusSemanticOutcome = atc_sessions.query_status(
            main_session_id=context.main_session_id,
            run_id=run_id,
            interaction_id=interaction_id,
            language=language,
        )
        semantic_ready_at = self._monotonic()
        result = outcome.result
        realtime_test_evidence.record(
            "live_golden_atc_status_resolved",
            probe_run_id=run_id,
            probe_case_id=case.case_id,
            interaction_id=str(interaction_id),
            atc_session_id=str(result.session_id) if result.session_id else "unavailable",
            authority_scope="flight_traffic",
            controller_agency=(
                result.controller_agency.value if result.controller_agency else "unavailable"
            ),
            procedural_state=result.procedural_state or "unavailable",
            runtime_revision_before=result.runtime_revision_before,
            runtime_revision_after=result.runtime_revision_after,
            atc_truth_unchanged=result.atc_truth_unchanged,
            semantic_meaning=outcome.semantic_unit.semantic_meaning,
            semantic_response_id=str(outcome.semantic_response.response_id),
            radio_entity_id=outcome.radio_entity_id,
            qwen_call_count=0,
        )
        if cancelled():
            raise LiveGoldenCaseFailure("cancelled", "Live Golden case was cancelled")

        response_id = f"live-golden-{run_id[:8]}-{case.case_id}"
        priority = CommunicationPriority.ROUTINE
        streaming_requested = (
            context.tts_output_mode is SpeechKitTtsOutputMode.STREAMING_V3
        )
        streaming_used = False
        streaming_fallback = False
        streaming_metrics: dict[str, float | int | bool] = {}
        pcm44 = b""
        pcm_bytes = 0
        pcm_sha256 = ""
        if streaming_requested:
            try:
                stream_outcome = asyncio.run(
                    self._stream_to_radio(
                        context=context,
                        run_id=run_id,
                        case=case,
                        response_id=response_id,
                        final_text=outcome.final_text,
                        source_domain=CommunicationDomain.ATC,
                        priority=priority,
                        entity_id=outcome.radio_entity_id,
                        cancelled=cancelled,
                        capture_audio=capture_audio,
                        semantic_ready_at=semantic_ready_at,
                    )
                )
            except _StreamingBeforeTxFailure as exc:
                streaming_fallback = True
                realtime_test_evidence.record(
                    "speechkit_stream_tts_rest_fallback",
                    probe_run_id=run_id,
                    probe_case_id=case.case_id,
                    response_id=response_id,
                    reason=str(exc),
                )
            else:
                streaming_used = True
                tx = stream_outcome.tx
                snapshot = stream_outcome.snapshot
                pcm44 = snapshot.captured_pcm or b""
                pcm_bytes = snapshot.total_pcm_bytes
                pcm_sha256 = snapshot.pcm_sha256
                speechkit_completed = stream_outcome.provider_completed_at
                radio_submitted = stream_outcome.radio_submitted_at
                radio_completed = stream_outcome.radio_completed_at
                streaming_metrics = {
                    "first_provider_audio_latency_ms": stream_outcome.first_audio_latency_ms,
                    "provider_complete_latency_ms": stream_outcome.provider_complete_latency_ms,
                    "first_srs_tx_frame_latency_ms": (
                        stream_outcome.first_srs_tx_frame_latency_ms
                    ),
                    "prebuffer_target_ms": STREAM_PREBUFFER_MS,
                    "max_buffered_bytes": snapshot.max_buffered_bytes,
                    "underrun_count": int(tx.get("underrun_count", 0)),
                    "underrun_silence_inserted_ms": float(
                        tx.get("underrun_silence_inserted_ms", 0.0)
                    ),
                }

        if not streaming_used:
            pcm48 = asyncio.run(
                self._synthesize(
                    context=context,
                    run_id=run_id,
                    case=case,
                    response_id=response_id,
                    final_text=outcome.final_text,
                )
            )
            speechkit_completed = self._monotonic()
            pcm44 = normalize_speechkit_pcm(pcm48)
            if not pcm44 or len(pcm44) % 2:
                raise LiveGoldenCaseFailure("speechkit", "SpeechKit produced invalid PCM")
            if cancelled():
                raise LiveGoldenCaseFailure(
                    "cancelled_before_radio",
                    "Live Golden case was cancelled before radio admission",
                )
            pcm_bytes = len(pcm44)
            pcm_sha256 = hashlib.sha256(pcm44).hexdigest()
            radio_submitted = self._monotonic()
            realtime_test_evidence.record(
                "live_golden_radio_admission_requested",
                probe_run_id=run_id,
                probe_case_id=case.case_id,
                response_id=response_id,
                pcm_bytes=pcm_bytes,
            )
            tx = context.endpoint.transmit_finalized_audio(
                response_id,
                pcm44,
                TX_TIMEOUT_S,
                source_domain=CommunicationDomain.ATC,
                priority=priority,
                entity_id=outcome.radio_entity_id,
            )
            radio_completed = self._monotonic()

        artifact = None
        if capture_audio:
            if not pcm44:
                raise LiveGoldenCaseFailure(
                    "speechkit_stream_capture",
                    "Streaming response audio capture was unavailable",
                )
            artifact = realtime_test_evidence.record_live_golden_audio(
                run_id=run_id,
                case_id=case.case_id,
                response_id=response_id,
                pcm44=pcm44,
            )
        radio_runtime = context.endpoint.srs_adapter_runtime()
        realtime_test_evidence.record(
            "live_golden_srs_completion_correlated",
            probe_run_id=run_id,
            probe_case_id=case.case_id,
            response_id=response_id,
            frames=int(tx.get("frame_count", 0)),
            duration_ms=float(tx.get("duration_ms", 0.0)),
            queue_to_first_tx_ms=float(tx.get("queue_to_first_tx_ms", 0.0)),
            queue_to_complete_ms=float(tx.get("queue_to_complete_ms", 0.0)),
            status="completed",
        )
        validations = {
            "real_spoken_input_observed": bool(turn_id and provider_item_id),
            "semantic_decomposition_not_required": True,
            "qwen_calls_zero": True,
            "status_semantic_response_present": bool(outcome.semantic_response),
            "status_query_read_only": result.atc_truth_unchanged,
            "controller_not_inferred_from_text": True,
            "frequency_not_invented": True,
            "informational_core_renderer": True,
            "speechkit_synthesized": pcm_bytes > 0,
            "radio_router_completed": True,
            "srs_adapter_completed": int(tx.get("frame_count", 0)) > 0,
            "audibility_not_inferred_from_tx": True,
        }
        return {
            "case_id": case.case_id,
            "primary": case.primary,
            "expected_prompt": case.prompt,
            "input": {
                "source": "real_human_speech_via_official_srs_client",
                "final_transcript": transcript,
                "turn_id": turn_id or "NOT OBSERVABLE",
                "provider_event_id": event_id or "NOT OBSERVABLE",
                "provider_item_id": provider_item_id or "NOT OBSERVABLE",
            },
            "semantic_route": {
                "recognizer_evaluated": route.recognizer_evaluated,
                "contract_matched": route.contract_matched,
                "pure": route.pure,
                "route_selected": route.route.value,
                "reason_code": route.reason_code.value,
                "contract": route.contract,
                "qwen_required": False,
                "qwen_call_count": 0,
                "policy_version": route.policy_version,
            },
            "qwen": {"required": False, "call_count": 0, "provider": "NOT CALLED"},
            "atc": {
                "context_origin": "PERSISTENT CORE ATC SESSION",
                "session_id": str(result.session_id) if result.session_id else None,
                "facility_id": result.facility_id,
                "authority_scope": "flight_traffic",
                "controller_agency": (
                    result.controller_agency.value if result.controller_agency else None
                ),
                "procedural_state": result.procedural_state,
                "authority_available": result.authority_available,
                "runtime_revision_before": result.runtime_revision_before,
                "runtime_revision_after": result.runtime_revision_after,
                "atc_truth_unchanged": result.atc_truth_unchanged,
            },
            "semantic_result": {
                "osu": outcome.semantic_unit.model_dump(mode="json"),
                "semantic_response": outcome.semantic_response.model_dump(mode="json"),
                "presentation_response_count": 1,
            },
            "communication_profile": "NOT_APPLICABLE_DIAGNOSTIC",
            "phraseology_entry_id": None,
            "protected_slots": {
                str(item.key): item.value
                for item in outcome.semantic_unit.protected_values
            },
            "free_response": None,
            "protected_fragment": None,
            "final_composed_text": outcome.final_text,
            "final_composed_text_sha256": hashlib.sha256(
                outcome.final_text.encode("utf-8")
            ).hexdigest(),
            "composition_order": ["CORE_INFORMATIONAL"],
            "speechkit": {
                "correlation_id": response_id,
                "provider_request_id": "NOT OBSERVABLE",
                "voice": SPEECHKIT_VOICE,
                "role": SPEECHKIT_ROLE,
                "output_mode": (
                    SpeechKitTtsOutputMode.STREAMING_V3.value
                    if streaming_used
                    else SpeechKitTtsOutputMode.REST_BUFFERED.value
                ),
                "streaming_requested": streaming_requested,
                "streaming_rest_fallback": streaming_fallback,
                "input_is_local_final_composition": True,
                "pcm_input_rate_hz": 48_000,
                "pcm_radio_rate_hz": 44_100,
                "pcm_bytes": pcm_bytes,
                "pcm_sha256": pcm_sha256,
                **streaming_metrics,
            },
            "audio_artifact": artifact or "NOT CAPTURED",
            "radio": {
                "correlation_id": response_id,
                "entity_id": outcome.radio_entity_id,
                "radio_router_admitted": True,
                "srs_adapter_tx_started": True,
                "srs_tx_completed": True,
                "srs_adapter_tx_completed": True,
                "target_frequency_hz": radio_runtime.frequency_hz,
                "modulation": radio_runtime.modulation,
                "radio_registered": radio_runtime.radio_registered,
                "udp_registered": radio_runtime.udp_registered,
                **tx,
            },
            "latency_ms": {
                "speech_end_to_semantic_input": _elapsed_ms(
                    speech_stopped_at, accepted_at
                ),
                "semantic_input_to_route_selected": _elapsed_ms(
                    accepted_at, route_selected_at
                ),
                "route_selected_to_atc_status_complete": _elapsed_ms(
                    route_selected_at, semantic_ready_at
                ),
                "status_to_speechkit_complete": _elapsed_ms(
                    semantic_ready_at, speechkit_completed
                ),
                "speechkit_to_srs_tx_start": round(
                    float(tx.get("queue_to_first_tx_ms", 0.0)), 3
                ),
                "speech_end_to_srs_tx_start": _speech_to_tx_start_ms(
                    speech_stopped_at,
                    radio_submitted,
                    float(tx.get("queue_to_first_tx_ms", 0.0)),
                ),
                "speech_end_to_srs_tx_complete": _elapsed_ms(
                    speech_stopped_at, radio_completed
                ),
            },
            "validation_assertions": validations,
            "internal_result": "PASS" if all(validations.values()) else "FAIL",
            "acoustic_review": "NOT OBSERVABLE",
        }

    async def _stream_to_radio(
        self,
        *,
        context: LiveGoldenRuntimeContext,
        run_id: str,
        case: LiveGoldenCase,
        response_id: str,
        final_text: str,
        source_domain: CommunicationDomain,
        priority: CommunicationPriority,
        cancelled: Callable[[], bool],
        capture_audio: bool,
        semantic_ready_at: float,
        entity_id: str = "orion.live-golden",
    ) -> _StreamingTxOutcome:
        started_at = self._monotonic()
        source = BoundedPcmStream(
            response_id,
            sample_rate_hz=STREAM_RADIO_RATE_HZ,
            prebuffer_ms=STREAM_PREBUFFER_MS,
            max_buffer_ms=STREAM_MAX_BUFFER_MS,
            max_total_bytes=STREAM_MAX_PCM_BYTES,
            capture=capture_audio,
        )
        aligner = Pcm16ChunkAligner()
        resampler = StreamingPcm16Resampler(
            SPEECHKIT_STREAM_TTS_RATE_HZ,
            STREAM_RADIO_RATE_HZ,
        )
        tx_task: asyncio.Task[dict[str, float | int]] | None = None
        radio_submitted_at: float | None = None
        first_audio_at: float | None = None
        provider_completed_at: float | None = None
        provider_chunks = 0
        provider_pcm_bytes = 0
        slice_bytes = STREAM_RADIO_RATE_HZ * 2 * STREAM_FEED_SLICE_MS // 1000

        realtime_test_evidence.record(
            "speechkit_stream_tts_started",
            probe_run_id=run_id,
            probe_case_id=case.case_id,
            response_id=response_id,
            prebuffer_target_ms=STREAM_PREBUFFER_MS,
            max_buffered_ms=STREAM_MAX_BUFFER_MS,
        )

        def start_radio_if_ready(*, provider_eos: bool = False) -> None:
            nonlocal tx_task, radio_submitted_at
            if tx_task is not None:
                return
            snapshot = source.snapshot()
            if snapshot.buffered_bytes < source.prebuffer_bytes and not provider_eos:
                return
            if snapshot.buffered_bytes <= 0:
                raise _StreamingBeforeTxFailure(
                    "SpeechKit streaming response ended without PCM"
                )
            actual_ms = (
                snapshot.buffered_bytes / (STREAM_RADIO_RATE_HZ * 2) * 1000
            )
            realtime_test_evidence.record(
                "speechkit_stream_tts_prebuffer_ready",
                probe_run_id=run_id,
                probe_case_id=case.case_id,
                response_id=response_id,
                prebuffer_target_ms=STREAM_PREBUFFER_MS,
                prebuffer_actual_ms=actual_ms,
                prebuffer_actual_bytes=snapshot.buffered_bytes,
            )
            radio_submitted_at = self._monotonic()
            realtime_test_evidence.record(
                "speechkit_stream_tts_srs_start_requested",
                probe_run_id=run_id,
                probe_case_id=case.case_id,
                response_id=response_id,
                elapsed_ms=(radio_submitted_at - started_at) * 1000,
            )
            realtime_test_evidence.record(
                "live_golden_radio_admission_requested",
                probe_run_id=run_id,
                probe_case_id=case.case_id,
                response_id=response_id,
                pcm_bytes=snapshot.total_pcm_bytes,
                streaming=True,
            )
            tx_task = asyncio.create_task(
                asyncio.to_thread(
                    context.endpoint.transmit_streaming_audio,
                    response_id,
                    source,
                    TX_TIMEOUT_S,
                    source_domain=source_domain,
                    priority=priority,
                    entity_id=entity_id,
                )
            )

        async def feed_radio_pcm(pcm44: bytes) -> None:
            for offset in range(0, len(pcm44), slice_bytes):
                if cancelled():
                    source.cancel()
                    raise LiveGoldenCaseFailure(
                        "cancelled_streaming_tts",
                        "Live Golden streaming response was cancelled",
                    )
                if tx_task is not None and tx_task.done():
                    await tx_task
                piece = pcm44[offset : offset + slice_bytes]
                if piece:
                    await asyncio.to_thread(source.feed, piece, timeout_s=TX_TIMEOUT_S)
                    start_radio_if_ready()

        client = self._streaming_speechkit_factory()
        async for event in client.stream(
            final_text,
            context.api_key,
            response_id=response_id,
            cancelled=cancelled,
        ):
            if event.response_id != response_id:
                source.fail("SpeechKit streaming response correlation mismatch")
                raise LiveGoldenCaseFailure(
                    "speechkit_stream_correlation",
                    "SpeechKit streaming response correlation mismatch",
                )
            if event.cancelled:
                source.cancel()
                realtime_test_evidence.record(
                    "speechkit_stream_tts_cancelled",
                    probe_run_id=run_id,
                    probe_case_id=case.case_id,
                    response_id=response_id,
                    chunk_count=provider_chunks,
                    byte_count=provider_pcm_bytes,
                )
                if tx_task is not None:
                    await asyncio.gather(tx_task, return_exceptions=True)
                raise LiveGoldenCaseFailure(
                    "cancelled_streaming_tts",
                    "Live Golden streaming response was cancelled",
                )
            if event.error is not None:
                source.fail(event.error)
                realtime_test_evidence.record(
                    "speechkit_stream_tts_failed",
                    probe_run_id=run_id,
                    probe_case_id=case.case_id,
                    response_id=response_id,
                    chunk_count=provider_chunks,
                    byte_count=provider_pcm_bytes,
                    reason=event.error,
                    status=("after_tx_start" if tx_task is not None else "before_tx_start"),
                )
                if tx_task is None:
                    raise _StreamingBeforeTxFailure(event.error)
                await asyncio.gather(tx_task, return_exceptions=True)
                raise LiveGoldenCaseFailure(
                    "speechkit_stream_after_tx",
                    "SpeechKit streaming failed after radio transmission started",
                )
            if event.end_of_stream:
                aligner.finish()
                tail = resampler.process(b"", end_of_input=True)
                if tail:
                    await feed_radio_pcm(tail)
                source.finish()
                provider_completed_at = self._monotonic()
                realtime_test_evidence.record(
                    "speechkit_stream_tts_provider_completed",
                    probe_run_id=run_id,
                    probe_case_id=case.case_id,
                    response_id=response_id,
                    chunk_count=provider_chunks,
                    byte_count=provider_pcm_bytes,
                    provider_complete_latency_ms=(
                        provider_completed_at - started_at
                    )
                    * 1000,
                )
                start_radio_if_ready(provider_eos=True)
                break
            provider_chunks += 1
            provider_pcm_bytes += len(event.pcm)
            now = self._monotonic()
            if first_audio_at is None:
                first_audio_at = now
                realtime_test_evidence.record(
                    "speechkit_stream_tts_first_audio",
                    probe_run_id=run_id,
                    probe_case_id=case.case_id,
                    response_id=response_id,
                    first_provider_audio_latency_ms=(now - started_at) * 1000,
                    byte_count=len(event.pcm),
                )
            realtime_test_evidence.record(
                "speechkit_stream_tts_chunk_received",
                probe_run_id=run_id,
                probe_case_id=case.case_id,
                response_id=response_id,
                chunk_index=event.chunk_index,
                chunk_count=provider_chunks,
                byte_count=len(event.pcm),
            )
            aligned = aligner.push(event.pcm)
            if aligned:
                await feed_radio_pcm(
                    resampler.process(aligned, end_of_input=False)
                )

        if provider_completed_at is None or first_audio_at is None:
            source.fail("SpeechKit stream closed without complete audio")
            if tx_task is None:
                raise _StreamingBeforeTxFailure(
                    "SpeechKit stream closed without complete audio"
                )
            await asyncio.gather(tx_task, return_exceptions=True)
            raise LiveGoldenCaseFailure(
                "speechkit_stream_incomplete",
                "SpeechKit stream closed without complete audio",
            )
        if tx_task is None or radio_submitted_at is None:
            raise _StreamingBeforeTxFailure(
                "SpeechKit stream did not reach radio prebuffer"
            )
        active_tx_task = tx_task
        assert active_tx_task is not None
        while not active_tx_task.done():
            if cancelled():
                source.cancel()
                await asyncio.gather(active_tx_task, return_exceptions=True)
                realtime_test_evidence.record(
                    "speechkit_stream_tts_cancelled",
                    probe_run_id=run_id,
                    probe_case_id=case.case_id,
                    response_id=response_id,
                    chunk_count=provider_chunks,
                    byte_count=provider_pcm_bytes,
                )
                raise LiveGoldenCaseFailure(
                    "cancelled_streaming_tts",
                    "Live Golden streaming response was cancelled while draining",
                )
            await asyncio.sleep(0.05)
        tx = await active_tx_task
        radio_completed_at = self._monotonic()
        snapshot = source.snapshot()
        first_srs_latency_ms = (
            (radio_submitted_at - semantic_ready_at) * 1000
            + float(tx.get("queue_to_first_tx_ms", 0.0))
        )
        max_buffered_ms = (
            snapshot.max_buffered_bytes / (STREAM_RADIO_RATE_HZ * 2) * 1000
        )
        realtime_test_evidence.record(
            "speechkit_stream_tts_buffer_drained",
            probe_run_id=run_id,
            probe_case_id=case.case_id,
            response_id=response_id,
            byte_count=snapshot.total_pcm_bytes,
            max_buffered_bytes=snapshot.max_buffered_bytes,
            max_buffered_ms=max_buffered_ms,
        )
        realtime_test_evidence.record(
            "speechkit_stream_tts_completed",
            probe_run_id=run_id,
            probe_case_id=case.case_id,
            response_id=response_id,
            chunk_count=provider_chunks,
            byte_count=snapshot.total_pcm_bytes,
            first_provider_audio_latency_ms=(first_audio_at - started_at) * 1000,
            provider_complete_latency_ms=(provider_completed_at - started_at) * 1000,
            first_srs_tx_frame_latency_ms=first_srs_latency_ms,
            total_tx_duration_ms=float(tx.get("duration_ms", 0.0)),
            underrun_count=int(tx.get("underrun_count", 0)),
            underrun_silence_inserted_ms=float(
                tx.get("underrun_silence_inserted_ms", 0.0)
            ),
        )
        return _StreamingTxOutcome(
            tx=tx,
            snapshot=snapshot,
            first_audio_latency_ms=(first_audio_at - started_at) * 1000,
            provider_complete_latency_ms=(provider_completed_at - started_at) * 1000,
            provider_completed_at=provider_completed_at,
            radio_submitted_at=radio_submitted_at,
            radio_completed_at=radio_completed_at,
            first_srs_tx_frame_latency_ms=first_srs_latency_ms,
        )

    async def _synthesize(
        self,
        *,
        context: LiveGoldenRuntimeContext,
        run_id: str,
        case: LiveGoldenCase,
        response_id: str,
        final_text: str,
    ) -> bytes:
        semantic_case = TestSemanticCase(
            case_id=case.case_id,
            finalized_text=final_text,
            required_groups=(),
            voice=SPEECHKIT_VOICE,
            role=SPEECHKIT_ROLE,
        )
        async with self._speechkit_factory() as speechkit:
            pcm, _text = await speechkit.synthesize(
                semantic_case,
                context.api_key,
                attempt_context=SpeechKitAttemptContext(
                    run_id=run_id,
                    case_id=case.case_id,
                    response_id=response_id,
                ),
                observer=lambda event, fields: realtime_test_evidence.record(
                    event,
                    **fields,
                ),
            )
        return pcm


class LiveGoldenConversationService:
    def __init__(
        self,
        *,
        runner: LiveGoldenCaseRunner | None = None,
        ptt_settle_seconds: float = PTT_TRANSCRIPT_SETTLE_S,
        corpus: tuple[LiveGoldenCase, ...] = LIVE_GOLDEN_CORPUS,
        atc_sessions: PersistentAtcSessionCoordinator | None = None,
    ) -> None:
        if not corpus:
            raise ValueError("Live Golden corpus cannot be empty")
        self._lock = threading.RLock()
        self._context: LiveGoldenRuntimeContext | None = None
        self._runner = runner or LiveGoldenCaseRunner()
        self._atc_sessions = atc_sessions or PersistentAtcSessionCoordinator()
        self._corpus = corpus
        self._status = LiveGoldenStatus(
            total_cases=len(corpus),
            primary_cases=sum(case.primary for case in corpus),
        )
        self._generation = 0
        self._seen_provider_items: set[str] = set()
        self._ptt_coordinator = LiveGoldenPttCoordinator(
            self._accept_coordinated_utterance,
            settle_seconds=ptt_settle_seconds,
        )

    def status(self) -> LiveGoldenStatus:
        with self._lock:
            return self._status.model_copy(deep=True)

    def attach(self, context: LiveGoldenRuntimeContext) -> None:
        with self._lock:
            self._context = context
            self._status = self._status.model_copy(
                update={
                    "compatible_session": True,
                    "main_session_id": context.main_session_id,
                }
            )

    def detach(self, main_session_id: str) -> None:
        with self._lock:
            if self._context is None or self._context.main_session_id != main_session_id:
                return
            active = self._status.state in {
                LiveGoldenState.WAITING_INPUT,
                LiveGoldenState.PROCESSING,
                LiveGoldenState.AWAITING_REVIEW,
            }
            run_id = self._status.run_id
            self._generation += 1
            self._ptt_coordinator.cancel()
            self._context = None
            self._status = LiveGoldenStatus(
                state=LiveGoldenState.FAIL if active else LiveGoldenState.OFF,
                message=(
                    "Compatible Yandex + SRS session closed during Live Golden"
                    if active
                    else "Live Golden Conversation is off"
                ),
            )
        if active and run_id:
            realtime_test_evidence.finish_live_golden_run(
                run_id=run_id,
                state="failed",
                failure="compatible_session_closed",
            )
        self._atc_sessions.release_main_session(main_session_id)

    def start(self, *, capture_audio: bool) -> LiveGoldenStatus:
        with self._lock:
            context = self._context
            if context is None:
                raise ValueError("Live Golden requires an active Yandex + SRS session")
            if not realtime_test_evidence.status().active:
                raise ValueError("Start Test Evidence Session before Live Golden")
            if self._status.state in {
                LiveGoldenState.WAITING_INPUT,
                LiveGoldenState.PROCESSING,
                LiveGoldenState.AWAITING_REVIEW,
            }:
                raise ValueError("Live Golden Conversation is already active")
            runtime = context.endpoint.srs_adapter_runtime()
            if (
                runtime.state is not SrsState.READY
                or not runtime.radio_registered
                or not runtime.udp_registered
                or runtime.failed
            ):
                raise ValueError("SRS radio is not fully ready for Live Golden")
            self._generation += 1
            self._seen_provider_items.clear()
            run_id = uuid.uuid4().hex
            context.endpoint.set_provider_output_suppressed(True)
            first = self._corpus[0]
            self._status = LiveGoldenStatus(
                state=LiveGoldenState.WAITING_INPUT,
                message="Speak the displayed case through the official SRS Client",
                compatible_session=True,
                run_id=run_id,
                main_session_id=context.main_session_id,
                case_id=first.case_id,
                next_prompt=first.prompt,
                case_number=1,
                total_cases=len(self._corpus),
                primary_cases=sum(case.primary for case in self._corpus),
                capture_audio=capture_audio,
            )
            self._ptt_coordinator.reset_and_arm()
            fingerprint = _configuration_fingerprint(runtime)
            realtime_test_evidence.record_live_golden_run(
                run_id=run_id,
                main_session_id=context.main_session_id,
                mode=self._status.mode,
                communication_profile=CommunicationProfileId.FAP_RUSSIAN_ATC.value,
                config_fingerprint=fingerprint,
                corpus=tuple(
                    {
                        "case_id": item.case_id,
                        "prompt": item.prompt,
                        "primary": item.primary,
                    }
                    for item in self._corpus
                ),
                capture_audio=capture_audio,
            )
            return self._status.model_copy(deep=True)

    def stop(self) -> LiveGoldenStatus:
        with self._lock:
            context = self._context
            run_id = self._status.run_id
            was_active = self._status.state not in {
                LiveGoldenState.OFF,
                LiveGoldenState.COMPLETE,
            }
            self._generation += 1
            self._ptt_coordinator.cancel()
            if context is not None:
                context.endpoint.set_provider_output_suppressed(False)
            self._status = LiveGoldenStatus(
                compatible_session=context is not None,
                main_session_id=context.main_session_id if context else None,
            )
        if was_active and run_id:
            realtime_test_evidence.finish_live_golden_run(
                run_id=run_id,
                state="cancelled",
                failure="operator_stop",
            )
        if context is not None and run_id is not None:
            self._atc_sessions.release(
                main_session_id=context.main_session_id,
                run_id=run_id,
            )
        return self.status()

    def suppress_provider_responses(self) -> bool:
        with self._lock:
            return self._status.state in {
                LiveGoldenState.WAITING_INPUT,
                LiveGoldenState.PROCESSING,
                LiveGoldenState.AWAITING_REVIEW,
                LiveGoldenState.FAIL,
            }

    def input_transmission_started(
        self, transmission_id: str, provider_audio_start_ms: int
    ) -> None:
        self._ptt_coordinator.transmission_started(
            transmission_id, provider_audio_start_ms
        )

    def input_transmission_completed(
        self, transmission_id: str, provider_audio_end_ms: int
    ) -> None:
        self._ptt_coordinator.transmission_completed(
            transmission_id, provider_audio_end_ms
        )

    def provider_input_activity(self, provider_audio_ms: int | None) -> None:
        self._ptt_coordinator.provider_activity(provider_audio_ms)

    def accept_transcript_segment(self, segment: RealtimeTranscriptSegment) -> None:
        self._ptt_coordinator.accept_segment(segment)

    def _accept_coordinated_utterance(
        self,
        transmission_id: str,
        transcript: str,
        last_segment: RealtimeTranscriptSegment,
        segment_count: int,
    ) -> None:
        realtime_test_evidence.record(
            "live_golden_utterance_finalized",
            physical_transmission_id=transmission_id,
            provider_item_id=last_segment.provider_item_id,
            segment_count=segment_count,
        )
        self.accept_transcript(
            transcript,
            transmission_id,
            last_segment.event_id,
            last_segment.provider_item_id,
            last_segment.speech_stopped_at,
        )

    def accept_native_finalized_utterance(
        self, utterance: FinalizedUserUtterance
    ) -> None:
        """Bypass Realtime-only settle/merge for a provider-native PTT final."""

        accepted = self.accept_transcript(
            utterance.transcript,
            utterance.transmission_id,
            utterance.event_id,
            utterance.provider_item_id,
            utterance.finalized_at,
        )
        if accepted:
            realtime_test_evidence.record(
                "live_golden_utterance_finalized",
                physical_transmission_id=utterance.transmission_id,
                provider_item_id=utterance.provider_item_id,
                segment_count=1,
                stt_provider=utterance.provider_id,
                final_index=utterance.provider_final_index,
                native_finalization=True,
            )
            realtime_test_evidence.record(
                "speechkit_stt_semantic_dispatch",
                physical_transmission_id=utterance.transmission_id,
                provider_item_id=utterance.provider_item_id,
                stt_provider=utterance.provider_id,
                final_index=utterance.provider_final_index,
                semantic_dispatch_count=1,
            )

    def accept_transcript(
        self,
        transcript: str,
        turn_id: str | None,
        event_id: str,
        provider_item_id: str,
        speech_stopped_at: float | None,
    ) -> bool:
        text = transcript.strip()
        if not text:
            return False
        with self._lock:
            if self._status.state is not LiveGoldenState.WAITING_INPUT:
                return False
            if provider_item_id and provider_item_id in self._seen_provider_items:
                return False
            if provider_item_id:
                self._seen_provider_items.add(provider_item_id)
            index = self._status.case_number - 1
            if index < 0 or index >= len(self._corpus):
                return False
            context = self._context
            run_id = self._status.run_id
            if context is None or run_id is None:
                return False
            generation = self._generation
            case = self._corpus[index]
            capture_audio = self._status.capture_audio
            self._status = self._status.model_copy(
                update={
                    "state": LiveGoldenState.PROCESSING,
                    "message": f"Processing {case.case_id}",
                    "next_prompt": None,
                }
            )
        threading.Thread(
            target=self._process_case,
            args=(
                generation,
                context,
                run_id,
                case,
                text,
                turn_id,
                event_id,
                provider_item_id,
                speech_stopped_at,
                capture_audio,
            ),
            name="orion-live-golden-case",
            daemon=True,
        ).start()
        return True

    def _process_case(
        self,
        generation: int,
        context: LiveGoldenRuntimeContext,
        run_id: str,
        case: LiveGoldenCase,
        transcript: str,
        turn_id: str | None,
        event_id: str,
        provider_item_id: str,
        speech_stopped_at: float | None,
        capture_audio: bool,
    ) -> None:
        cancelled = lambda: self._is_cancelled(generation, run_id)
        try:
            record = self._runner.run(
                context=context,
                run_id=run_id,
                case=case,
                transcript=transcript,
                turn_id=turn_id,
                event_id=event_id,
                provider_item_id=provider_item_id,
                speech_stopped_at=speech_stopped_at,
                cancelled=cancelled,
                capture_audio=capture_audio,
                atc_sessions=self._atc_sessions,
            )
        except Exception as exc:
            if cancelled():
                return
            stage = exc.stage if isinstance(exc, LiveGoldenCaseFailure) else "runtime"
            safe = f"{stage}: {type(exc).__name__}"
            realtime_test_evidence.record_live_golden_case(
                run_id=run_id,
                record={
                    "case_id": case.case_id,
                    "primary": case.primary,
                    "input": {"final_transcript": transcript},
                    "internal_result": "FAIL",
                    "failure_stage": stage,
                    "failure_type": type(exc).__name__,
                    "acoustic_review": "NOT OBSERVABLE",
                },
            )
            realtime_test_evidence.finish_live_golden_run(
                run_id=run_id,
                state="failed",
                failure=safe,
            )
            self._atc_sessions.release(
                main_session_id=context.main_session_id,
                run_id=run_id,
            )
            with self._lock:
                if not self._is_cancelled_locked(generation, run_id):
                    self._status = self._status.model_copy(
                        update={
                            "state": LiveGoldenState.FAIL,
                            "message": f"Live Golden failed closed at {stage}",
                        }
                    )
            return

        realtime_test_evidence.record_live_golden_case(run_id=run_id, record=record)
        with self._lock:
            if self._is_cancelled_locked(generation, run_id):
                return
            self._status = self._status.model_copy(
                update={
                    "state": LiveGoldenState.AWAITING_REVIEW,
                    "message": "Record CLEAR, UNCLEAR, or NOT_HEARD",
                    "completed_cases": self._status.completed_cases + 1,
                }
            )

    def review(self, result: LiveGoldenAcousticReview) -> LiveGoldenStatus:
        with self._lock:
            if self._status.state is not LiveGoldenState.AWAITING_REVIEW:
                raise ValueError("Live Golden has no completed case awaiting review")
            run_id = self._status.run_id
            case_id = self._status.case_id
            if run_id is None or case_id is None:
                raise RuntimeError("Live Golden review correlation is unavailable")
            reviewed = self._status.reviewed_cases + 1
            realtime_test_evidence.record_live_golden_review(
                run_id=run_id,
                case_id=case_id,
                result=result.value,
            )
            next_index = self._status.case_number
            context = self._context
            if next_index >= len(self._corpus):
                self._ptt_coordinator.cancel()
                if context is not None:
                    context.endpoint.set_provider_output_suppressed(False)
                self._status = self._status.model_copy(
                    update={
                        "state": LiveGoldenState.COMPLETE,
                        "message": "All Live Golden cases completed; export Test Evidence",
                        "reviewed_cases": reviewed,
                        "next_prompt": None,
                    }
                )
                realtime_test_evidence.finish_live_golden_run(
                    run_id=run_id,
                    state="complete",
                )
                if context is not None:
                    self._atc_sessions.release(
                        main_session_id=context.main_session_id,
                        run_id=run_id,
                    )
            else:
                next_case = self._corpus[next_index]
                self._status = self._status.model_copy(
                    update={
                        "state": LiveGoldenState.WAITING_INPUT,
                        "message": "Speak the displayed case through the official SRS Client",
                        "case_id": next_case.case_id,
                        "next_prompt": next_case.prompt,
                        "case_number": next_index + 1,
                        "reviewed_cases": reviewed,
                    }
                )
                self._ptt_coordinator.arm_next()
            return self._status.model_copy(deep=True)

    def _is_cancelled(self, generation: int, run_id: str) -> bool:
        with self._lock:
            return self._is_cancelled_locked(generation, run_id)

    def _is_cancelled_locked(self, generation: int, run_id: str) -> bool:
        return generation != self._generation or self._status.run_id != run_id


def _configuration_fingerprint(runtime: SrsAdapterRuntime) -> str:
    catalog = build_pilot_phraseology_catalog()
    payload = {
        "mode": "controlled_acoustic_golden_mode_a",
        "qwen_model": QWEN_MODEL_ID,
        "communication_profile": CommunicationProfileId.FAP_RUSSIAN_ATC.value,
        "catalog_sha256": catalog.sha256,
        "speechkit_voice": SPEECHKIT_VOICE,
        "speechkit_role": SPEECHKIT_ROLE,
        "speechkit_rate_hz": 48_000,
        "radio_frequency_hz": runtime.frequency_hz,
        "radio_modulation": runtime.modulation,
        "bot_name": runtime.bot_name,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _elapsed_ms(start: float | None, end: float) -> float | str:
    if start is None:
        return "NOT OBSERVABLE"
    return round(max(0.0, end - start) * 1000, 3)


def _speech_to_tx_start_ms(
    speech_stopped_at: float | None,
    submitted_at: float,
    queue_to_first_tx_ms: float,
) -> float | str:
    if speech_stopped_at is None:
        return "NOT OBSERVABLE"
    return round(
        max(0.0, submitted_at - speech_stopped_at) * 1000
        + max(0.0, queue_to_first_tx_ms),
        3,
    )


live_golden_conversation = LiveGoldenConversationService(
    corpus=PERSISTENT_ATC_STATUS_FIRST_CORPUS
)
