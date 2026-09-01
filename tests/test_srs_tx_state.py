from __future__ import annotations

import json
import threading
import time

import pytest

from orion.srs_tx_state import (
    SrsTxStateListener,
    SrsTxStateListenerStatus,
    SrsTxStatePortUnavailable,
    SrsTxStateUnavailable,
    parse_combined_radio_state,
)


class Clock:
    def __init__(self) -> None:
        self.now = 10.0

    def __call__(self) -> float:
        return self.now


def datagram(
    is_sending: bool,
    *,
    sending_on: int = 1,
    is_encrypted: int = 0,
) -> bytes:
    return json.dumps(
        {
            "RadioSendingState": {
                "IsSending": is_sending,
                "SendingOn": sending_on,
                "IsEncrypted": is_encrypted,
            },
            "RadioInfo": {"selected": 1, "unit": "EAM"},
        }
    ).encode()


def test_official_combined_radio_state_fields_are_parsed_exactly() -> None:
    snapshot = parse_combined_radio_state(
        datagram(True),
        received_at=12.5,
        received_timestamp="2026-08-31T15:08:54.254+00:00",
    )
    assert snapshot.is_sending is True
    assert snapshot.sending_on == 1
    assert snapshot.is_encrypted == 0
    assert snapshot.received_at == 12.5


def test_malformed_snapshot_is_diagnosed_and_does_not_corrupt_later_state() -> None:
    clock = Clock()
    snapshots = []
    events: list[tuple[str, dict[str, object]]] = []
    listener = SrsTxStateListener(
        threading.Event(),
        lambda item, previous: snapshots.append((item, previous)),
        lambda _status, _age: None,
        lambda event, fields: events.append((event, fields)),
        clock=clock,
    )

    assert listener.process_datagram(datagram(False)) is True
    assert listener.process_datagram(b'{"RadioSendingState": {}}') is False
    clock.now += 0.2
    assert listener.process_datagram(datagram(True)) is True

    assert [item[0].is_sending for item in snapshots] == [False, True]
    assert snapshots[-1][1] is not None
    assert snapshots[-1][1].is_sending is False
    assert [event for event, _fields in events].count("srs_tx_state_malformed") == 1
    assert listener.status is SrsTxStateListenerStatus.READY


def test_snapshot_stream_stale_and_recovery_are_deterministic() -> None:
    clock = Clock()
    statuses: list[tuple[SrsTxStateListenerStatus, float | None]] = []
    events: list[str] = []
    listener = SrsTxStateListener(
        threading.Event(),
        lambda _item, _previous: None,
        lambda status, age: statuses.append((status, age)),
        lambda event, _fields: events.append(event),
        clock=clock,
    )
    listener.process_datagram(datagram(False))
    clock.now += 1.1

    assert listener.check_liveness() is True
    assert listener.status is SrsTxStateListenerStatus.READY
    clock.now += 3.901
    assert listener.check_liveness() is False
    assert listener.status is SrsTxStateListenerStatus.STALE
    clock.now += 0.1
    listener.process_datagram(datagram(False))

    assert listener.status is SrsTxStateListenerStatus.READY
    assert "srs_tx_state_stale" in events
    assert "srs_tx_state_recovered" in events
    assert statuses[-1] == (SrsTxStateListenerStatus.READY, 0.0)


def test_valid_same_state_snapshots_drive_one_bounded_cadence_contract() -> None:
    clock = Clock()
    events: list[tuple[str, dict[str, object]]] = []
    listener = SrsTxStateListener(
        threading.Event(),
        lambda _item, _previous: None,
        lambda _status, _age: None,
        lambda event, fields: events.append((event, fields)),
        clock=clock,
    )

    listener.process_datagram(datagram(False))
    assert listener.liveness.cadence_sample_count == 0
    assert listener.liveness.budget_seconds == 5.0
    clock.now += 0.2
    listener.process_datagram(datagram(False))

    assert listener.liveness.cadence_sample_count == 1
    assert listener.liveness.observed_cadence_seconds == pytest.approx(0.2)
    assert listener.liveness.budget_seconds == 1.0
    snapshot = next(
        fields for event, fields in events if event == "srs_tx_state_snapshot"
    )
    assert snapshot["listener_epoch"] == 1
    assert snapshot["liveness_budget_ms"] in {1_000.0, 5_000.0}


def test_slow_cadence_budget_tolerates_one_missed_heartbeat_then_fails_bounded() -> (
    None
):
    clock = Clock()
    listener = SrsTxStateListener(
        threading.Event(),
        lambda _item, _previous: None,
        lambda _status, _age: None,
        lambda _event, _fields: None,
        clock=clock,
    )

    listener.process_datagram(datagram(False))
    clock.now += 1.6
    listener.process_datagram(datagram(False))
    assert listener.liveness.budget_seconds == pytest.approx(4.8)

    clock.now += 3.2
    assert listener.check_liveness() is True
    clock.now += 1.601
    assert listener.check_liveness() is False
    assert listener.liveness.budget_seconds == 5.0
    assert listener.latest is None


@pytest.mark.parametrize("cadence", [0.2, 1.6])
def test_long_ptt_over_six_seconds_stays_fresh_with_valid_heartbeats(
    cadence: float,
) -> None:
    clock = Clock()
    transitions: list[tuple[bool | None, bool]] = []
    listener = SrsTxStateListener(
        threading.Event(),
        lambda item, previous: transitions.append(
            (previous.is_sending if previous is not None else None, item.is_sending)
        ),
        lambda _status, _age: None,
        lambda _event, _fields: None,
        clock=clock,
    )

    listener.process_datagram(datagram(False))
    clock.now += cadence
    listener.process_datagram(datagram(False))
    clock.now += cadence
    listener.process_datagram(datagram(True))
    ptt_started = clock.now
    while clock.now - ptt_started <= 6.0:
        clock.now += cadence
        assert listener.check_liveness(clock.now - 0.001) is True
        listener.process_datagram(datagram(True))
    clock.now += cadence
    listener.process_datagram(datagram(False))

    assert listener.status is SrsTxStateListenerStatus.READY
    assert transitions.count((False, True)) == 1
    assert transitions.count((True, False)) == 1
    assert transitions.count((True, True)) >= 3


def test_malformed_datagrams_never_extend_cadence_or_freshness() -> None:
    clock = Clock()
    listener = SrsTxStateListener(
        threading.Event(),
        lambda _item, _previous: None,
        lambda _status, _age: None,
        lambda _event, _fields: None,
        clock=clock,
    )
    listener.process_datagram(datagram(False))
    clock.now += 1.0
    assert listener.process_datagram(b"not-json") is False

    assert listener.liveness.cadence_sample_count == 0
    clock.now += 4.001
    assert listener.check_liveness() is False


def test_confirmed_true_with_dead_heartbeat_fails_without_fabricated_false() -> None:
    clock = Clock()
    observed: list[bool] = []
    statuses: list[SrsTxStateListenerStatus] = []
    listener = SrsTxStateListener(
        threading.Event(),
        lambda item, _previous: observed.append(item.is_sending),
        lambda status, _age: statuses.append(status),
        lambda _event, _fields: None,
        clock=clock,
    )
    listener.process_datagram(datagram(False))
    clock.now += 1.6
    listener.process_datagram(datagram(False))
    clock.now += 1.6
    listener.process_datagram(datagram(True))
    assert listener.liveness.budget_seconds == pytest.approx(4.8)

    clock.now += 4.801
    assert listener.check_liveness() is False
    assert statuses[-1] is SrsTxStateListenerStatus.STALE
    assert observed == [False, False, True]


class PortBusySocket:
    def setsockopt(self, *_args) -> None:  # noqa: ANN002
        return None

    def bind(self, _address) -> None:  # noqa: ANN001
        raise OSError("address already in use")

    def settimeout(self, _timeout: float) -> None:
        return None

    def close(self) -> None:
        return None


def test_port_unavailable_is_explicit_and_has_no_silent_fallback() -> None:
    statuses: list[SrsTxStateListenerStatus] = []
    events: list[str] = []
    listener = SrsTxStateListener(
        threading.Event(),
        lambda _item, _previous: None,
        lambda status, _age: statuses.append(status),
        lambda event, _fields: events.append(event),
        socket_factory=lambda *_args: PortBusySocket(),
    )

    with pytest.raises(SrsTxStatePortUnavailable, match="127.0.0.1:7082"):
        listener.start(ready_timeout=0.01)

    assert listener.status is SrsTxStateListenerStatus.PORT_UNAVAILABLE
    assert statuses[-1] is SrsTxStateListenerStatus.PORT_UNAVAILABLE
    assert events[-1] == "srs_tx_state_port_unavailable"
    assert not hasattr(PortBusySocket, "send")


class SilentSocket:
    def setsockopt(self, *_args) -> None:  # noqa: ANN002
        return None

    def bind(self, _address) -> None:  # noqa: ANN001
        return None

    def settimeout(self, _timeout: float) -> None:
        return None

    def recvfrom(self, _size: int):  # noqa: ANN202
        time.sleep(0.005)
        raise TimeoutError

    def close(self) -> None:
        return None


def test_no_initial_valid_snapshot_fails_ready_explicitly() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    listener = SrsTxStateListener(
        threading.Event(),
        lambda _item, _previous: None,
        lambda _status, _age: None,
        lambda event, fields: events.append((event, fields)),
        socket_factory=lambda *_args: SilentSocket(),
    )

    with pytest.raises(SrsTxStateUnavailable, match="No valid SRS TX-state snapshots"):
        listener.start(ready_timeout=0.02)

    stale = [fields for event, fields in events if event == "srs_tx_state_stale"]
    assert stale == [
        {"reason": "no_initial_snapshot", "snapshot_age_ms": None, "port": 7082}
    ]
