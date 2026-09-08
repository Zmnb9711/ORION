"""Observation-only differential against exact pre-observation host. No live I/O."""
import asyncio
import json
from pathlib import Path
import queue
import subprocess
import threading
from types import SimpleNamespace as NS
from uuid import uuid4
import zipfile

import pytest

from orion import full_voice_service as current
from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("outcome", ["FinalizedUserUtterance", "None", "exception", "cancellation", "stop_pending"])
@pytest.mark.parametrize("recording", ["active", "inactive", "broken"])
def test_actual_host_control_and_data_trace_identical_to_fallback(monkeypatch, tmp_path, outcome, recording):
    baseline = {"__name__": "pre_observation_host"}
    exec(compile(subprocess.check_output(
        ["git", "show", "3f364bdf:orion/full_voice_service.py"], cwd=ROOT
    ).decode("utf-8"), "3f364bdf/full_voice_service.py", "exec"), baseline)
    identity = uuid4()
    exact = "  Какой мой текущий курс и координаты?\n"
    utterance = NS(text=exact, interaction_id=identity)
    error = RuntimeError("private provider body must not be recorded")
    cancel = asyncio.CancelledError("private cancellation detail")
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    if recording != "inactive":
        recorder.start(provider="yandex", transport="srs")
    if recording == "broken":
        def broken(**kwargs):
            raise PermissionError("offline recorder failure")
        monkeypatch.setattr(recorder, "record_stt_core_boundary", broken)
    monkeypatch.setattr(current, "realtime_test_evidence", recorder)
    traces = []
    for namespace in (baseline, vars(current)):
        trace = []
        stopped = threading.Event()

        class Endpoint:
            tx_frames = 0
            def __init__(self, *args):
                self.turn_events = queue.Queue()
                for kind in current.RadioTurnEventKind:
                    self.turn_events.put(NS(kind=kind, identity=identity, timestamp=1.0, pcm=b"\x01\x00" * 320))
                self.radio_router = object()
            def connect_radio(self): trace.append("connect")
            def start(self): trace.append("endpoint_start")
            def arm_physical_capture(self): trace.append("arm")
            def srs_adapter_runtime(self): return NS(bot_name="fixture", coalition=2)
            def failure(self): return None
            def release_turn(self, turn):
                trace.append(("endpoint_release", turn))
                stopped.set()
            def stop(self): trace.append("endpoint_stop")

        class Native:
            owner = None
            future = None
            def __init__(self, port, fail): self.fail = fail
            async def open(self, key): trace.append("stt_open")
            def start(self, turn, at):
                trace.append(("stt_start", turn, at))
                self.owner = turn
                self.future = asyncio.get_running_loop().create_future()
            async def audio(self, turn, pcm, at): trace.append(("stt_audio", turn, pcm, at))
            async def end(self, turn, at):
                trace.append(("stt_end", turn, at))
                if outcome == "stop_pending":
                    stopped.set()
                    return
                if outcome == "exception":
                    self.future.cancel()
                    self.fail("stt_eou_transport_failed")
                    raise error
                self.future.set_result(None)
            async def result(self):
                trace.append("stt_result")
                if outcome == "cancellation": raise cancel
                return utterance if outcome == "FinalizedUserUtterance" else None
            def release(self, turn): trace.append(("stt_release", turn))
            async def close(self): trace.append("stt_close")

        class Core:
            def __init__(self, gateway): pass
            def run(self, value, cancellation):
                assert value is utterance
                trace.append(("core", value.text, cancellation.cancelled))
                return NS(finalized=None, status="unsupported")

        class Presentation:
            def __init__(self, *args): pass
            async def shutdown(self): trace.append("presentation_shutdown")

        class Service(namespace["FullVoiceService"]):
            def _set(self, **changes): trace.append(("status", changes))

        with monkeypatch.context() as patch:
            for name, value in {"NativeSpeechKitTurns": Native, "FullVoiceCore": Core,
                                "GrpcSpeechKitStreamingPort": lambda: None,
                                "ProtectedStreamingTts": lambda key: None,
                                "StreamingProtectedPresentation": Presentation,
                                "SrsTransportDiagnostics": lambda *a, **kw: None,
                                "build_tool_gateway": lambda **kw: None}.items():
                patch.setitem(namespace, name, value)
            request = NS(api_key="fixture", eam_password=NS(get_secret_value=lambda: "fixture"),
                         host="127.0.0.1", port=5002, bot_name="fixture", frequency_hz=251000000, modulation=0)
            async def run():
                try:
                    await Service(endpoint_factory=Endpoint)._voice(request, "session", stopped)
                except BaseException as exc:
                    assert exc is (error if outcome == "exception" else cancel)
                    trace.append(("raised", type(exc).__name__))
            asyncio.run(run())
        traces.append(trace)
    assert traces[0] == traces[1]
    events = [e for e in recorder._events if e["event"] == "stt_core_boundary"]
    if recording == "active":
        assert len(events) == 1
        assert events[0]["status"] == ("cancellation" if outcome == "stop_pending" else outcome)
        assert events[0]["turn_id"] == str(identity)
        if outcome == "FinalizedUserUtterance": assert events[0]["transcript"] == exact
        else: assert "transcript" not in events[0]
        assert "private" not in json.dumps(events)
    else:
        assert events == []


def test_exact_text_explicit_test_export_and_normal_privacy(tmp_path):
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    # Includes boundary whitespace and a token-like word: no sanitizer rewrite.
    text = " \nBearer — это буквальный текст пользователя. " + "я" * 3900 + "\n "
    fields = dict(turn_id="turn", realtime_session_id="session", status="FinalizedUserUtterance", transcript=text)
    recorder.record_stt_core_boundary(**fields)
    assert not recorder._events and not list(tmp_path.iterdir())
    recorder.start(provider="yandex", transport="srs")
    recorder.record_stt_core_boundary(**fields)
    assert not list(tmp_path.iterdir())  # Hot path has no filesystem persistence.
    archive = recorder.stop_and_export()
    with zipfile.ZipFile(archive) as package:
        rows = [json.loads(line) for line in package.read("events.jsonl").decode("utf-8").splitlines()]
        assert rows[0]["transcript"] == text
        assert b"user_transcripts_included=true" in package.read("manifest.txt")
    before = list(recorder._events)
    recorder.record_stt_core_boundary(**fields)
    assert list(recorder._events) == before


def test_one_terminal_record_no_overwrite_by_later_core_failure(monkeypatch):
    recorder = RealtimeTestEvidenceRecorder()
    recorder.start(provider="yandex", transport="srs")
    monkeypatch.setattr(current, "realtime_test_evidence", recorder)
    observation = current._SttCoreObservation("session")
    observation.record("exception")  # No physical turn yet.
    observation.begin(uuid4())
    observation.record("None")
    observation.record("exception", error_type="later_core_failure")
    observation.record("cancellation")
    assert [event["status"] for event in recorder._events] == ["None"]
