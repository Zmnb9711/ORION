"""Core-owned SRS 2.4.x radio transport with bounded lifecycle."""

from __future__ import annotations

import errno
import select
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable

from orion.srs_protocol import (
    AM,
    JsonLineParser,
    MessageType,
    SRS_VERSION,
    SrsProtocolError,
    SrsRadioState,
    build_eam_disconnect_message,
    build_eam_password_message,
    build_ping_message,
    build_radio_update_message,
    build_sync_message,
    compatible_server_version,
    eam_enabled,
    encode_tcp_message,
    generate_client_guid,
    mask_guid,
    radio_info_matches_state,
    validate_guid,
)

PING_INTERVAL_SECONDS = 15.0
CONNECT_TIMEOUT_SECONDS = 10.0
HANDSHAKE_TIMEOUT_SECONDS = 8.0
UDP_READY_TIMEOUT_SECONDS = 5.0

RadioEventCallback = Callable[[str, dict[str, object]], None]
VoiceCallback = Callable[[bytes], None]


class SrsState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING_TCP = "CONNECTING_TCP"
    SYNCING = "SYNCING"
    AUTHENTICATING_EAM = "AUTHENTICATING_EAM"
    REGISTERING_RADIO = "REGISTERING_RADIO"
    RADIO_REGISTERED = "RADIO_REGISTERED"
    REGISTERING_UDP = "REGISTERING_UDP"
    READY = "READY"
    ERROR = "ERROR"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


@dataclass(frozen=True, slots=True)
class SrsRadioConfig:
    host: str = "127.0.0.1"
    port: int = 5002
    bot_name: str = "ORION SRS"
    eam_password: str = field(default="", repr=False)
    frequency_hz: float = 251_000_000.0
    modulation: int = AM
    unit_id: int = 100_000

    def validate(self) -> None:
        if not self.host.strip():
            raise ValueError("SRS Server Host is required.")
        if not 1 <= self.port <= 65_535:
            raise ValueError("SRS Server Port must be between 1 and 65535.")
        if not self.bot_name.strip():
            raise ValueError("SRS bot name is required.")
        if not self.eam_password:
            raise ValueError("SRS EAM password is required.")
        if self.frequency_hz <= 0:
            raise ValueError("SRS target frequency must be positive.")
        if self.modulation != AM:
            raise ValueError("SRS Radio v0.1 supports AM only.")
        if not 0 <= self.unit_id <= 0xFFFFFFFF:
            raise ValueError("SRS UnitID must fit uint32.")


class SrsRadioTransport:
    transport_id = "srs"

    def __init__(
        self,
        config: SrsRadioConfig,
        voice_callback: VoiceCallback,
        event_callback: RadioEventCallback | None = None,
        *,
        client_guid: str | None = None,
        tcp_connector: Callable[..., socket.socket] = socket.create_connection,
        udp_socket_factory: Callable[..., socket.socket] = socket.socket,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        config.validate()
        self.config = config
        self.voice_callback = voice_callback
        self.event_callback = event_callback or (lambda _event, _fields: None)
        self.client_guid = client_guid or generate_client_guid()
        validate_guid(self.client_guid)
        self.radio_state = SrsRadioState(
            config.frequency_hz,
            config.modulation,
            config.unit_id,
        )
        self.tcp_connector = tcp_connector
        self.udp_socket_factory = udp_socket_factory
        self.clock = clock
        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.state = SrsState.DISCONNECTED
        self.coalition = 0
        self.server_version: str | None = None
        self.server_settings: dict[str, object] = {}
        self.clients: dict[str, dict[str, object]] = {}
        self.radio_registered = False
        self.udp_registered = False
        self.tcp_socket: socket.socket | None = None
        self.udp_socket: socket.socket | None = None
        self.tcp_thread: threading.Thread | None = None
        self.udp_thread: threading.Thread | None = None
        self.maintenance_thread: threading.Thread | None = None
        self._tcp_parser = JsonLineParser()
        self._pending_tcp: deque[dict[str, Any]] = deque()
        self._tcp_send_lock = threading.Lock()
        self._udp_send_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self.messages_sent = 0
        self.messages_received = 0
        self.tcp_ping_count = 0
        self.udp_ping_count = 0
        self.tcp_parse_errors = 0
        self.udp_packets_received = 0
        self.udp_packets_sent = 0
        self.udp_voice_before_ready = 0
        self.udp_wrong_echo = 0
        self.disconnect_origin: str | None = None
        self.worker_close_status: dict[str, bool] = {}

    def _emit(self, event: str, **fields: object) -> None:
        self.event_callback(event, fields)

    def _set_state(self, state: SrsState) -> None:
        self.state = state
        self._emit("srs.state", value=state.value)

    def connect(self) -> None:
        if self.state not in {SrsState.DISCONNECTED, SrsState.STOPPED}:
            raise RuntimeError("SRS transport is already started.")
        self.stop_event.clear()
        self.ready_event.clear()
        self.radio_registered = False
        self.udp_registered = False
        self._tcp_parser = JsonLineParser()
        self._pending_tcp.clear()
        try:
            self._set_state(SrsState.CONNECTING_TCP)
            self.tcp_socket = self._open_tcp()
            self.tcp_socket.settimeout(0.2)
            self._set_state(SrsState.SYNCING)
            self._send_tcp(
                build_sync_message(
                    self.client_guid,
                    self.config.bot_name,
                    radio_state=self.radio_state,
                )
            )
            sync = self._wait_for_message(MessageType.SYNC, HANDSHAKE_TIMEOUT_SECONDS)
            self.server_version = str(sync.get("Version") or "")
            if not compatible_server_version(self.server_version):
                raise SrsProtocolError(
                    f"Unsupported SRS server version {self.server_version!r}; expected 2.4.x."
                )
            settings = sync.get("ServerSettings")
            if not isinstance(settings, dict):
                raise SrsProtocolError("SRS SYNC is missing ServerSettings.")
            self.server_settings = {str(key): value for key, value in settings.items()}
            self._update_clients(sync.get("Clients"))
            if not eam_enabled(self.server_settings):
                raise SrsProtocolError("SRS External AWACS Mode is disabled.")

            self._set_state(SrsState.AUTHENTICATING_EAM)
            self._send_tcp(
                build_eam_password_message(
                    self.client_guid,
                    self.config.bot_name,
                    self.config.eam_password,
                )
            )
            eam = self._wait_for_message(
                MessageType.EXTERNAL_AWACS_MODE_PASSWORD,
                HANDSHAKE_TIMEOUT_SECONDS,
            )
            client = eam.get("Client")
            if not isinstance(client, dict):
                raise SrsProtocolError("Malformed EAM response: Client is missing.")
            coalition = client.get("Coalition")
            if coalition not in {1, 2}:
                raise SrsProtocolError("External AWACS authentication failed (coalition 0/invalid).")
            self.coalition = int(coalition)

            self._set_state(SrsState.REGISTERING_RADIO)
            self._send_tcp(
                build_radio_update_message(
                    self.client_guid,
                    self.config.bot_name,
                    self.coalition,
                    self.config.frequency_hz,
                    self.config.modulation,
                    self.config.unit_id,
                    radio_state=self.radio_state,
                )
            )
            self._wait_for_radio_registration(HANDSHAKE_TIMEOUT_SECONDS)
            self.radio_registered = True
            self._set_state(SrsState.RADIO_REGISTERED)
            self._set_state(SrsState.REGISTERING_UDP)
            self._register_udp()
            self.udp_registered = True
            if self.stop_event.is_set():
                raise InterruptedError("SRS start stopped during handshake.")
            if not self.radio_registered or not self.udp_registered:
                raise AssertionError("SRS READY prerequisites are incomplete.")
            self._set_state(SrsState.READY)
            self.ready_event.set()
            self._start_workers()
            self._emit(
                "srs.ready",
                server_version=self.server_version,
                coalition=self.coalition,
                client_id=mask_guid(self.client_guid),
                frequency_hz=self.config.frequency_hz,
                modulation=self.config.modulation,
            )
        except Exception:
            if not self.stop_event.is_set():
                self._set_state(SrsState.ERROR)
            self.close(send_disconnect=False, preserve_error=True)
            raise

    def _open_tcp(self) -> socket.socket:
        if self.tcp_connector is not socket.create_connection:
            return self.tcp_connector(
                (self.config.host, self.config.port),
                timeout=CONNECT_TIMEOUT_SECONDS,
            )
        deadline = self.clock() + CONNECT_TIMEOUT_SECONDS
        last_error: OSError | None = None
        addresses = socket.getaddrinfo(self.config.host, self.config.port, type=socket.SOCK_STREAM)
        for family, socktype, protocol, _canonical, address in addresses:
            candidate = socket.socket(family, socktype, protocol)
            self.tcp_socket = candidate
            candidate.setblocking(False)
            try:
                result = candidate.connect_ex(address)
                pending_codes = {
                    0,
                    errno.EINPROGRESS,
                    errno.EWOULDBLOCK,
                    errno.EALREADY,
                    getattr(errno, "WSAEINPROGRESS", 10036),
                    getattr(errno, "WSAEWOULDBLOCK", 10035),
                    getattr(errno, "WSAEALREADY", 10037),
                }
                if result not in pending_codes:
                    raise OSError(result, "SRS TCP connect failed")
                while not self.stop_event.is_set() and self.clock() < deadline:
                    _readable, writable, exceptional = select.select([], [candidate], [candidate], 0.1)
                    if exceptional:
                        error = candidate.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                        raise OSError(error, "SRS TCP connect failed")
                    if writable:
                        error = candidate.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                        if error:
                            raise OSError(error, "SRS TCP connect failed")
                        candidate.setblocking(True)
                        return candidate
                if self.stop_event.is_set():
                    raise InterruptedError("SRS TCP connect stopped.")
                raise TimeoutError("SRS TCP connect timed out.")
            except InterruptedError:
                candidate.close()
                self.tcp_socket = None
                raise
            except OSError as exc:
                last_error = exc
                candidate.close()
                self.tcp_socket = None
        if self.clock() >= deadline:
            raise TimeoutError("SRS TCP connect timed out.")
        raise last_error or ConnectionError("SRS TCP address resolution produced no endpoints.")

    def _wait_for_message(self, expected: MessageType, timeout: float) -> dict[str, Any]:
        deadline = self.clock() + timeout
        while not self.stop_event.is_set():
            message = self._pending_tcp.popleft() if self._pending_tcp else self._recv_tcp_message(deadline)
            raw_type = message.get("MsgType")
            if not isinstance(raw_type, (int, str)):
                raise SrsProtocolError(f"Unexpected SRS message type {raw_type!r}.")
            try:
                message_type = MessageType(int(raw_type))
            except (TypeError, ValueError) as exc:
                raise SrsProtocolError(f"Unexpected SRS message type {raw_type!r}.") from exc
            if message_type is MessageType.VERSION_MISMATCH:
                raise SrsProtocolError(
                    f"SRS VERSION_MISMATCH (server {message.get('Version')!r}, client {SRS_VERSION})."
                )
            if message_type is expected:
                return message
            self._handle_tcp_message(message, during_handshake=True)
        raise InterruptedError("SRS handshake stopped.")

    def _recv_tcp_message(self, deadline: float) -> dict[str, Any]:
        tcp = self.tcp_socket
        if tcp is None:
            raise ConnectionError("SRS TCP socket is unavailable.")
        while not self.stop_event.is_set():
            if self._pending_tcp:
                return self._pending_tcp.popleft()
            if self.clock() >= deadline:
                raise TimeoutError("Timed out waiting for SRS TCP handshake message.")
            try:
                chunk = tcp.recv(65_536)
            except socket.timeout:
                continue
            if not chunk:
                self._tcp_parser.eof()
                raise ConnectionError("SRS TCP closed without a complete handshake.")
            try:
                messages = self._tcp_parser.feed(chunk)
            except SrsProtocolError:
                self.tcp_parse_errors += 1
                raise
            self.messages_received += len(messages)
            self._pending_tcp.extend(messages)
        raise InterruptedError("SRS TCP receive stopped.")

    def _wait_for_radio_registration(self, timeout: float) -> None:
        deadline = self.clock() + timeout
        while not self.stop_event.is_set():
            message = self._recv_tcp_message(deadline)
            raw_type = message.get("MsgType")
            if not isinstance(raw_type, (int, str)):
                raise SrsProtocolError(f"Unexpected SRS message type {raw_type!r}.")
            try:
                kind = MessageType(int(raw_type))
            except (TypeError, ValueError) as exc:
                raise SrsProtocolError(f"Unexpected SRS message type {raw_type!r}.") from exc
            if kind is MessageType.VERSION_MISMATCH:
                raise SrsProtocolError("SRS server reported VERSION_MISMATCH.")
            client = message.get("Client")
            if (
                kind is MessageType.RADIO_UPDATE
                and isinstance(client, dict)
                and client.get("ClientGuid") == self.client_guid
                and client.get("Coalition") == self.coalition
                and radio_info_matches_state(client.get("RadioInfo"), self.radio_state)
            ):
                self._handle_tcp_message(message, during_handshake=True)
                return
            self._handle_tcp_message(message, during_handshake=True)
        raise InterruptedError("SRS radio registration stopped.")

    def _register_udp(self) -> None:
        udp = self.udp_socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket = udp
        udp.settimeout(0.2)
        udp.connect((self.config.host, self.config.port))
        guid = self.client_guid.encode("ascii")
        udp.send(guid)
        self.udp_ping_count += 1
        deadline = self.clock() + UDP_READY_TIMEOUT_SECONDS
        while not self.stop_event.is_set() and self.clock() < deadline:
            try:
                reply = udp.recv(65_535)
            except socket.timeout:
                continue
            if len(reply) == 22:
                if reply == guid:
                    return
                self.udp_wrong_echo += 1
                continue
            self.udp_voice_before_ready += 1
        if self.stop_event.is_set():
            raise InterruptedError("SRS UDP registration stopped.")
        raise TimeoutError("SRS UDP GUID echo was not received before timeout.")

    def _start_workers(self) -> None:
        self.tcp_thread = threading.Thread(target=self._tcp_worker, name="srs-tcp-rx", daemon=True)
        self.udp_thread = threading.Thread(target=self._udp_worker, name="srs-udp-rx", daemon=True)
        self.maintenance_thread = threading.Thread(
            target=self._maintenance_worker,
            name="srs-keepalive",
            daemon=True,
        )
        self.tcp_thread.start()
        self.udp_thread.start()
        self.maintenance_thread.start()

    def _tcp_worker(self) -> None:
        try:
            while not self.stop_event.is_set():
                try:
                    message = self._recv_tcp_message(self.clock() + 0.5)
                except TimeoutError:
                    continue
                self._handle_tcp_message(message)
        except Exception as exc:
            if not self.stop_event.is_set():
                self.disconnect_origin = "tcp_receive"
                self._emit("srs.error", category="TCP_RECEIVE", message=str(exc))
                self._set_state(SrsState.ERROR)
                self.stop_event.set()

    def _handle_tcp_message(self, message: dict[str, Any], during_handshake: bool = False) -> None:
        raw_type = message.get("MsgType")
        if not isinstance(raw_type, (int, str)):
            self.tcp_parse_errors += 1
            self._emit("srs.tcp.unexpected", msg_type=str(raw_type))
            return
        try:
            kind = MessageType(int(raw_type))
        except (TypeError, ValueError):
            self.tcp_parse_errors += 1
            self._emit("srs.tcp.unexpected", msg_type=str(raw_type))
            return
        if kind is MessageType.VERSION_MISMATCH:
            raise SrsProtocolError("SRS server reported VERSION_MISMATCH.")
        if kind in {MessageType.UPDATE, MessageType.RADIO_UPDATE}:
            settings = message.get("ServerSettings")
            if isinstance(settings, dict):
                self.server_settings.update({str(key): value for key, value in settings.items()})
            client = message.get("Client")
            if isinstance(client, dict) and isinstance(client.get("ClientGuid"), str):
                self.clients[str(client["ClientGuid"])] = client
        elif kind is MessageType.CLIENT_DISCONNECT:
            client = message.get("Client")
            if isinstance(client, dict):
                self.clients.pop(str(client.get("ClientGuid") or ""), None)
        elif kind is MessageType.SERVER_SETTINGS:
            settings = message.get("ServerSettings")
            if isinstance(settings, dict):
                self.server_settings = {str(key): value for key, value in settings.items()}
            if not eam_enabled(self.server_settings):
                raise SrsProtocolError("SRS External AWACS Mode was disabled during the session.")
        elif kind not in {MessageType.PING, MessageType.SYNC, MessageType.EXTERNAL_AWACS_MODE_PASSWORD}:
            self._emit("srs.tcp.unexpected", msg_type=int(kind), handshake=during_handshake)

    def _update_clients(self, raw_clients: object) -> None:
        if raw_clients is None:
            return
        if not isinstance(raw_clients, list):
            raise SrsProtocolError("SRS SYNC Clients field is not an array.")
        for client in raw_clients:
            if isinstance(client, dict) and isinstance(client.get("ClientGuid"), str):
                self.clients[str(client["ClientGuid"])] = client

    def _udp_worker(self) -> None:
        udp = self.udp_socket
        if udp is None:
            return
        try:
            while not self.stop_event.is_set():
                try:
                    datagram = udp.recv(65_535)
                except socket.timeout:
                    continue
                if len(datagram) == 22:
                    continue
                self.udp_packets_received += 1
                self.voice_callback(datagram)
        except Exception as exc:
            if not self.stop_event.is_set():
                self.disconnect_origin = "udp_receive"
                self._emit("srs.error", category="UDP_RECEIVE", message=str(exc))
                self._set_state(SrsState.ERROR)
                self.stop_event.set()

    def _maintenance_worker(self) -> None:
        next_ping = self.clock() + PING_INTERVAL_SECONDS
        while not self.stop_event.wait(0.1):
            now = self.clock()
            if now < next_ping:
                continue
            try:
                self._send_keepalive()
            except Exception as exc:
                if not self.stop_event.is_set():
                    self.disconnect_origin = "keepalive"
                    self._emit("srs.error", category="KEEPALIVE", message=str(exc))
                    self._set_state(SrsState.ERROR)
                    self.stop_event.set()
                return
            next_ping += PING_INTERVAL_SECONDS

    def _send_keepalive(self) -> None:
        self._send_tcp(build_ping_message(self.client_guid, self.config.bot_name, self.coalition))
        udp = self.udp_socket
        if udp is None:
            raise ConnectionError("SRS UDP socket is unavailable.")
        with self._udp_send_lock:
            udp.send(self.client_guid.encode("ascii"))
        self.udp_ping_count += 1

    def _send_tcp(self, message: dict[str, object]) -> None:
        tcp = self.tcp_socket
        if tcp is None:
            raise ConnectionError("SRS TCP socket is unavailable.")
        with self._tcp_send_lock:
            tcp.sendall(encode_tcp_message(message))
        self.messages_sent += 1
        if message.get("MsgType") == int(MessageType.PING):
            self.tcp_ping_count += 1

    def send_voice(self, datagram: bytes) -> None:
        if (
            not self.ready_event.is_set()
            or self.state is not SrsState.READY
            or not self.radio_registered
            or not self.udp_registered
        ):
            raise RuntimeError("SRS UDP voice TX is not allowed before radio and UDP readiness.")
        udp = self.udp_socket
        if udp is None:
            raise ConnectionError("SRS UDP socket is unavailable.")
        with self._udp_send_lock:
            udp.send(datagram)
        self.udp_packets_sent += 1

    def close(
        self,
        *,
        send_disconnect: bool = True,
        timeout: float = 2.0,
        preserve_error: bool = False,
    ) -> None:
        with self._close_lock:
            if self.state in {SrsState.STOPPED, SrsState.DISCONNECTED} and self.tcp_socket is None:
                return
            prior = self.state
            if prior is not SrsState.ERROR:
                self._set_state(SrsState.STOPPING)
            if send_disconnect and self.tcp_socket is not None and self.coalition in {1, 2}:
                try:
                    self._send_tcp(
                        build_eam_disconnect_message(
                            self.client_guid,
                            self.config.bot_name,
                            self.coalition,
                        )
                    )
                except OSError:
                    pass
            self.stop_event.set()
            self.ready_event.clear()
            self.radio_registered = False
            self.udp_registered = False
            for active in (self.udp_socket, self.tcp_socket):
                if active is not None:
                    try:
                        active.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    try:
                        active.close()
                    except OSError:
                        pass
            self.udp_socket = None
            self.tcp_socket = None
            current = threading.current_thread()
            for worker in (self.tcp_thread, self.udp_thread, self.maintenance_thread):
                if worker is not None and worker is not current and worker.is_alive():
                    worker.join(timeout)
                if worker is not None:
                    self.worker_close_status[worker.name] = not worker.is_alive()
            if prior is not SrsState.ERROR or not preserve_error:
                self._set_state(SrsState.STOPPED)

    def report(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "host": self.config.host,
            "port": self.config.port,
            "server_version": self.server_version,
            "frequency_hz": self.config.frequency_hz,
            "modulation": self.config.modulation,
            "eam_enabled": eam_enabled(self.server_settings),
            "coalition": self.coalition,
            "radio_registered": self.radio_registered,
            "udp_registered": self.udp_registered,
            "client_id": mask_guid(self.client_guid),
            "tcp_messages_sent": self.messages_sent,
            "tcp_messages_received": self.messages_received,
            "tcp_ping_count": self.tcp_ping_count,
            "tcp_parse_errors": self.tcp_parse_errors,
            "udp_ping_count": self.udp_ping_count,
            "udp_packets_received": self.udp_packets_received,
            "udp_packets_sent": self.udp_packets_sent,
            "udp_voice_before_ready": self.udp_voice_before_ready,
            "udp_wrong_echo": self.udp_wrong_echo,
            "disconnect_origin": self.disconnect_origin,
            "clean_stop": all(self.worker_close_status.values()) if self.worker_close_status else None,
        }
