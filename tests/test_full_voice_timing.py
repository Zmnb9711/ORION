"""Measurement-only proof against the exact frozen tree; zero external I/O."""
import asyncio
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace as NS
import zipfile

import pytest

from orion import full_voice_timing as timing
from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
from orion import protected_streaming_tts as current
from timing_oracle import OBSERVATIONS, without_timing

ROOT = Path(__file__).resolve().parents[1]
FROZEN = "05c832762a73ed38f98984942227dbdee1e89ef3"


def frozen(path):
    return subprocess.check_output(["git", "show", f"{FROZEN}:{path}"], cwd=ROOT).decode("utf-8")


def test_host_is_exact_frozen_and_all_other_changes_are_only_observations():
    actual = (ROOT / "orion/full_voice_service.py").read_text(encoding="utf-8")
    assert actual == frozen("orion/full_voice_service.py")
    for name in OBSERVATIONS:
        path = "orion/" + name
        assert without_timing(name, (ROOT/path).read_text(encoding="utf-8")) == frozen(path)


def test_high_resolution_marks_bounded_private_memory_only_and_export(monkeypatch, tmp_path):
    recorder = RealtimeTestEvidenceRecorder(tmp_path, max_events=11)
    monkeypatch.setattr(timing, "realtime_test_evidence", recorder)
    # QPC-style deterministic fractions, never mixed with coarse runtime clock.
    stamps = {f"T{i}": 100 + i*.0001234 for i in range(11)}
    def observe():
        for boundary, stamp in stamps.items():
            monkeypatch.setattr(timing, "time", NS(perf_counter=lambda:stamp))
            timing.observe(boundary, "turn", response_id="p7c-turn")
    observe()
    assert not recorder._events
    recorder.start(provider="yandex", transport="srs")
    observe()
    assert not list(tmp_path.iterdir())
    rows = list(recorder._events)
    assert {r["event_id"]:r["perf_counter_seconds"] for r in rows} == stamps
    assert all(r["turn_id"] == "turn" and r["response_id"] == "p7c-turn" for r in rows)
    assert "transcript" not in json.dumps(rows) and "pcm" not in json.dumps(rows)
    observe()
    assert len(recorder._events) == 11 and recorder.status().dropped_event_count == 11
    with zipfile.ZipFile(recorder.stop_and_export()) as package:
        exported = [json.loads(r) for r in package.read("events.jsonl").splitlines()]
    assert [r["perf_counter_seconds"] for r in exported] == [r["perf_counter_seconds"] for r in rows]


def test_clock_and_recorder_failure_are_not_control_flow(monkeypatch):
    recorder = NS(record=lambda *a, **kw: (_ for _ in ()).throw(PermissionError("offline")))
    monkeypatch.setattr(timing, "realtime_test_evidence", recorder)
    timing.observe("T0", "turn")
    monkeypatch.setattr(timing, "time", NS(perf_counter=lambda:1/0))
    timing.observe("T0", "turn")


@pytest.mark.parametrize("mode", ["success", "empty", "odd", "bound", "exception", "cancellation", "rpc_failure", "closed"])
@pytest.mark.parametrize("recording", ["active", "inactive", "broken"])
def test_actual_tts_requests_pcm_calls_and_exceptions_identical(monkeypatch, mode, recording):
    import grpc
    baseline = {"__name__":"frozen_tts"}
    exec(compile(frozen("orion/protected_streaming_tts.py"), "frozen_tts", "exec"), baseline)
    exact = " \nFly heading zero three seven.  "
    boom = asyncio.CancelledError() if mode == "cancellation" else ValueError("fixture")
    traces = []
    for namespace in (baseline, vars(current)):
        trace = []
        recorder = RealtimeTestEvidenceRecorder()
        if recording != "inactive": recorder.start(provider="yandex", transport="srs")
        if recording == "broken":
            monkeypatch.setattr(recorder, "record", lambda *a, **kw: (_ for _ in ()).throw(OSError("offline")))
        monkeypatch.setattr(timing, "realtime_test_evidence", recorder)
        class Call:
            def __aiter__(self): return self.iterate()
            async def iterate(self):
                if mode in ("exception", "cancellation"): raise boom
                if mode == "empty": return
                yield NS(audio_chunk=NS(data=b""))
                yield NS(audio_chunk=NS(data=b"x" if mode == "odd" else
                                        bytes(2_880_002) if mode == "bound" else b"\x01\x00" * 960))
                yield NS(audio_chunk=NS(data=b"\x02\x00" * 1280))
            def cancel(self): trace.append("call_cancel")
        class Channel:
            def stream_stream(self, path, **kw):
                trace.append(("method", path))
                def invoke(requests, **options):
                    trace.append(("rpc", [r.SerializeToString() for r in requests], options))
                    if mode == "rpc_failure": raise boom
                    return Call()
                return invoke
            async def close(self): trace.append("channel_close")
        def channel(*a, **kw):
            trace.append(("channel", a, kw))
            return Channel()
        with monkeypatch.context() as patch:
            patch.setattr(grpc.aio, "secure_channel", channel)
            patch.setattr(grpc, "ssl_channel_credentials", lambda:"fixture_credentials")
            patch.setitem(namespace, "uuid4", lambda:"fixed-request-id")
            async def run():
                tts = namespace["ProtectedStreamingTts"]("fixture_key")
                if namespace is not baseline: tts.observation_turn_id = "fixture-turn"
                if mode == "closed": await tts.aclose()
                try:
                    async for chunk in tts.stream(exact): trace.append(("pcm", chunk))
                except BaseException as exc:
                    if mode in ("exception", "cancellation", "rpc_failure"): assert exc is boom
                    trace.append(("raised", type(exc).__name__, str(exc)))
                assert tts._call is None
                await tts.aclose()
            asyncio.run(run())
        rows = list(recorder._events)
        if namespace is not baseline and recording == "active" and mode != "closed":
            assert len(rows) == 1 and rows[0]["event_id"] == "T6"
            assert rows[0]["turn_id"] == "fixture-turn"
            assert "fixture_key" not in json.dumps(rows) and exact not in json.dumps(rows)
        else:
            assert rows == []
        traces.append(trace)
    assert traces[0] == traces[1]


def test_srs_frame_sequence_and_count_identical_to_frozen(monkeypatch, tmp_path):
    import test_full_voice_srs as fixture
    import time
    from orion.bounded_radio_stream import BoundedPcmStream
    from orion.srs_protocol import decode_voice_packet
    baseline = {"__name__":"frozen_srs"}
    exec(compile(frozen("orion/full_voice_srs.py"), "frozen_srs", "exec"), baseline)
    outputs = []
    for cls in (baseline["FullVoiceSrsEndpoint"], fixture.FullVoiceSrsEndpoint):
        with monkeypatch.context() as patch:
            recorder = RealtimeTestEvidenceRecorder(tmp_path / "no-hot-path-files")
            recorder.start(provider="yandex", transport="srs")
            patch.setattr(timing, "realtime_test_evidence", recorder)
            patch.setattr(fixture, "FullVoiceSrsEndpoint", cls)
            endpoint = fixture.build(tmp_path)
            try:
                now = time.monotonic()
                for offset, sending in ((-1,False),(-.9,True),(-.5,False)):
                    endpoint.capture.snapshot(fixture.snap(now+offset, sending))
                endpoint.capture.tick(now)
                stream = BoundedPcmStream()
                stream.feed(bytes(3528*5)); stream.finish()
                result = endpoint.transmit_srs_stream("p7c-" + "a"*32, stream, 2)
                packets = [decode_voice_packet(raw) for raw in endpoint.radio.sent]
                assert [p.packet_id for p in packets] == list(range(1,len(packets)+1))
                outputs.append((result.frame_count, list(endpoint.radio.sent)))
                events = [r for r in recorder._events if r.get("response_id")]
                if cls is not baseline["FullVoiceSrsEndpoint"]:
                    assert [r["event_id"] for r in events] == ["T8", "T9", "T10"]
                    assert all(r["response_id"] == "p7c-" + "a"*32 for r in events)
                assert not (tmp_path / "no-hot-path-files").exists()
            finally:
                endpoint.stop()
    assert outputs[0] == outputs[1]
