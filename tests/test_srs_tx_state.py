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

    assert listener.check_liveness() is False
    assert listener.status is SrsTxStateListenerStatus.STALE
    clock.now += 0.1
    listener.process_datagram(datagram(False))

    assert listener.status is SrsTxStateListenerStatus.READY
    assert "srs_tx_state_stale" in events
    assert "srs_tx_state_recovered" in events
    assert statuses[-1] == (SrsTxStateListenerStatus.READY, 0.0)


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
