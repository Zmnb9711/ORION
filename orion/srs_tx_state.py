"""Read-only localhost consumer for official SRS CombinedRadioState snapshots."""

from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Callable

SRS_TX_STATE_HOST = "127.0.0.1"
SRS_TX_STATE_PORT = 7082
SRS_TX_STATE_STALE_SECONDS = 1.0
SRS_TX_STATE_READY_TIMEOUT_SECONDS = 2.0
SRS_TX_STATE_EVIDENCE_INTERVAL_SECONDS = 1.0
SRS_TX_STATE_MAX_DATAGRAM_BYTES = 65_507


class SrsTxStateError(RuntimeError):
    """Base error for an unavailable or ambiguous SRS TX-state stream."""


class SrsTxStatePortUnavailable(SrsTxStateError):
    """The exclusive localhost UDP port could not be acquired."""


class SrsTxStateUnavailable(SrsTxStateError):
    """No valid CombinedRadioState stream became available in time."""


class SrsTxStateListenerStatus(StrEnum):
    STOPPED = "stopped"
    WAITING = "waiting"
    READY = "ready"
    STALE = "stale"
    PORT_UNAVAILABLE = "port_unavailable"


@dataclass(frozen=True, slots=True)
class SrsTxStateSnapshot:
    is_sending: bool
    sending_on: int
    is_encrypted: int
    received_at: float
    received_timestamp: str


TxStateSnapshotCallback = Callable[
    [SrsTxStateSnapshot, SrsTxStateSnapshot | None], None
]
TxStateStatusCallback = Callable[[SrsTxStateListenerStatus, float | None], None]
DiagnosticCallback = Callable[[str, dict[str, object]], None]
SocketFactory = Callable[..., socket.socket]


def parse_combined_radio_state(
    datagram: bytes,
    *,
    received_at: float,
    received_timestamp: str,
) -> SrsTxStateSnapshot:
    """Parse only the official RadioSendingState fields needed by ORION."""

    if not datagram or len(datagram) > SRS_TX_STATE_MAX_DATAGRAM_BYTES:
        raise ValueError("SRS TX-state datagram size is invalid")
    try:
        payload = json.loads(datagram.decode("utf-8").strip())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("SRS TX-state datagram is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("SRS CombinedRadioState must be a JSON object")
    state = payload.get("RadioSendingState")
    if not isinstance(state, dict):
        raise ValueError("SRS RadioSendingState is missing")
    is_sending = state.get("IsSending")
    sending_on = state.get("SendingOn")
    is_encrypted = state.get("IsEncrypted")
    if not isinstance(is_sending, bool):
        raise ValueError("SRS RadioSendingState.IsSending is invalid")
    if isinstance(sending_on, bool) or not isinstance(sending_on, int):
        raise ValueError("SRS RadioSendingState.SendingOn is invalid")
    if isinstance(is_encrypted, bool) or not isinstance(is_encrypted, int):
        raise ValueError("SRS RadioSendingState.IsEncrypted is invalid")
    if sending_on < 0:
        raise ValueError("SRS RadioSendingState.SendingOn is negative")
    if is_encrypted < 0:
        raise ValueError("SRS RadioSendingState.IsEncrypted is negative")
    return SrsTxStateSnapshot(
        is_sending=is_sending,
        sending_on=sending_on,
        is_encrypted=is_encrypted,
        received_at=received_at,
        received_timestamp=received_timestamp,
    )


class SrsTxStateListener:
    """Exclusive localhost listener with bounded liveness and safe diagnostics.

    Windows does not offer portable fan-out semantics for multiple unrelated UDP
    receivers bound to the same unicast endpoint. ORION therefore requests an
    exclusive bind and reports a clear failure instead of stealing traffic from
    an existing flight-control panel or relying on nondeterministic SO_REUSEADDR.
    """

    def __init__(
        self,
        session_stop: threading.Event,
        on_snapshot: TxStateSnapshotCallback,
        on_status: TxStateStatusCallback,
        diagnostic: DiagnosticCallback,
        *,
        host: str = SRS_TX_STATE_HOST,
        port: int = SRS_TX_STATE_PORT,
        stale_seconds: float = SRS_TX_STATE_STALE_SECONDS,
        evidence_interval_seconds: float = SRS_TX_STATE_EVIDENCE_INTERVAL_SECONDS,
        socket_factory: SocketFactory = socket.socket,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if host != SRS_TX_STATE_HOST:
            raise ValueError("SRS TX-state listener must bind to 127.0.0.1")
        if not 1 <= port <= 65_535:
            raise ValueError("SRS TX-state UDP port is invalid")
        if stale_seconds <= 0 or evidence_interval_seconds <= 0:
            raise ValueError("SRS TX-state timing bounds must be positive")
        self._session_stop = session_stop
        self._on_snapshot = on_snapshot
        self._on_status = on_status
        self._diagnostic = diagnostic
        self._host = host
        self._port = port
        self._stale_seconds = stale_seconds
        self._evidence_interval = evidence_interval_seconds
        self._socket_factory = socket_factory
        self._clock = clock
        self._listener_stop = threading.Event()
        self._first_snapshot = threading.Event()
        self._lock = threading.RLock()
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._status = SrsTxStateListenerStatus.STOPPED
        self._latest: SrsTxStateSnapshot | None = None
        self._last_evidence_at: float | None = None
        self._suppressed_snapshots = 0
        self._valid_snapshots = 0
        self._malformed_datagrams = 0

    @property
    def status(self) -> SrsTxStateListenerStatus:
        with self._lock:
            return self._status

    @property
    def latest(self) -> SrsTxStateSnapshot | None:
        with self._lock:
            return self._latest

    def start(
        self,
        ready_timeout: float = SRS_TX_STATE_READY_TIMEOUT_SECONDS,
    ) -> None:
        if ready_timeout <= 0:
            raise ValueError("SRS TX-state ready timeout must be positive")
        with self._lock:
            if self._thread is not None:
                return
            udp = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
                if exclusive is not None:
                    udp.setsockopt(socket.SOL_SOCKET, exclusive, 1)
                udp.bind((self._host, self._port))
                udp.settimeout(0.1)
            except OSError as exc:
                udp.close()
                self._status = SrsTxStateListenerStatus.PORT_UNAVAILABLE
                self._on_status(self._status, None)
                self._diagnostic(
                    "srs_tx_state_port_unavailable",
                    {"port": self._port, "error_type": type(exc).__name__},
                )
                raise SrsTxStatePortUnavailable(
                    f"SRS TX-state UDP {self._host}:{self._port} is unavailable"
                ) from exc
            self._socket = udp
            self._status = SrsTxStateListenerStatus.WAITING
            self._on_status(self._status, None)
            self._thread = threading.Thread(
                target=self._run,
                name="orion-srs-tx-state",
                daemon=True,
            )
            self._thread.start()
        if self._first_snapshot.wait(ready_timeout):
            return
        self._diagnostic(
            "srs_tx_state_stale",
            {
                "reason": "no_initial_snapshot",
                "snapshot_age_ms": None,
                "port": self._port,
            },
        )
        self.stop()
        raise SrsTxStateUnavailable(
            "No valid SRS TX-state snapshots arrived on localhost UDP 7082"
        )

    def stop(self) -> None:
        self._listener_stop.set()
        with self._lock:
            udp = self._socket
            self._socket = None
            worker = self._thread
        if udp is not None:
            udp.close()
        if (
            worker is not None
            and worker is not threading.current_thread()
            and worker.is_alive()
        ):
            worker.join(1.0)
        with self._lock:
            self._thread = None
            self._status = SrsTxStateListenerStatus.STOPPED

    def process_datagram(
        self,
        datagram: bytes,
        *,
        received_at: float | None = None,
        received_timestamp: str | None = None,
    ) -> bool:
        """Process one snapshot; public to support deterministic protocol tests."""

        now = self._clock() if received_at is None else received_at
        timestamp = received_timestamp or datetime.now(UTC).isoformat(
            timespec="milliseconds"
        )
        try:
            snapshot = parse_combined_radio_state(
                datagram,
                received_at=now,
                received_timestamp=timestamp,
            )
        except ValueError as exc:
            with self._lock:
                self._malformed_datagrams += 1
                malformed_count = self._malformed_datagrams
            if malformed_count == 1 or malformed_count % 25 == 0:
                self._diagnostic(
                    "srs_tx_state_malformed",
                    {
                        "malformed_count": malformed_count,
                        "datagram_bytes": len(datagram),
                        "reason": str(exc),
                    },
                )
            return False

        with self._lock:
            previous = self._latest
            recovered = self._status is SrsTxStateListenerStatus.STALE
            self._latest = snapshot
            self._status = SrsTxStateListenerStatus.READY
            self._valid_snapshots += 1
            valid_count = self._valid_snapshots
            transition = previous is None or previous.is_sending != snapshot.is_sending
            periodic = (
                self._last_evidence_at is None
                or now - self._last_evidence_at >= self._evidence_interval
            )
            if transition or periodic:
                suppressed = self._suppressed_snapshots
                self._suppressed_snapshots = 0
                self._last_evidence_at = now
            else:
                self._suppressed_snapshots += 1
                suppressed = -1
        self._first_snapshot.set()
        if valid_count == 1:
            self._diagnostic(
                "srs_tx_state_listener_ready",
                {"host": self._host, "port": self._port, "snapshot_age_ms": 0},
            )
        if recovered:
            self._diagnostic(
                "srs_tx_state_recovered",
                {"snapshot_age_ms": 0, "valid_snapshot_count": valid_count},
            )
        if suppressed >= 0:
            self._diagnostic(
                "srs_tx_state_snapshot",
                {
                    "is_sending": snapshot.is_sending,
                    "sending_on": snapshot.sending_on,
                    "is_encrypted": snapshot.is_encrypted,
                    "snapshot_age_ms": 0,
                    "valid_snapshot_count": valid_count,
                    "suppressed_snapshot_count": suppressed,
                    "transition": transition,
                },
            )
        self._on_status(SrsTxStateListenerStatus.READY, 0.0)
        self._on_snapshot(snapshot, previous)
        return True

    def check_liveness(self, now: float | None = None) -> bool:
        current = self._clock() if now is None else now
        with self._lock:
            latest = self._latest
            if latest is None:
                return False
            age = max(0.0, current - latest.received_at)
            if age < self._stale_seconds:
                return True
            if self._status is SrsTxStateListenerStatus.STALE:
                return False
            self._status = SrsTxStateListenerStatus.STALE
        age_ms = round(age * 1000, 3)
        self._diagnostic(
            "srs_tx_state_stale",
            {"snapshot_age_ms": age_ms, "stale_after_ms": self._stale_seconds * 1000},
        )
        self._on_status(SrsTxStateListenerStatus.STALE, age_ms)
        return False

    def _run(self) -> None:
        while not self._listener_stop.is_set() and not self._session_stop.is_set():
            with self._lock:
                udp = self._socket
            if udp is None:
                return
            try:
                datagram, sender = udp.recvfrom(SRS_TX_STATE_MAX_DATAGRAM_BYTES + 1)
            except TimeoutError:
                self.check_liveness()
                continue
            except OSError:
                if self._listener_stop.is_set() or self._session_stop.is_set():
                    return
                with self._lock:
                    self._status = SrsTxStateListenerStatus.STALE
                    latest = self._latest
                age_ms = (
                    round(max(0.0, self._clock() - latest.received_at) * 1000, 3)
                    if latest is not None
                    else None
                )
                self._diagnostic(
                    "srs_tx_state_stale",
                    {"reason": "listener_socket_error", "snapshot_age_ms": age_ms},
                )
                self._on_status(SrsTxStateListenerStatus.STALE, age_ms)
                return
            if sender[0] != SRS_TX_STATE_HOST:
                self._diagnostic(
                    "srs_tx_state_malformed",
                    {"reason": "non_loopback_sender", "datagram_bytes": len(datagram)},
                )
                continue
            self.process_datagram(datagram)
