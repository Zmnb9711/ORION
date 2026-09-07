"""Dedicated bounded physical voice field host. Does not alter START LIVE."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
import logging
from pathlib import Path
import queue
import tempfile
import threading
import time
from uuid import uuid4
from typing import Any

from orion.full_voice_capture import RadioTurnEventKind
from orion.full_voice_core import FullVoiceCore
from orion.full_voice_live_world import RecoveryLiveWorld
from orion.full_voice_srs import FullVoiceSrsEndpoint
from orion.full_voice_stt import NativeSpeechKitTurns, FinalizedUserUtterance
from orion.planner import PlannerCancellationToken
from orion.protected_presentation import tx_correlation
from orion.protected_streaming_presentation import StreamingProtectedPresentation
from orion.protected_streaming_tts import ProtectedStreamingTts
from orion.radio_contracts import RadioContext, RadioEntityRef, RadioModulation
from orion.speechkit_v3_stt_transport import GrpcSpeechKitStreamingPort
from orion.srs_diagnostics import SrsTransportDiagnostics
from orion.srs_radio_transport import SrsRadioConfig
from orion.tool_gateway import build_tool_gateway
from orion.windows_credentials import VoiceCredential, default_voice_credential_store


class FieldDiagnostics(SrsTransportDiagnostics):
    def record(self, event: str, **fields: object) -> None:
        if event not in {"srs_tx_started", "tx_completed", "srs_adapter_tx_failed", "endpoint_error"}:
            return
        safe = {"event": event, "monotonic": time.monotonic()}
        for key in ("response_id", "tx_correlation_id", "frames"):
            value = fields.get(key)
            if isinstance(value, int) or (isinstance(value, str) and value.startswith("p7c-")):
                safe[key] = value
        with self._lock:
            self._events.append(safe)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def run_field(args, output: Path) -> dict:
    store = default_voice_credential_store()
    key = store.load(VoiceCredential.YANDEX_API_KEY)
    password = store.load(VoiceCredential.SRS_EAM_PASSWORD)
    if not key or not password:
        raise RuntimeError("secure_credentials_unavailable")
    stopped = threading.Event()
    cancellation = PlannerCancellationToken()
    report = {"milestone": "first_full_voice_vertical", "human_review": "REQUIRED", "turns": [], "failures": [], "ready": False}

    def persist() -> None:
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def fail(code: str) -> None:
        if not report["failures"]:
            report["failures"].append(code)
        stopped.set(); cancellation.cancel()

    diagnostics = FieldDiagnostics(uuid4().hex, runtime_dir=output)
    endpoint = FullVoiceSrsEndpoint(
        SrsRadioConfig(host="127.0.0.1", bot_name=args.callsign, eam_password=password),
        stopped, diagnostics, lambda **_fields: None,
    )
    live = RecoveryLiveWorld()
    native = NativeSpeechKitTurns(GrpcSpeechKitStreamingPort(), fail=fail)
    presentation = None
    workflow = None
    native_consumed = False
    core_worker = None
    try:
        await live.start()
        core = FullVoiceCore(build_tool_gateway(world=live.world))
        await asyncio.to_thread(endpoint.connect_radio)
        endpoint.start()
        if endpoint.radio_router is None:
            raise RuntimeError("radio_router_unavailable")
        presentation = StreamingProtectedPresentation(ProtectedStreamingTts(key), endpoint.radio_router)
        await native.open(key)
        await asyncio.to_thread(endpoint.arm_physical_capture)
        runtime = endpoint.srs_adapter_runtime()
        entity = RadioEntityRef(
            entity_id="recovery.controlled.ownship", operational_callsign=runtime.bot_name,
            coalition={1: "red", 2: "blue"}.get(runtime.coalition),
        )
        report["ready"] = True
        report["frequency_hz"] = 251000000
        report["radio_index"] = 1
        report["semantic_middle"] = "bounded_deterministic_ownship"
        report["qwen_calls"] = 0
        persist()
        print(json.dumps({"state": "READY_FOR_USER_PTT", "report": str(output / "report.json")}), flush=True)

        async def answer(utterance: FinalizedUserUtterance | None) -> None:
            nonlocal core_worker
            identity = native.owner
            if identity is None:
                fail("turn_owner_lost"); return
            row: dict[str, Any] = {"interaction_id": str(identity), "state": "empty_final"}
            row["input_evidence"] = native.safe_turn_evidence()
            try:
                if utterance is not None:
                    row.update(
                        transcript_sha256=_sha(utterance.text), transcript_characters=len(utterance.text),
                        provider_session_sha256=_sha(utterance.provider_session), final_index=utterance.final_index,
                        pcm_bytes=utterance.pcm_bytes,
                    )
                    marks = {name: getattr(utterance, name) for name in (
                        "physical_start", "physical_end", "last_pcm", "eou_sent", "final_received", "barrier_closed",
                    )}
                    core_worker = asyncio.create_task(asyncio.to_thread(core.run, utterance, cancellation))
                    core_result = await asyncio.shield(core_worker)
                    marks.update(core_result.marks)
                    row["state"] = core_result.status
                    row["marks"] = marks
                    finalized = core_result.finalized
                    if finalized is not None:
                        if stopped.is_set() or cancellation.cancelled:
                            raise RuntimeError("turn_cancelled_before_presentation")
                        context = RadioContext(
                            tx_correlation_id=tx_correlation(identity), interaction_id=identity,
                            turn_id=str(identity), session_id="recovery-full-voice",
                            source_domain=finalized.context.domain, communication_priority=finalized.priority,
                            radio_entity=entity, target_frequency_hz=251000000, modulation=RadioModulation.AM,
                        )
                        row["protected_text"] = finalized.text
                        row["protected_values"] = [v.model_dump(mode="json") for v in finalized.protected_fragments[0].semantic_unit.protected_values]
                        row["provenance"] = [p.model_dump(mode="json") for p in finalized.provenance]
                        row["tool_receipts"] = [r.receipt.model_dump(mode="json") for r in core_result.tool_results]
                        now_utc = datetime.now(UTC)
                        remaining = min(
                            5.0 - (r.provenance.max_age_seconds or 0.0)
                            - (now_utc - r.receipt.completed_at).total_seconds()
                            for r in core_result.tool_results if r.provenance is not None
                        )
                        endpoint.response_valid_until = time.monotonic() + remaining
                        outcome = await presentation.present(finalized, context)
                        row["state"] = outcome.state
                        row["tx_id"] = context.tx_correlation_id
                        marks.update(presentation.marks)
                        marks.update(endpoint.tx_marks)
                        if "radio_first_frame" in marks:
                            row["response_start_proxy_ms"] = (marks["radio_first_frame"] - utterance.physical_end) * 1000
                        if outcome.state != "completed":
                            fail("protected_presentation_not_completed")
                    elif core_result.status not in {"unsupported"}:
                        fail("core_semantics_not_completed")
            except Exception as exc:
                # Exception messages may contain provider/user data. Category only.
                row["state"] = "failed"
                row["failure_type"] = type(exc).__name__
                fail("turn_processing_failed")
            finally:
                row["terminal_monotonic"] = time.monotonic()
                report["turns"].append(row)
                if not stopped.is_set():
                    native.release(identity)
                    endpoint.release_turn(identity)
                persist()
                print(json.dumps({"state": row["state"], "turn": len(report["turns"]), "report": str(output / "report.json")}), flush=True)

        deadline = time.monotonic() + args.duration
        while not stopped.is_set() and len(report["turns"]) < args.turns and time.monotonic() < deadline:
            if endpoint.failure() is not None:
                fail("srs_endpoint_failure"); break
            try:
                event = await asyncio.to_thread(endpoint.turn_events.get, True, .05)
            except queue.Empty:
                event = None
            if event is not None:
                if event.kind is RadioTurnEventKind.START:
                    native.start(event.identity, event.timestamp)
                    native_consumed = False
                elif event.kind is RadioTurnEventKind.PCM:
                    await native.audio(event.identity, event.pcm, event.timestamp)
                else:
                    await native.end(event.identity, event.timestamp)
            if native.future is not None and native.future.done() and not native.future.cancelled() and not native_consumed:
                native_consumed = True
                workflow = asyncio.create_task(answer(await native.result()), name="full-voice-answer")
        if workflow is not None:
            await workflow
    finally:
        stopped.set(); cancellation.cancel()
        await native.close()
        if presentation is not None:
            report["presentation_shutdown_clean"] = await presentation.shutdown()
        await asyncio.to_thread(endpoint.stop)
        if core_worker is not None:
            await asyncio.gather(core_worker, return_exceptions=True)
        await live.close()
        report["transport_events"] = list(diagnostics.snapshot())
        report["closed_at"] = datetime.now(UTC).isoformat()
        persist()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--field", action="store_true", required=True)
    parser.add_argument("--callsign", default="ORION RECOVERY")
    parser.add_argument("--config-root", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=240)
    parser.add_argument("--turns", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.turns <= 3 or not 1 <= args.duration <= 240:
        parser.error("Field bounds: 1–3 turns, duration at most 240 seconds")
    output = Path(tempfile.mkdtemp(prefix="orion-full-voice-"))
    logging.disable(logging.CRITICAL)  # No generic provider/telemetry raw log bodies.
    try:
        report = asyncio.run(run_field(args, output))
        return 1 if report["failures"] else 0
    except KeyboardInterrupt:
        print(json.dumps({"state": "cancelled", "report": str(output / "report.json")}), flush=True)
        return 130
    except Exception as exc:
        print(json.dumps({"state": "failed", "failure_type": type(exc).__name__, "report": str(output / "report.json")}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
