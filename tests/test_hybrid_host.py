"""Actual normal service owner + FINAL + real Core/gateway + streaming fake radio."""
import asyncio
from datetime import datetime
from pathlib import Path
import queue
import subprocess
import threading
import time
from types import SimpleNamespace as NS

import pytest

import orion.full_voice_service as host
from orion.full_voice_core import FullVoiceCore
from orion.hybrid_aircraft_core import HybridAircraftCore
from orion.informational_presentation import InformationalPresentation
from orion.radio_router import RadioRouter
from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
from orion.yandex_srs_live_core import YandexSrsStartRequest
from test_hybrid_aircraft import MIXED, PURE, FREE, Provider, Gateway, utterance, NOW
from test_full_voice import StreamingFakeRadio


@pytest.mark.parametrize("text,expected,calls", [(MIXED, True, 0), (PURE, True, 0), (FREE, True, 0),
    ("какой мой текущий курс и координаты", True, 0), ("какой мой текущий вкус или оригинал", False, 0),
    ("Какой это самолёт?", False, 0)])
@pytest.mark.parametrize("mode", ["active", "inactive", "broken", "stop_local"])
def test_gate10_normal_host_coexistence_and_single_owner(monkeypatch, tmp_path, text, expected, calls, mode):
    if mode == "stop_local" and text not in {MIXED, FREE}:
        pytest.skip("Pure/frozen routes do not invoke local decomposition")
    u = utterance(text)
    stop = threading.Event()
    first, entered = threading.Event(), threading.Event()
    adapter = StreamingFakeRadio(first)
    router = RadioRouter(default_transport_id="srs")
    router.register_adapter(adapter); router.start()
    closed, tts_texts, hybrid_invoked = [], [], []
    factory_calls = []
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    if mode != "inactive": recorder.start(provider="yandex", transport="srs")
    if mode == "broken":
        def broken(*args, **kwargs): raise PermissionError("fixture evidence unavailable")
        monkeypatch.setattr(recorder, "record_aircraft_slice", broken)
    provider, gateway = Provider(), Gateway()
    active_token = []
    if mode == "stop_local":
        import orion.hybrid_aircraft_core as local
        recognize = local.recognize_local_decomposition
        def stopping(text):
            entered.set(); stop.set()
            deadline = time.monotonic() + 1
            while not active_token[0].cancelled and time.monotonic() < deadline:
                time.sleep(.001)
            assert active_token[0].cancelled
            return recognize(text)
        monkeypatch.setattr(local, "recognize_local_decomposition", stopping)

    class Native:
        owner, future = None, None
        def __init__(self, *args, **kwargs): pass
        async def open(self, key): pass
        def start(self, identity, at):
            self.owner = identity
            self.future = asyncio.get_running_loop().create_future()
        async def end(self, identity, at): self.future.set_result(u)
        async def result(self): return await self.future
        def release(self, identity): assert identity == u.interaction_id
        async def close(self): closed.append("native")

    class Endpoint:
        tx_frames = 0
        packet_id = 0
        tx_marks = {}
        def __init__(self, *args):
            self.radio_router = router
            self.turn_events = queue.Queue()
            for kind in (host.RadioTurnEventKind.START, host.RadioTurnEventKind.END):
                self.turn_events.put(NS(kind=kind, identity=u.interaction_id, timestamp=1.0))
        def connect_radio(self): pass
        def start(self): pass
        def arm_physical_capture(self): pass
        def srs_adapter_runtime(self): return NS(bot_name="ORION", coalition=2)
        def failure(self): return None
        def release_turn(self, identity): stop.set()
        def stop(self): router.shutdown(); closed.append("endpoint")

    class Hybrid(HybridAircraftCore):
        def __init__(self, gateway, _factory, **kwargs):
            def forbidden():
                factory_calls.append(True)
                raise AssertionError("Hybrid must not instantiate provider")
            super().__init__(gateway, forbidden, clock=lambda: NOW, **kwargs)
        def run(self, *args):
            hybrid_invoked.append(True)
            active_token.append(args[1])
            return super().run(*args)
    class Info(InformationalPresentation):
        def __init__(self, *args, **kwargs): super().__init__(*args, clock=lambda: NOW, **kwargs)
    async def tts(self, text):
        self._requests(text)  # Same request builder, fake audio, no gRPC channel.
        tts_texts.append(text)
        yield bytes(48000)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return NOW
    monkeypatch.setattr(host, "datetime", Clock)
    monkeypatch.setattr(host, "NativeSpeechKitTurns", Native)
    monkeypatch.setattr(host, "GrpcSpeechKitStreamingPort", lambda: None)
    monkeypatch.setattr(host, "SrsTransportDiagnostics", lambda *a, **k: None)
    monkeypatch.setattr(host, "FullVoiceCore", lambda g: FullVoiceCore(g, clock=lambda: NOW))
    monkeypatch.setattr(host, "build_tool_gateway", lambda **kwargs: gateway)
    monkeypatch.setattr(host, "HybridAircraftCore", Hybrid)
    monkeypatch.setattr(host, "InformationalPresentation", Info)
    monkeypatch.setattr(host, "realtime_test_evidence", recorder)
    monkeypatch.setattr(host.ProtectedStreamingTts, "stream", tts)
    service = host.FullVoiceService(endpoint_factory=Endpoint)
    request = YandexSrsStartRequest(api_key="fixture", folder_id="fixture", eam_password="fixture")
    try:
        asyncio.run(asyncio.wait_for(service._voice(request, "fixture-session", stop), 3))
        assert closed == ["native", "endpoint"]
        assert len(provider.calls) == calls
        assert not factory_calls
        owns = text.casefold().rstrip("?") == "какой мой текущий курс и координаты"
        assert bool(hybrid_invoked) != owns
        accepted = expected and mode != "stop_local"
        assert len(tts_texts) == len(adapter.transmit_calls) == int(accepted)
        assert len(gateway.calls) == int(accepted and text != FREE)
        assert service.status().state != "error"
        if mode == "active":
            events = list(recorder._events)
            assert any(e.get("transcript") == text for e in events)
            if accepted and not owns:
                finalized = next(e["finalized_text"] for e in events if e["event"] == "aircraft_slice.local_composition")
                assert finalized == tts_texts[0]
                assert any(e.get("tts_input") == finalized for e in events)
                assert any(e["event"] == "aircraft_slice.response_terminal" for e in events)
                terminal = next(e for e in events if e["event"] == "aircraft_slice.response_terminal")
                assert terminal["status"] == "completed" and "frames" in terminal
                assert {"radio_first_frame", "radio_completed", "tts_started", "tts_first_pcm"} <= terminal.keys()
                if text not in {PURE}:
                    accepted_event = next(e for e in events if e["event"] == "aircraft_slice.decomposition_validation" and e["status"] == "accepted")
                    assert accepted_event["decomposition_source"] == "LOCAL" and accepted_event["provider_call_count"] == 0
                if text != FREE:
                    fact = next(e["aircraft"] for e in events if e["event"] == "aircraft_slice.authoritative_read")
                    assert fact["aircraft_type"] == "FA-18C_hornet" and fact["source"] == "dcs_export"
            if owns: assert next(e for e in events if e.get("route") == "FROZEN_OWNSHIP")["provider_call_count"] == 0
        if mode == "inactive": assert not recorder._events
        if mode == "stop_local": assert entered.is_set() and not tts_texts
    finally:
        stop.set(); router.shutdown()


def test_gate11_no_unapproved_production_delta():
    root = Path(__file__).resolve().parents[1]
    from level0_scope_guard import assert_historical_and_current_scope
    assert_historical_and_current_scope(root, "474d11bc", {"orion/full_voice_service.py", "orion/yandex_qwen_planner.py",
        "orion/protected_presentation.py", "orion/protected_streaming_tts.py", "orion/realtime_test_evidence.py",
        "orion/hybrid_aircraft_contracts.py", "orion/hybrid_aircraft_core.py", "orion/informational_presentation.py"})
    import ast
    path = "orion/yandex_qwen_planner.py"
    current = (root/path).read_text(encoding="utf-8")
    added = next(n for n in ast.walk(ast.parse(current)) if isinstance(n, ast.FunctionDef) and n.name == "decompose_aircraft")
    lines = current.splitlines(keepends=True)
    restored = "".join(lines[:added.lineno-2] + lines[added.end_lineno:])
    original = subprocess.check_output(["git", "show", f"474d11bc:{path}"], cwd=root).decode()
    assert restored == original  # Existing transport, retry, cleanup entirely literal.
