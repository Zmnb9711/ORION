"""Bounded Live Golden Conversation Mode A orchestration.

The active Yandex/SRS session remains the sole speech-input and radio owner.
Yandex Realtime contributes only its finalized user transcript while its normal
generated response is cancelled and suppressed.  Qwen supplies one strict
FREE/OPERATIONAL decomposition; Core owns ATC, phraseology and composition.
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

from orion.airport_surface import RunwayAvailability, RunwayState
from orion.airport_surface_runtime import AirportSurfaceCoordinator
from orion.airport_tower_runtime import AirportTowerController
from orion.atc_core import AtcSessionIdentity
from orion.atc_operations import FreshnessClass
from orion.atc_runtime import AtcCoreFlow
from orion.communication_contracts import (
    CommunicationDomain,
    CommunicationPriority,
    CommunicationProfileId,
)
from orion.golden_takeoff_vertical import GoldenTakeoffVertical
from orion.mixed_conversation import (
    MixedOperationalIntent,
    MixedProviderStatus,
    build_mixed_composition,
    request_mixed_decomposition,
)
from orion.pilot_phraseology import PilotPhraseologyResolver
from orion.pilot_phraseology_catalog import build_pilot_phraseology_catalog
from orion.planner import PlannerProvider
from orion.realtime_audio_transport import RealtimeTranscriptSegment
from orion.realtime_test_evidence import realtime_test_evidence
from orion.srs_radio_adapter import SrsAdapterRuntime
from orion.srs_radio_transport import SrsState
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


CALLSIGN = "Viper 2-1"
RUNWAY = "07/25"
SPEECHKIT_VOICE = "jane"
SPEECHKIT_ROLE = "neutral"
PRIMARY_CASE_COUNT = 6
TX_TIMEOUT_S = 40.0
PROVIDER_DEADLINE_S = 60.0
PTT_TRANSCRIPT_SETTLE_S = 1.0
_COMPLETED_PTT_HISTORY = 8


@dataclass(frozen=True, slots=True)
class LiveGoldenCase:
    case_id: str
    prompt: str
    expects_free: bool
    expects_operational: bool
    primary: bool = True


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


@dataclass(slots=True)
class LiveGoldenRuntimeContext:
    api_key: str = field(repr=False)
    folder_id: str
    endpoint: LiveGoldenEndpoint
    main_session_id: str


@dataclass(slots=True)
class _PendingPhysicalPtt:
    transmission_id: str
    provider_audio_start_ms: int
    provider_audio_end_ms: int | None = None
    segments: list[tuple[int, RealtimeTranscriptSegment]] = field(default_factory=list)
    timer: threading.Timer | None = None
    timer_token: int = 0


@dataclass(frozen=True, slots=True)
class _CompletedPhysicalPtt:
    transmission_id: str
    provider_audio_start_ms: int
    provider_audio_end_ms: int


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

    def reset_and_arm(self) -> None:
        with self._lock:
            self._cancel_pending_locked()
            self._generation += 1
            self._armed = True
            self._completed.clear()
            self._seen_provider_items.clear()

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

    def transmission_started(
        self, transmission_id: str, provider_audio_start_ms: int
    ) -> None:
        with self._lock:
            if not self._armed or transmission_id in self._pending:
                return
            self._pending[transmission_id] = _PendingPhysicalPtt(
                transmission_id=transmission_id,
                provider_audio_start_ms=provider_audio_start_ms,
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
            if provider_item_id and provider_item_id in self._seen_provider_items:
                return
            position = (
                segment.provider_audio_start_ms
                if segment.provider_audio_start_ms is not None
                else segment.provider_audio_end_ms
            )
            if self._completed_for_position_locked(position) is not None:
                realtime_test_evidence.record(
                    "live_golden_stale_segment_dropped",
                    provider_item_id=provider_item_id,
                    provider_position_ms=position,
                )
                return
            pending = self._pending_for_position_locked(position)
            if pending is None:
                realtime_test_evidence.record(
                    "live_golden_unmatched_segment_dropped",
                    provider_item_id=provider_item_id,
                    provider_position_ms=position,
                )
                return
            if provider_item_id:
                self._seen_provider_items.add(provider_item_id)
            self._sequence += 1
            pending.segments.append((self._sequence, segment))
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
        )

    def _pending_for_position_locked(
        self, provider_audio_ms: int | None
    ) -> _PendingPhysicalPtt | None:
        ordered = tuple(self._pending.values())
        if provider_audio_ms is not None:
            for pending in ordered:
                end = pending.provider_audio_end_ms
                if provider_audio_ms >= pending.provider_audio_start_ms and (
                    end is None or provider_audio_ms <= end
                ):
                    return pending
            return None
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
            parts = [item.transcript.strip() for item in ordered if item.transcript.strip()]
            if parts:
                self._armed = False
                emission = (transmission_id, " ".join(parts), ordered[-1], len(parts))
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


ProviderFactory = Callable[[YandexQwenPlannerConfig], PlannerProvider]
SpeechKitFactory = Callable[[], SpeechKitTtsClient]


class LiveGoldenCaseRunner:
    def __init__(
        self,
        *,
        provider_factory: ProviderFactory = YandexQwenPlannerProvider,
        speechkit_factory: SpeechKitFactory = SpeechKitTtsClient,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._provider_factory = provider_factory
        self._speechkit_factory = speechkit_factory
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
    ) -> dict[str, object]:
        accepted_at = self._monotonic()
        interaction_id = uuid.uuid4()
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
        qwen_completed = self._monotonic()
        if cancelled():
            raise LiveGoldenCaseFailure("cancelled", "Live Golden case was cancelled")
        if (
            provider_result.status is not MixedProviderStatus.COMPLETED
            or provider_result.decomposition is None
        ):
            code = provider_result.error.code.value if provider_result.error else "invalid_output"
            raise LiveGoldenCaseFailure("qwen_decomposition", code)
        realtime_test_evidence.record(
            "live_golden_qwen_completed",
            probe_run_id=run_id,
            probe_case_id=case.case_id,
            status=provider_result.status.value,
            elapsed_ms=(qwen_completed - qwen_started) * 1000,
        )

        decomposition = provider_result.decomposition
        has_free = bool(decomposition.free_semantics)
        has_operational = decomposition.operational_intents == (
            MixedOperationalIntent.TAKEOFF_CLEARANCE_REQUEST,
        )
        if has_free != case.expects_free or has_operational != case.expects_operational:
            raise LiveGoldenCaseFailure(
                "semantic_gate",
                "Recognized FREE/OPERATIONAL shape did not match the selected field case",
            )

        identity, vertical = _controlled_takeoff_fixture(run_id, case.case_id)
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
            elapsed_ms=(atc_completed - qwen_completed) * 1000,
        )

        response_id = f"live-golden-{run_id[:8]}-{case.case_id}"
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

        artifact = None
        if capture_audio:
            artifact = realtime_test_evidence.record_live_golden_audio(
                run_id=run_id,
                case_id=case.case_id,
                response_id=response_id,
                pcm44=pcm44,
            )
        radio_submitted = self._monotonic()
        radio_runtime = context.endpoint.srs_adapter_runtime()
        realtime_test_evidence.record(
            "live_golden_radio_admission_requested",
            probe_run_id=run_id,
            probe_case_id=case.case_id,
            response_id=response_id,
            pcm_bytes=len(pcm44),
        )
        tx = context.endpoint.transmit_finalized_audio(
            response_id,
            pcm44,
            TX_TIMEOUT_S,
            source_domain=(
                CommunicationDomain.ATC
                if protected
                else CommunicationDomain.GENERAL
            ),
            priority=outcome.plan.priority,
            entity_id="orion.live-golden",
        )
        radio_completed = self._monotonic()
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
        usage = provider_result.usage
        protected_fragment = protected[0] if protected else None
        golden = outcome.golden_result
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
            "qwen_decomposition_completed": True,
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
            "speechkit_synthesized": bool(pcm44),
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
            "qwen": {
                "provider": getattr(provider, "provider_id", "unknown"),
                "model": QWEN_MODEL_ID,
                "provider_response_ids": list(usage.provider_request_ids) if usage else [],
                "attempts": usage.provider_attempts if usage else None,
                "decomposition": decomposition.model_dump(mode="json"),
                "operational_decision_present": False,
                "reasoning_passes_after_operational_truth": 0,
            },
            "atc": {
                "context_origin": "CONTROLLED GOLDEN ATC FIXTURE",
                "callsign": CALLSIGN,
                "runway": RUNWAY,
                "decision": (
                    golden.decision.model_dump(mode="json")
                    if golden is not None and golden.decision is not None
                    else None
                ),
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
                "input_is_local_final_composition": True,
                "pcm_input_rate_hz": 48_000,
                "pcm_radio_rate_hz": 44_100,
                "pcm_bytes": len(pcm44),
                "pcm_sha256": hashlib.sha256(pcm44).hexdigest(),
            },
            "audio_artifact": artifact or "NOT CAPTURED",
            "radio": {
                "correlation_id": response_id,
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
                "semantic_input_to_qwen_complete": _elapsed_ms(
                    qwen_started, qwen_completed
                ),
                "qwen_to_atc_phraseology_complete": _elapsed_ms(
                    qwen_completed, atc_completed
                ),
                "composition_to_speechkit_complete": _elapsed_ms(
                    atc_completed, speechkit_completed
                ),
                "speechkit_to_srs_tx_start": round(
                    float(tx.get("queue_to_first_tx_ms", 0.0)), 3
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
    ) -> None:
        self._lock = threading.RLock()
        self._context: LiveGoldenRuntimeContext | None = None
        self._runner = runner or LiveGoldenCaseRunner()
        self._status = LiveGoldenStatus()
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
            first = LIVE_GOLDEN_CORPUS[0]
            self._status = LiveGoldenStatus(
                state=LiveGoldenState.WAITING_INPUT,
                message="Speak the displayed case through the official SRS Client",
                compatible_session=True,
                run_id=run_id,
                main_session_id=context.main_session_id,
                case_id=first.case_id,
                next_prompt=first.prompt,
                case_number=1,
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
                    for item in LIVE_GOLDEN_CORPUS
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

    def accept_transcript(
        self,
        transcript: str,
        turn_id: str | None,
        event_id: str,
        provider_item_id: str,
        speech_stopped_at: float | None,
    ) -> None:
        text = transcript.strip()
        if not text:
            return
        with self._lock:
            if self._status.state is not LiveGoldenState.WAITING_INPUT:
                return
            if provider_item_id and provider_item_id in self._seen_provider_items:
                return
            if provider_item_id:
                self._seen_provider_items.add(provider_item_id)
            index = self._status.case_number - 1
            if index < 0 or index >= len(LIVE_GOLDEN_CORPUS):
                return
            context = self._context
            run_id = self._status.run_id
            if context is None or run_id is None:
                return
            generation = self._generation
            case = LIVE_GOLDEN_CORPUS[index]
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
            if next_index >= len(LIVE_GOLDEN_CORPUS):
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
            else:
                next_case = LIVE_GOLDEN_CORPUS[next_index]
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


def _controlled_takeoff_fixture(
    run_id: str,
    case_id: str,
) -> tuple[AtcSessionIdentity, GoldenTakeoffVertical]:
    core = AtcCoreFlow()
    surface = AirportSurfaceCoordinator(core)
    tower = AirportTowerController(surface)
    identity = AtcSessionIdentity(
        session_id=uuid.uuid5(uuid.NAMESPACE_URL, f"orion-live-golden:{run_id}:{case_id}"),
        mission_id="live-golden-controlled-fixture",
        aircraft_id=CALLSIGN,
        facility_id="Golden Tower",
    )
    core.open_session(identity)
    tower.assume_runway_control(identity.session_id, reason="controlled Live Golden fixture")
    tower.start_departure(session_id=identity.session_id, runway_id=RUNWAY)
    surface.runways.observe(
        RunwayState(
            runway_id=RUNWAY,
            availability=RunwayAvailability.CLEAR,
            freshness=FreshnessClass.FRESH,
            reason="controlled Live Golden fixture",
        )
    )
    catalog = build_pilot_phraseology_catalog()
    return identity, GoldenTakeoffVertical(
        tower,
        PilotPhraseologyResolver(catalog),
        profile_id=CommunicationProfileId.FAP_RUSSIAN_ATC,
    )


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


live_golden_conversation = LiveGoldenConversationService()
