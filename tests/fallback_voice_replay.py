"""Offline golden field versus fallback inherited-owner replay.

Only external I/O is replaced. PCM is either a fixed fixture or an existing WAV;
provider FINAL is explicitly a fixture, NEVER a claimed transcription of that WAV.
"""
import argparse
import asyncio
from contextlib import redirect_stdout
from datetime import UTC, datetime
import hashlib
import io
import json
from pathlib import Path
import queue
import socket
import sys
import threading
import time
from types import SimpleNamespace as NS
import wave


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", required=True)
    parser.add_argument("--host", choices=("field", "runtime"), required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--wav")
    parser.add_argument("--human-coalition", type=int, choices=(0, 2), default=2)
    parser.add_argument("--peer-metadata", choices=("full", "missing", "lost-after-arm"), default="full")
    args = parser.parse_args()
    tree = Path(args.tree)
    sys.path[:0] = [str(tree), str(tree / "tests")]
    import pytest
    from orion.full_voice_capture import PhysicalRadioTurn
    from orion.full_voice_core import FullVoiceCore
    from orion.full_voice_stt import NativeSpeechKitTurns
    from orion.protected_streaming_tts import ProtectedStreamingTts, protected_stream_requests
    from orion.radio_router import RadioRouter
    from orion.srs_radio_transport import SrsState
    from orion.srs_tx_state import SrsTxStateSnapshot, SrsTxStateListenerStatus
    from orion.speechkit_v3_stt_transport import speechkit_session_options
    from orion.live_telemetry_store import LiveTelemetryStore
    from orion.models import AircraftState, Position, TelemetryEnvelope
    from orion.world_model import WorldModelFacade
    from test_interaction_router import MissionOwner, BridgeOwner
    from test_full_voice import Port, terminal, StreamingFakeRadio

    def no_network(*a, **kw):
        raise AssertionError("offline_oracle_network_forbidden")

    pcm = b"\x01\x00" * 1600
    if args.wav:
        with wave.open(args.wav, "rb") as wav:
            assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
            pcm = wav.readframes(wav.getnframes())
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    queries = ["Какой мой текущий курс и координаты?", "Расскажи анекдот.",
               "какой мой текущий курс и координаты", "расскажи анекдот",
               "  КАКОЙ МОЙ ТЕКУЩИЙ КУРС И КООРДИНАТЫ?  ",
               "Мой текущий курс и координаты?", "Какой мой текущий курс и координаты и скорость?"]
    for index, query in enumerate(queries):
        trace, inputs, results, finals, texts, endpoints, ports = [], [], [], [], [], [], []
        first = threading.Event()
        adapter = StreamingFakeRadio(first)
        telemetry = LiveTelemetryStore()
        telemetry.set(TelemetryEnvelope(sequence=1, state=AircraftState(
            aircraft_type="FA-18C_hornet", callsign="Colt 1-1", heading_deg=137,
            position=Position(latitude=42.1, longitude=41.2, altitude_m=9876), true_airspeed_mps=543,
        )), received_at=datetime.now(UTC))
        world = WorldModelFacade(telemetry=telemetry, mission=MissionOwner(), mission_bridge=BridgeOwner())

        class Endpoint:
            def __init__(self, config, stopped, diagnostics, status):
                endpoints.append(self)
                self.config, self.stop_event = config, stopped
                self.expected_origin = None
                self.radio = NS(state=SrsState.READY, client_guid="bot", coalition=2,
                    server_settings={"COALITION_AUDIO_SECURITY": "False", "SPECTATORS_AUDIO_DISABLED": "False"},
                    clients={"human": {"Coalition": args.human_coalition, "RadioInfo": {"radios": [{},
                        {"freq": 251000000, "modulation": 0, "enc": False}]}}})
                self.listener = NS(status=SrsTxStateListenerStatus.READY, latest=NS(is_sending=False))
                if args.peer_metadata == "missing":
                    self.radio.clients["human"] = {}
                self.turn_events = queue.Queue()
                self.capture = PhysicalRadioTurn(self.turn_events.put_nowait,
                    lambda code: (_ for _ in ()).throw(AssertionError(code)))
                self.tx_frames = self.tx_transmissions = 0
                self.tx_marks = {}
                self.released = False

            def connect_radio(self): trace.append("radio_connect")
            def start(self):
                trace.append("radio_start")
                self.radio_router = RadioRouter(default_transport_id="srs", queue_capacity=1)
                self.radio_router.register_adapter(adapter)
                self.radio_router.start()
            def arm_physical_capture(self):
                trace.append("physical_arm")
                self.expected_origin = "human"
                if args.peer_metadata == "lost-after-arm":
                    self.radio.clients["human"] = {"Coalition": args.human_coalition}
                now = time.monotonic() - len(pcm) / 32000 - .3
                self.capture.snapshot(SrsTxStateSnapshot(False, 1, 0, now, "fixture"))
                self.capture.snapshot(SrsTxStateSnapshot(True, 1, 0, now + .01, "fixture"))
                for offset in range(0, len(pcm), 1280):
                    self.capture.pcm(pcm[offset:offset+1280], now + .02 + offset / 32000)
                end = now + .02 + len(pcm)/32000
                self.capture.snapshot(SrsTxStateSnapshot(False, 1, 0, end, "fixture"))
                self.capture.tick(end + .2)
            def srs_adapter_runtime(self): return NS(bot_name=self.config.bot_name, coalition=2)
            def failure(self): return None
            def release_turn(self, identity):
                self.capture.release(identity)
                self.released = True
            def stop(self):
                trace.append("radio_stop")
                self.radio_router.shutdown()

        class Native(NativeSpeechKitTurns):
            async def result(self):
                result = await super().result()
                if result:
                    inputs.append({"text": result.text, "language": result.input_language,
                        "pcm_bytes": result.pcm_bytes, "final_index": result.final_index,
                        "provider_session": result.provider_session,
                        "physical_duration": round(result.physical_end - result.physical_start, 6),
                        "last_pcm_offset": round(result.last_pcm - result.physical_start, 6),
                        "same_physical_owner": result.interaction_id == self.owner,
                        "ordered_marks": result.physical_end <= result.eou_sent <= result.final_received <= result.barrier_closed})
                    assert inputs[-1]["ordered_marks"] and inputs[-1]["same_physical_owner"]
                return result

        class FinalPort(Port):
            def __init__(self):
                super().__init__()
                ports.append(self)
            async def open(self, key): trace.append("stt_open")
            async def send_eou(self):
                await super().send_eou()
                self.queue.put_nowait(terminal("partial", text="not dispatchable"))
                self.queue.put_nowait(terminal(text=query))
                self.queue.put_nowait(terminal("eou_update"))
            async def close(self):
                trace.append("stt_close")
                await super().close()

        class Core(FullVoiceCore):
            def run(self, utterance, cancel):
                result = super().run(utterance, cancel)
                results.append(result.status)
                fragment = result.finalized.protected_fragments[0] if result.finalized else None
                finals.append({"text": result.finalized.text if result.finalized else None,
                    "values": [v.model_dump(mode="json") for v in fragment.semantic_unit.protected_values] if fragment else [],
                    "tool_count": len(result.tool_results),
                    "route": self.router.diagnostic_snapshot()[-1].route.value})
                return result

        async def tts(self, text):
            texts.append(text)
            yield b"\x01\x00" * 24000

        with pytest.MonkeyPatch.context() as patch, redirect_stdout(io.StringIO()):
            import grpc
            patch.setattr(socket, "create_connection", no_network)
            patch.setattr(grpc.aio, "secure_channel", no_network)
            patch.setattr(socket.socket, "sendto", no_network)
            patch.setattr(ProtectedStreamingTts, "stream", tts)
            if args.host == "field":
                import orion.full_voice_field as host
                class Live:
                    def __init__(self): self.world = world
                    async def start(self): trace.append("world_start")
                    async def close(self): trace.append("world_close")
                patch.setattr(host, "RecoveryLiveWorld", Live)
                patch.setattr(host, "default_voice_credential_store", lambda: NS(load=lambda _: "fixture"))
                patch.setattr(host, "FullVoiceSrsEndpoint", Endpoint)
                patch.setattr(host, "NativeSpeechKitTurns", Native)
                patch.setattr(host, "GrpcSpeechKitStreamingPort", FinalPort)
                patch.setattr(host, "FullVoiceCore", Core)
                run_dir = output / str(index)
                run_dir.mkdir()
                report = asyncio.run(host.run_field(NS(callsign="ORION RECOVERY", duration=3, turns=1,
                                                       profile_latency=False), run_dir))
                terminal_state = report["turns"][0]["state"]
                assert not report["failures"]
            else:
                import orion.full_voice_service as host
                from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
                observation = RealtimeTestEvidenceRecorder(output)
                observation.start(provider="yandex", transport="srs")
                patch.setattr(host, "realtime_test_evidence", observation)
                from orion.yandex_srs_live_core import YandexSrsStartRequest
                patch.setattr(host, "NativeSpeechKitTurns", Native)
                patch.setattr(host, "GrpcSpeechKitStreamingPort", FinalPort)
                patch.setattr(host, "FullVoiceCore", Core)
                patch.setattr(host, "world_model", world)
                service = host.FullVoiceService(endpoint_factory=Endpoint)
                service.start(YandexSrsStartRequest(api_key="fixture", folder_id="fixture",
                    bot_name="ORION RECOVERY", host="127.0.0.1", port=5002, eam_password="fixture"))
                deadline = time.monotonic()+3
                try:
                    while time.monotonic() < deadline and not (endpoints and endpoints[0].released):
                        time.sleep(.01)
                    assert endpoints and endpoints[0].released, service.status()
                    assert service.status().state == "streaming"
                    terminal_state = results[-1]
                finally:
                    service.stop()
                assert service.status().state == "stopped"
                assert service._thread is not None and not service._thread.is_alive()
                observed = [e for e in observation._events if e["event"] == "stt_core_boundary"]
                assert len(observed) == 1 and observed[0]["status"] == "FinalizedUserUtterance"
                assert observed[0]["transcript"] == query
        transmitted = adapter.transmit_calls
        row = {"query":query, "finalized_utterances":inputs, "core_status":results,
               "finalized":finals, "tts_texts":texts, "terminal":terminal_state,
               "tx_count":len(transmitted), "eou_count":ports[0].eous,
               "stt_pcm_sha256":hashlib.sha256(b"".join(ports[0].audio)).hexdigest(),
               "stt_chunk_sizes":[len(chunk) for chunk in ports[0].audio],
               "trace":trace, "bot_name":endpoints[0].config.bot_name,
               "entity":transmitted[0].context.radio_entity.entity_id if transmitted else None,
               "frequency":transmitted[0].context.target_frequency_hz if transmitted else None}
        assert row["stt_pcm_sha256"] == hashlib.sha256(pcm).hexdigest()
        assert all(x not in " ".join(texts) for x in ("9876", "543", "altitude", "airspeed", "telemetry"))
        rows.append(row)
    result = {"host":args.host, "tree":str(tree), "pcm_sha256":hashlib.sha256(pcm).hexdigest(),
              "provider_final_source":"explicit_fixture_not_audio_transcription",
              "stt_options":speechkit_session_options().SerializeToString().hex(),
              "tts_requests":[r.SerializeToString().hex() for r in protected_stream_requests("  Exact protected text.\n")],
              "rows":rows, "provider_calls":0, "physical_ptt":0}
    (output/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"result":str(output/"result.json"),"rows":len(rows)}))


if __name__ == "__main__":
    main()
