"""Golden voice components hosted by the unchanged historical SRS service owner."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import queue
import time
from typing import cast

from orion.full_voice_capture import RadioTurnEventKind
from orion.full_voice_core import FullVoiceCore
from orion.conversational_core import eligible_conversation
from orion.conversational_presentation import ConversationVoice
from orion.communication_contracts import CommunicationDomain, CommunicationPriority
from orion.hybrid_aircraft_contracts import HybridRoute
from orion.hybrid_aircraft_core import HybridAircraftCore
from orion.interaction_router import InteractionRouter
from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter
from orion.informational_presentation import InformationalPresentation, InformationalStreamingTts
from orion.full_voice_srs import FullVoiceSrsEndpoint
from orion.full_voice_stt import NativeSpeechKitTurns
from orion.planner import PlannerCancellationToken
from orion.protected_presentation import tx_correlation
from orion.protected_streaming_presentation import StreamingProtectedPresentation
from orion.protected_streaming_tts import ProtectedStreamingTts
from orion.radio_contracts import RadioContext, RadioEntityRef, RadioModulation
from orion.realtime_test_evidence import realtime_test_evidence
from orion.speechkit_v3_stt_transport import GrpcSpeechKitStreamingPort
from orion.srs_diagnostics import SrsTransportDiagnostics
from orion.srs_radio_transport import SrsRadioConfig
from orion.tool_gateway import build_tool_gateway
from orion.world_model import world_model
from orion.yandex_realtime_provider import sanitize_yandex_error
from orion.yandex_qwen_planner import YandexQwenPlannerConfig, YandexQwenPlannerProvider
from orion.yandex_srs_live_core import YandexSrsLiveService, YandexSrsState


class _SttCoreObservation:
    """Best-effort observation only: no I/O, awaits, control or provider calls."""

    def __init__(self, session_id):
        self.session_id = session_id
        self.turn_id = None
        self.recorded = False

    def begin(self, identity):
        self.turn_id = str(identity)
        self.recorded = False

    def record(self, status, *, utterance=None, error_type=None):
        if self.turn_id is None or self.recorded:
            return
        self.recorded = True
        try:
            realtime_test_evidence.record_stt_core_boundary(
                turn_id=self.turn_id, realtime_session_id=self.session_id,
                status=status, transcript=utterance.text if utterance is not None else None,
                error_type=error_type,
            )
        except Exception:
            # Evidence failure must never change the accepted voice turn.
            pass


class FullVoiceService(YandexSrsLiveService):
    # Inherit __init__, start, status, _set and stop literally. The old Launcher
    # retains its existing selection, thread owner, six-second STOP and states.
    def _run(self, request, session_id, stop_event):
        try:
            asyncio.run(self._voice(request, session_id, stop_event))
        except Exception as exc:
            self._set(state=YandexSrsState.ERROR, phase="error",
                      message="Yandex SRS voice failed",
                      last_error=sanitize_yandex_error(exc, request.api_key))
        finally:
            with self._lock:
                if self._status.state is not YandexSrsState.ERROR:
                    self._status.state = YandexSrsState.STOPPED
                    self._status.phase = "idle"
                    self._status.message = "Yandex SRS voice stopped"

    async def _voice(self, request, session_id, stopped):
        cancellation = PlannerCancellationToken()
        observation = _SttCoreObservation(session_id)

        def observe_slice(event, **fields):
            try:
                realtime_test_evidence.record_aircraft_slice(event, realtime_session_id=session_id, **fields)
            except Exception:
                pass  # Evidence never changes accepted voice behavior.

        def fail(code):
            observation.record("exception", error_type=code)
            self._set(state=YandexSrsState.ERROR, phase="error", message=code, last_error=code)
            stopped.set()
            cancellation.cancel()

        def observe_conversation(event, **fields):
            try:
                realtime_test_evidence.record_conversation_slice(event, realtime_session_id=session_id, **fields)
            except Exception:
                pass  # The existing explicit evidence session is observation-only.

        def observe_interpreter(event, **fields):
            # Reuse existing bounded scalar projection; distinguish user and
            # barrier latency without provider bodies or a new evidence owner.
            observe_conversation("failed" if "failed" in event else "routing",
                route_source="INTERPRETER_" + event.upper(),
                completion_ms=fields.get("user_path_ms", fields.get("isolation_ms")),
                **{key: fields[key] for key in ("turn_id", "monotonic", "status", "failure_category") if key in fields})

        password = request.eam_password.get_secret_value()
        diagnostics = SrsTransportDiagnostics(session_id, secrets=(request.api_key, password))
        endpoint = cast(FullVoiceSrsEndpoint, self._endpoint_factory(SrsRadioConfig(
            host=request.host, port=request.port, bot_name=request.bot_name,
            frequency_hz=request.frequency_hz, modulation=request.modulation,
            eam_password=password), stopped, diagnostics, self._set))
        native = NativeSpeechKitTurns(GrpcSpeechKitStreamingPort(), fail=fail)
        presentation = workflow = core_worker = None
        informational: InformationalPresentation | None = None
        hybrid: HybridAircraftCore | None = None
        hybrid_active = False
        interpreter = None
        interpreter_warmup = None
        consumed = False
        try:
            # The existing Core already owns ingress and this WorldModel. Only
            # the field CLI's RecoveryLiveWorld ownership is omitted here.
            gateway = build_tool_gateway(world=world_model)
            core = FullVoiceCore(gateway)
            def no_interpreter_planner():
                raise RuntimeError("interpreter_cannot_call_planner")
            interpretation_router = InteractionRouter(provider_factory=no_interpreter_planner, bounded_ownship_gateway=gateway)
            await asyncio.to_thread(endpoint.connect_radio)
            endpoint.start()
            if endpoint.radio_router is None:
                raise RuntimeError("radio_router_unavailable")
            presentation = StreamingProtectedPresentation(ProtectedStreamingTts(request.api_key), endpoint.radio_router)
            await native.open(request.api_key)
            await asyncio.to_thread(endpoint.arm_physical_capture)
            runtime = endpoint.srs_adapter_runtime()
            entity = RadioEntityRef(entity_id="recovery.controlled.ownship", operational_callsign=runtime.bot_name,
                                    coalition={1: "red", 2: "blue"}.get(runtime.coalition))
            self._set(state=YandexSrsState.STREAMING, phase="streaming", message="Yandex SRS voice is running")
            # Optional separate semantic owner, never a readiness prerequisite.
            interpreter = WarmYandexAircraftInterpreter.configured(request.api_key, request.folder_id,
                observe=observe_interpreter)
            interpreter_warmup = asyncio.create_task(interpreter.prepare(), name="aircraft-interpreter-warmup")

            async def answer(utterance):
                nonlocal core_worker, hybrid, informational, hybrid_active
                identity = native.owner
                if identity is None:
                    fail("turn_owner_lost")
                    return
                try:
                    if utterance is not None:
                        core_worker = asyncio.create_task(asyncio.to_thread(core.run, utterance, cancellation))
                        result = await asyncio.shield(core_worker)
                        finalized = result.finalized
                        if finalized is not None:
                            observe_slice("routing", turn_id=str(identity), route="FROZEN_OWNSHIP", provider_call_count=0)
                            if stopped.is_set() or cancellation.cancelled:
                                raise RuntimeError("turn_cancelled_before_presentation")
                            context = RadioContext(
                                tx_correlation_id=tx_correlation(identity), interaction_id=identity,
                                turn_id=str(identity), session_id="recovery-full-voice",
                                source_domain=finalized.context.domain, communication_priority=finalized.priority,
                                radio_entity=entity, target_frequency_hz=251000000, modulation=RadioModulation.AM)
                            now = datetime.now(UTC)
                            remaining = min(5.0 - (r.provenance.max_age_seconds or 0.0)
                                - (now - r.receipt.completed_at).total_seconds()
                                for r in result.tool_results if r.provenance is not None)
                            endpoint.response_valid_until = time.monotonic() + remaining
                            outcome = await presentation.present(finalized, context)
                            if outcome.state != "completed":
                                fail("protected_presentation_not_completed")
                        elif result.status != "unsupported":
                            fail("core_semantics_not_completed")
                        else:
                            # Only the existing ownship router's unsupported outcome
                            # opens this new slice. It cannot steal a protected turn.
                            if stopped.is_set() or cancellation.cancelled:
                                return
                            hybrid_active = True
                            if hybrid is None:
                                hybrid = HybridAircraftCore(gateway, lambda: YandexQwenPlannerProvider(
                                    YandexQwenPlannerConfig(api_key=request.api_key, folder_id=request.folder_id)),
                                    observe=observe_slice)
                            core_worker = asyncio.create_task(asyncio.to_thread(hybrid.run, utterance, cancellation))
                            information = await asyncio.shield(core_worker)
                            if (information.route is HybridRoute.UNSUPPORTED and information.failure is None
                                    and not eligible_conversation(utterance.text)):
                                grant = await interpretation_router.interpret_aircraft_warm(
                                    utterance, interpreter, cancellation, observe=observe_interpreter)
                                if grant is not None:
                                    core_worker = asyncio.create_task(asyncio.to_thread(
                                        hybrid.run_interpreted, utterance, cancellation, grant, interpretation_router))
                                    information = await asyncio.shield(core_worker)
                            if information.finalized is not None:
                                if stopped.is_set() or cancellation.cancelled:
                                    raise RuntimeError("turn_cancelled_before_presentation")
                                if informational is None:
                                    informational = InformationalPresentation(InformationalStreamingTts(request.api_key,
                                        observe=lambda text: observe_slice("tts_input", turn_id=str(native.owner), tts_input=text)),
                                        endpoint.radio_router, authorize=hybrid.authorize, observe=observe_slice)
                                plan = information.finalized.plan
                                expiry = min(plan.deadline, plan.aircraft.expires_at) if plan.aircraft else plan.deadline
                                endpoint.response_valid_until = time.monotonic() + (expiry - datetime.now(UTC)).total_seconds()
                                context = RadioContext(tx_correlation_id=tx_correlation(identity), interaction_id=identity,
                                    turn_id=str(identity), session_id="recovery-full-voice", source_domain=CommunicationDomain.GENERAL,
                                    communication_priority=CommunicationPriority.ROUTINE, radio_entity=entity,
                                    target_frequency_hz=251000000, modulation=RadioModulation.AM)
                                previous_marks = endpoint.tx_marks
                                packet_before = endpoint.packet_id
                                outcome = await informational.present(information.finalized, context)
                                marks = endpoint.tx_marks if endpoint.tx_marks is not previous_marks else {}
                                observe_slice("response_terminal", turn_id=str(identity), tx_id=tx_correlation(identity),
                                    status=outcome.state, frames=endpoint.packet_id - packet_before,
                                    failure_stage="presentation" if outcome.failure else None,
                                    failure_category=outcome.failure.value if outcome.failure else None,
                                    tts_started=informational.marks.get("tts_started"),
                                    tts_first_pcm=informational.marks.get("tts_first_pcm"),
                                    tts_completed=informational.marks.get("tts_completed"),
                                    tts_pcm_bytes=informational.marks.get("tts_pcm_bytes"),
                                    radio_first_frame=marks.get("radio_first_frame"), radio_completed=marks.get("radio_completed"))
                                if outcome.state != "completed":
                                    fail("informational_presentation_not_completed")
                            elif information.route is HybridRoute.UNSUPPORTED and information.failure is None:
                                # Whole-source eligibility, never generic unsupported fallback.
                                # This owner receives no gateway, WorldModel or Planner.
                                if eligible_conversation(utterance.text):
                                    conversation = ConversationVoice(request.api_key, request.folder_id,
                                        endpoint, entity, observe=observe_conversation)
                                    try:
                                        await conversation.run(utterance, cancellation)
                                    finally:
                                        await conversation.shutdown()
                                else:
                                    observe_conversation("routing", turn_id=str(identity), route="UNSUPPORTED",
                                        conversation_provider_call_count=0, planner_call_count=0, tool_gateway_call_count=0)
                except Exception:
                    fail("turn_processing_failed")
                finally:
                    hybrid_active = False
                    self._set(output_chunks=endpoint.tx_frames)
                    if not stopped.is_set():
                        native.release(identity)
                        endpoint.release_turn(identity)

            # Historical owner controls lifetime; field CLI turn/time budgets
            # are not a replacement Launcher lifecycle.
            while not stopped.is_set():
                if endpoint.failure() is not None:
                    fail("srs_endpoint_failure")
                    break
                try:
                    event = await asyncio.to_thread(endpoint.turn_events.get, True, .05)
                except queue.Empty:
                    event = None
                if event is not None:
                    if event.kind is RadioTurnEventKind.START:
                        observation.begin(event.identity)
                        native.start(event.identity, event.timestamp)
                        consumed = False
                    elif event.kind is RadioTurnEventKind.PCM:
                        await native.audio(event.identity, event.pcm, event.timestamp)
                        self._set(input_chunks_delta=1)
                    else:
                        observe_conversation("physical_turn_end", turn_id=str(event.identity), monotonic=event.timestamp)
                        await native.end(event.identity, event.timestamp)
                if native.future is not None and native.future.done() and not native.future.cancelled() and not consumed:
                    consumed = True
                    utterance = await native.result()
                    observation.record("FinalizedUserUtterance" if utterance is not None else "None", utterance=utterance)
                    workflow = asyncio.create_task(answer(utterance), name="full-voice-answer")
            if workflow is not None:
                if hybrid_active:
                    cancellation.cancel()
                await workflow
        except BaseException as exc:
            observation.record("cancellation" if isinstance(exc, asyncio.CancelledError) else "exception",
                               error_type=type(exc).__name__)
            raise
        finally:
            observation.record("cancellation")
            stopped.set()
            cancellation.cancel()
            try:
                await native.close()
                if presentation is not None:
                    await presentation.shutdown()
                information_owner = cast(InformationalPresentation | None, informational)
                if information_owner is not None:
                    await information_owner.shutdown()
                await asyncio.to_thread(endpoint.stop)
                if core_worker is not None:
                    await asyncio.gather(core_worker, return_exceptions=True)
            finally:
                if interpreter is not None:
                    await interpreter.shutdown()
                if interpreter_warmup is not None:
                    results = await asyncio.gather(interpreter_warmup, return_exceptions=True)
                    for warmup_result in results:
                        if isinstance(warmup_result, Exception):
                            raise warmup_result


full_voice_service = FullVoiceService(endpoint_factory=FullVoiceSrsEndpoint)
