"""Explicit live DCS + one john request, paced local packet sink. NO SRS TX/PTT/Qwen."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import hashlib
import json
import logging
from pathlib import Path
import tempfile
import threading
import time
from uuid import uuid4

from orion.full_voice_core import FullVoiceCore
from orion.full_voice_field import FieldDiagnostics
from orion.full_voice_live_world import RecoveryLiveWorld
from orion.full_voice_srs import FullVoiceSrsEndpoint
from orion.full_voice_stt import FinalizedUserUtterance
from orion.planner import PlannerCancellationToken
from orion.protected_presentation import tx_correlation
from orion.protected_streaming_presentation import StreamingProtectedPresentation
from orion.protected_streaming_tts import ProtectedStreamingTts, protected_stream_requests
from orion.radio_contracts import RadioContext, RadioEntityRef, RadioModulation
from orion.srs_opus import OpusDecoder
from orion.srs_protocol import decode_voice_packet
from orion.srs_radio_transport import SrsRadioConfig, SrsState
from orion.srs_tx_state import SrsTxStateSnapshot
from orion.tool_gateway import build_tool_gateway
from orion.windows_credentials import VoiceCredential, default_voice_credential_store


class PacketSink:
    """No sockets, no PCM persistence; validate each locally encoded SRS packet."""
    def __init__(self):
        self.client_guid = "OOOOOOOOOOOOOOOOOOOOOO"
        self.state = SrsState.DISCONNECTED
        self.server_version = "LOCAL_SINK_NOT_SRS"
        self.coalition = 2
        self.radio_registered = self.udp_registered = False
        self.frames = self.pcm_bytes = 0
        self.first = self.last = None
        self.decoder = OpusDecoder()

    def connect(self):
        self.state = SrsState.READY
        self.radio_registered = self.udp_registered = True

    def send_voice(self, raw):
        packet = decode_voice_packet(raw)
        assert packet.original_client_guid == self.client_guid
        assert packet.packet_id == self.frames + 1 and len(packet.frequencies) == 1
        assert packet.frequencies[0].hz == 251000000
        decoded = self.decoder.decode(packet.audio)
        assert len(decoded) == 1280
        self.pcm_bytes += len(decoded)
        self.frames += 1
        self.last = time.monotonic()
        if self.first is None: self.first = self.last

    def close(self):
        self.decoder.close(); self.state = SrsState.STOPPED


class ObservedTts(ProtectedStreamingTts):
    def __init__(self, key, expected, report):
        super().__init__(key)
        self.expected, self.report = expected, report

    async def stream(self, text):
        assert text == self.expected
        assert protected_stream_requests(text)[1].synthesis_input.text == self.expected
        self.report["exact_request_text"] = True
        self.report["tts_calls"] += 1
        try:
            async for chunk in super().stream(text):
                self.report["tts_bytes"] += len(chunk)
                self.report["tts_chunks"] += 1
                yield chunk
        except Exception as exc:
            self.report["tts_failure_type"] = type(exc).__name__
            if str(exc).startswith("streaming_tts_"): self.report["tts_failure_category"] = str(exc)
            raise


async def run(output):
    report = {"gate": "deterministic_live_core_protected_stream_to_local_packet_sink",
              "pass": False, "physical_turn": False, "srs_tx": False, "qwen_calls": 0,
              "tts_calls": 0, "tts_bytes": 0, "tts_chunks": 0}
    live = RecoveryLiveWorld()
    endpoint = presentation = sink = None
    try:
        await live.start()
        core = FullVoiceCore(build_tool_gateway(world=live.world))
        now, stamp = datetime.now(UTC), time.monotonic()
        utterance = FinalizedUserUtterance(uuid4(), "Какой мой текущий курс и координаты?",
            stamp, stamp, stamp, stamp, stamp, stamp, now, now, "typed-gate-not-stt", 0, 0)
        result = await asyncio.to_thread(core.run, utterance, PlannerCancellationToken())
        report["core_status"] = result.status
        report["core_ms"] = (result.marks["interaction_completed"] - result.marks["interaction_started"]) * 1000
        if result.finalized is None: return report
        finalized = result.finalized
        report["protected_text"] = finalized.text
        report["text_sha256"] = hashlib.sha256(finalized.text.encode()).hexdigest()
        report["values"] = [v.model_dump(mode="json") for v in finalized.protected_fragments[0].semantic_unit.protected_values]
        report["provenance"] = [p.model_dump(mode="json") for p in finalized.provenance]
        sink = PacketSink()
        endpoint = FullVoiceSrsEndpoint(SrsRadioConfig(eam_password="local-sink-only"), threading.Event(),
            FieldDiagnostics(uuid4().hex, runtime_dir=output), lambda **_: None,
            radio_factory=lambda *_: sink)
        endpoint.connect_radio(); endpoint.start()
        at = time.monotonic()
        endpoint.capture.snapshot(SrsTxStateSnapshot(False, 1, 0, at-1, "synthetic-gate"))
        endpoint.capture.snapshot(SrsTxStateSnapshot(True, 1, 0, at-.9, "synthetic-gate"))
        endpoint.capture.snapshot(SrsTxStateSnapshot(False, 1, 0, at-.5, "synthetic-gate"))
        endpoint.capture.tick(at)
        tool = result.tool_results[0]
        remaining = 5 - tool.provenance.max_age_seconds - (datetime.now(UTC)-tool.receipt.completed_at).total_seconds()
        endpoint.response_valid_until = time.monotonic() + remaining
        tts = ObservedTts(default_voice_credential_store().load(VoiceCredential.YANDEX_API_KEY), finalized.text, report)
        presentation = StreamingProtectedPresentation(tts, endpoint.radio_router)
        context = RadioContext(tx_correlation_id=tx_correlation(utterance.interaction_id),
            interaction_id=utterance.interaction_id, source_domain=finalized.context.domain,
            communication_priority=finalized.priority,
            radio_entity=RadioEntityRef(entity_id="controlled.sink", operational_callsign=endpoint.config.bot_name),
            target_frequency_hz=251000000, modulation=RadioModulation.AM)
        outcome = await presentation.present(finalized, context)
        assert await presentation.present(finalized, context) == outcome
        report["presentation_state"] = outcome.state
        report["marks"] = {**result.marks, **presentation.marks, **endpoint.tx_marks}
        report.update(local_frames=sink.frames, decoded_local_pcm_bytes=sink.pcm_bytes,
                      local_stream_underruns=endpoint.tx_marks.get("underrun_frames", 0))
        report["pass"] = outcome.state == "completed" and sink.frames > 0 and report["tts_calls"] == 1
    except Exception as exc:
        report["failure_type"] = type(exc).__name__
    finally:
        if presentation is not None: report["shutdown_clean"] = await presentation.shutdown()
        if endpoint is not None: await asyncio.to_thread(endpoint.stop)
        elif sink is not None: sink.close()
        await live.close()
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    output = Path(tempfile.mkdtemp(prefix="orion-ownship-stream-gate-"))
    report = asyncio.run(run(output))
    print(json.dumps({k: v for k, v in report.items() if k not in {"protected_text", "values", "provenance", "marks"}}))
    print(json.dumps({"report": str(output / "report.json")}))
