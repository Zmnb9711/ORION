import json

import pytest

from orion.fa18c_diagnostics_recorder import DiagnosticPacket, HornetDiagnosticsRecorder, hornet_diagnostics_recorder
from orion.udp_bridge import TelemetryProtocol


def packet(*changes):
    return {
        "mode": "cockpit_argument_changes",
        "aircraft_id": "fa-18c",
        "range": {"min": 0, "max": 999},
        "changes": list(changes),
    }


def test_recorder_ranks_repeated_marker_candidate_first():
    recorder = HornetDiagnosticsRecorder()
    recorder.start("Hornet mapping")
    recorder.mark("toggle TACAN power")
    recorder.ingest(packet({"id": 410, "previous": 0.0, "value": 1.0}, {"id": 77, "previous": 0.1, "value": 0.2}))
    recorder.ingest(packet({"id": 410, "previous": 1.0, "value": 0.0}))

    report = recorder.report()

    assert report.event_count == 3
    assert report.packet_count == 2
    assert report.candidates[0].argument_id == 410
    assert report.markers["toggle TACAN power"] == [77, 410]
    assert report.candidates[0].transitions[-1] == (1.0, 0.0)


def test_recorder_ignores_non_hornet_or_invalid_packets():
    recorder = HornetDiagnosticsRecorder()
    recorder.start()

    assert recorder.ingest({"mode": "cockpit_argument_changes", "aircraft_id": "f-5e", "changes": []}) == 0
    assert recorder.ingest({"bad": "payload"}) == 0
    assert recorder.report().event_count == 0


def test_recorder_does_not_hide_unexpected_programming_errors(monkeypatch):
    recorder = HornetDiagnosticsRecorder()
    recorder.start()

    def explode(cls, payload):
        raise RuntimeError("unexpected diagnostics failure")

    monkeypatch.setattr(DiagnosticPacket, "model_validate", classmethod(explode))
    with pytest.raises(RuntimeError, match="unexpected diagnostics failure"):
        recorder.ingest(packet())


def test_udp_bridge_feeds_active_diagnostics_session():
    hornet_diagnostics_recorder.clear()
    hornet_diagnostics_recorder.start("udp")
    received = []
    protocol = TelemetryProtocol(received.append)
    payload = {
        "protocol_version": "0.2",
        "source": "dcs-export",
        "state": {
            "aircraft_type": "FA-18C_hornet",
            "position": {"latitude": 1.0, "longitude": 2.0, "altitude_m": 3.0},
            "heading_deg": 90.0,
            "true_airspeed_mps": 120.0,
            "vertical_speed_mps": 0.0,
            "diagnostics": packet({"id": 133, "previous": 0.0, "value": 0.1}),
        },
    }

    protocol.datagram_received(json.dumps(payload).encode("utf-8"), ("127.0.0.1", 9999))

    assert len(received) == 1
    report = hornet_diagnostics_recorder.report()
    assert report.event_count == 1
    assert report.candidates[0].argument_id == 133
    hornet_diagnostics_recorder.clear()
