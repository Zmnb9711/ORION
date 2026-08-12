from datetime import datetime, timedelta, timezone

from orion.models import AircraftState, Position, TelemetryEnvelope
from orion.telemetry_history import TelemetryHistoryRecorder


def _telemetry(aircraft_type: str = "FA-18C_hornet") -> TelemetryEnvelope:
    return TelemetryEnvelope(
        protocol_version="0.2",
        source="dcs-export",
        state=AircraftState(
            aircraft_type=aircraft_type,
            position=Position(latitude=36.0, longitude=30.0, altitude_m=1000.0),
            heading_deg=90.0,
            true_airspeed_mps=150.0,
        ),
    )


def test_history_retains_last_known_state_after_packets_stop() -> None:
    recorder = TelemetryHistoryRecorder(capacity=3)
    start = datetime(2026, 8, 13, 0, 0, tzinfo=timezone.utc)
    recorder.observe(_telemetry(), received_at=start)
    recorder.observe(_telemetry(), received_at=start + timedelta(seconds=1))

    report = recorder.report()

    assert report.total_packet_count == 2
    assert report.retained_packet_count == 2
    assert report.last_seen_aircraft_type == "FA-18C_hornet"
    assert report.last_source == "dcs-export"
    assert report.last_protocol_version == "0.2"
    assert report.average_packet_rate_hz == 1.0


def test_history_is_bounded_to_latest_packets() -> None:
    recorder = TelemetryHistoryRecorder(capacity=2)
    start = datetime(2026, 8, 13, 0, 0, tzinfo=timezone.utc)
    for offset in range(3):
        recorder.observe(_telemetry(), received_at=start + timedelta(seconds=offset))

    report = recorder.report()

    assert report.total_packet_count == 3
    assert report.retained_packet_count == 2
    assert [sample.received_at for sample in report.samples] == [
        start + timedelta(seconds=1),
        start + timedelta(seconds=2),
    ]
