"""Golden voice components hosted by the unchanged historical SRS service owner."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import queue
import time
from typing import cast

from orion.full_voice_capture import RadioTurnEventKind
from orion.full_voice_core import FullVoiceCore
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

        def fail(code):
            observation.record("exception", error_type=code)
            self._set(state=YandexSrsState.ERROR, phase="error", message=code, last_error=code)
            stopped.set()
            cancellation.cancel()

        password = request.eam_password.get_secret_value()
        diagnostics = SrsTransportDiagnostics(session_id, secrets=(request.api_key, password))
        endpoint = cast(FullVoiceSrsEndpoint, self._endpoint_factory(SrsRadioConfig(
            host=request.host, port=request.port, bot_name=request.bot_name,
            frequency_hz=request.frequency_hz, modulation=request.modulation,
            eam_password=password), stopped, diagnostics, self._set))
        native = NativeSpeechKitTurns(GrpcSpeechKitStreamingPort(), fail=fail)
        presentation = workflow = core_worker = None
        consumed = False
        try:
            # The existing Core already owns ingress and this WorldModel. Only
            # the field CLI's RecoveryLiveWorld ownership is omitted here.
            core = FullVoiceCore(build_tool_gateway(world=world_model))
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

            async def answer(utterance):
                nonlocal core_worker
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
                except Exception:
                    fail("turn_processing_failed")
                finally:
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
                        await native.end(event.identity, event.timestamp)
                if native.future is not None and native.future.done() and not native.future.cancelled() and not consumed:
                    consumed = True
                    utterance = await native.result()
                    observation.record("FinalizedUserUtterance" if utterance is not None else "None", utterance=utterance)
                    workflow = asyncio.create_task(answer(utterance), name="full-voice-answer")
            if workflow is not None:
                await workflow
        except BaseException as exc:
            observation.record("cancellation" if isinstance(exc, asyncio.CancelledError) else "exception",
                               error_type=type(exc).__name__)
            raise
        finally:
            observation.record("cancellation")
            stopped.set()
            cancellation.cancel()
            await native.close()
            if presentation is not None:
                await presentation.shutdown()
            await asyncio.to_thread(endpoint.stop)
            if core_worker is not None:
                await asyncio.gather(core_worker, return_exceptions=True)


full_voice_service = FullVoiceService(endpoint_factory=FullVoiceSrsEndpoint)
