from __future__ import annotations

import copy
import json
import socket
import threading
import time
from typing import Any

import pytest

import orion.srs_radio_transport as radio_module
from orion.srs_protocol import MessageType, SrsRadioState, build_radio_info
from orion.srs_radio_transport import SrsRadioConfig, SrsRadioTransport, SrsState

GUID = "GGGGGGGGGGGGGGGGGGGGGG"


def line(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


class FakeTcp:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = list(chunks)
        self.sent: list[bytes] = []
        self.closed = False

    def settimeout(self, _value: float) -> None:
        return None

    def recv(self, _size: int) -> bytes:
        if self.closed:
            return b""
        if self.chunks:
            return self.chunks.pop(0)
        raise socket.timeout()

    def sendall(self, data: bytes) -> None:
        if self.closed:
            raise OSError("closed")
        self.sent.append(data)

    def shutdown(self, _how: int) -> None:
        self.closed = True

    def close(self) -> None:
        self.closed = True


class FakeUdp:
    def __init__(self, replies: list[bytes]) -> None:
        self.replies = list(replies)
        self.sent: list[bytes] = []
        self.closed = False

    def settimeout(self, _value: float) -> None:
        return None

    def connect(self, _endpoint: tuple[str, int]) -> None:
        return None

    def send(self, data: bytes) -> int:
        if self.closed:
            raise OSError("closed")
        self.sent.append(data)
        return len(data)

    def recv(self, _size: int) -> bytes:
        if self.closed:
            raise OSError("closed")
        if self.replies:
            return self.replies.pop(0)
        raise socket.timeout()

    def shutdown(self, _how: int) -> None:
        self.closed = True

    def close(self) -> None:
        self.closed = True


class Srs240StatefulFakeTcp(FakeTcp):
    """SRS 2.4 registry including its original null-sensitive update."""

    def __init__(self, *, broadcast_radio_update: bool = True) -> None:
        super().__init__([])
        self.registry: dict[str, object] | None = None
        self.broadcast_radio_update = broadcast_radio_update
        self.radio_update_exception = False

    def sendall(self, data: bytes) -> None:
        super().sendall(data)
        message = json.loads(data)
        kind = MessageType(int(message["MsgType"]))
        incoming = message.get("Client")
        assert isinstance(incoming, dict)
        if kind is MessageType.SYNC:
            self.registry = copy.deepcopy(incoming)
            self.chunks.append(
                line(
                    {
                        "MsgType": int(MessageType.SYNC),
                        "Version": "2.4.0.0",
                        "ServerSettings": {"EXTERNAL_AWACS_MODE": "true"},
                        "Clients": [],
                    }
                )
            )
        elif kind is MessageType.EXTERNAL_AWACS_MODE_PASSWORD:
            assert self.registry is not None
            self.registry["Coalition"] = 2
            self.chunks.append(
                line(
                    {
                        "MsgType": int(MessageType.EXTERNAL_AWACS_MODE_PASSWORD),
                        "Version": "2.4.0.0",
                        "Client": {"Coalition": 2},
                    }
                )
            )
        elif kind is MessageType.RADIO_UPDATE:
            assert self.registry is not None
            if self.registry.get("RadioInfo") is None:
                self.radio_update_exception = True
                return
            self.registry.update(copy.deepcopy(incoming))
            if self.broadcast_radio_update:
                self.chunks.append(
                    line(
                        {
                            "MsgType": int(MessageType.RADIO_UPDATE),
                            "Version": "2.4.0.0",
                            "Client": copy.deepcopy(self.registry),
                        }
                    )
                )

    def route_voice(
        self,
        udp: FakeUdp,
        datagram: bytes,
        *,
        frequency_hz: float,
        modulation: int,
        encryption: int = 0,
    ) -> bool:
        if self.registry is None:
            return False
        radio_info = self.registry.get("RadioInfo")
        radios = radio_info.get("radios") if isinstance(radio_info, dict) else None
        if not isinstance(radios, list) or self.registry.get("Coalition") != 2:
            return False
        matched = any(
            isinstance(radio, dict)
            and abs(float(radio.get("freq", 0.0)) - frequency_hz) < 500.0
            and radio.get("modulation") == modulation
            and (radio.get("encKey") if radio.get("enc") else 0) == encryption
            for radio in radios
        )
        if matched:
            udp.replies.append(datagram)
        return matched


def handshake_messages(coalition: int = 2, version: str = "2.4.0.0") -> bytes:
    return line(
        {
            "MsgType": int(MessageType.SYNC),
            "Version": version,
            "ServerSettings": {"EXTERNAL_AWACS_MODE": "true"},
            "Clients": [],
        }
    ) + line(
        {
            "MsgType": int(MessageType.EXTERNAL_AWACS_MODE_PASSWORD),
            "Version": version,
            "Client": {"Coalition": coalition},
        }
    ) + line(
        {
            "MsgType": int(MessageType.RADIO_UPDATE),
            "Version": version,
            "Client": {
                "ClientGuid": GUID,
                "Name": "ORION SRS",
                "Coalition": coalition,
                "RadioInfo": build_radio_info(SrsRadioState()),
            },
        }
    )


def make_transport(
    tcp: FakeTcp,
    udp: FakeUdp,
    voice_callback: Any = None,
) -> SrsRadioTransport:
    return SrsRadioTransport(
        SrsRadioConfig(eam_password="memory-only"),
        voice_callback or (lambda _datagram: None),
        client_guid=GUID,
        tcp_connector=lambda *_args, **_kwargs: tcp,  # type: ignore[arg-type]
        udp_socket_factory=lambda *_args, **_kwargs: udp,  # type: ignore[arg-type]
    )


def decoded_sent(tcp: FakeTcp) -> list[dict[str, Any]]:
    return [json.loads(raw.decode()) for raw in tcp.sent]


def test_fragmented_handshake_requires_radio_then_udp_and_stops_cleanly() -> None:
    combined = handshake_messages()
    tcp = FakeTcp([combined[:17], combined[17:]])
    udp = FakeUdp([b"voice-before-ready", GUID.encode()])
    transport = make_transport(tcp, udp)
    transport.connect()
    assert transport.state is SrsState.READY
    assert transport.radio_registered and transport.udp_registered
    assert transport.ready_event.is_set()
    assert transport.udp_voice_before_ready == 1
    assert [item["MsgType"] for item in decoded_sent(tcp)[:3]] == [2, 7, 3]
    transport.close()
    assert transport.state is SrsState.STOPPED


def test_srs240_registry_regression_initial_radio_info_prevents_server_exception() -> None:
    tcp = Srs240StatefulFakeTcp()
    udp = FakeUdp([GUID.encode()])
    transport = make_transport(tcp, udp)
    transport.connect()
    sent = decoded_sent(tcp)
    initial = sent[0]["Client"]["RadioInfo"]
    subsequent = sent[2]["Client"]["RadioInfo"]
    assert initial is not None and initial == subsequent
    assert tcp.radio_update_exception is False
    assert tcp.registry is not None and tcp.registry["RadioInfo"] == initial
    transport.close()


def test_guid_echo_cannot_bypass_missing_server_radio_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(radio_module, "HANDSHAKE_TIMEOUT_SECONDS", 0.02)
    tcp = Srs240StatefulFakeTcp(broadcast_radio_update=False)
    udp = FakeUdp([GUID.encode()])
    transport = make_transport(tcp, udp)
    with pytest.raises(TimeoutError, match="TCP handshake"):
        transport.connect()
    assert not transport.radio_registered
    assert not transport.ready_event.is_set()
    assert udp.sent == []


def test_routing_requires_valid_registered_matching_251_am_blue_state() -> None:
    delivered: list[bytes] = []
    received = threading.Event()

    def on_voice(datagram: bytes) -> None:
        delivered.append(datagram)
        received.set()

    tcp = Srs240StatefulFakeTcp()
    udp = FakeUdp([GUID.encode()])
    transport = make_transport(tcp, udp, on_voice)
    transport.connect()
    assert tcp.route_voice(udp, b"human", frequency_hz=251_000_000.0, modulation=0)
    assert received.wait(1.0)
    assert not tcp.route_voice(udp, b"wrong-freq", frequency_hz=250_000_000.0, modulation=0)
    assert not tcp.route_voice(udp, b"wrong-mod", frequency_hz=251_000_000.0, modulation=1)
    assert tcp.registry is not None
    tcp.registry["RadioInfo"] = None
    assert not tcp.route_voice(udp, b"missing-radio", frequency_hz=251_000_000.0, modulation=0)
    transport.close()


@pytest.mark.parametrize(
    "coalition,version,match",
    [(0, "2.4.0.0", "coalition"), (2, "2.3.9.0", "Unsupported")],
)
def test_invalid_eam_and_version_are_fatal(coalition: int, version: str, match: str) -> None:
    transport = make_transport(
        FakeTcp([handshake_messages(coalition, version)]),
        FakeUdp([GUID.encode()]),
    )
    with pytest.raises(Exception, match=match):
        transport.connect()
    assert transport.state is SrsState.ERROR


def test_wrong_echo_timeout_stop_during_udp_and_tx_before_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tcp = FakeTcp([handshake_messages()])
    udp = FakeUdp([b"XXXXXXXXXXXXXXXXXXXXXX", GUID.encode()])
    transport = make_transport(tcp, udp)
    transport.connect()
    assert transport.udp_wrong_echo == 1
    transport.close()

    idle = SrsRadioTransport(
        SrsRadioConfig(eam_password="x"),
        lambda _: None,
        client_guid=GUID,
    )
    with pytest.raises(RuntimeError, match="before radio and UDP"):
        idle.send_voice(b"voice")

    monkeypatch.setattr(radio_module, "UDP_READY_TIMEOUT_SECONDS", 0.02)
    timed = make_transport(FakeTcp([handshake_messages()]), FakeUdp([]))
    with pytest.raises(TimeoutError, match="GUID echo"):
        timed.connect()
    assert timed.state is SrsState.ERROR


def test_start_stop_start_uses_fresh_bounded_transport_instances() -> None:
    for _ in range(2):
        transport = make_transport(FakeTcp([handshake_messages()]), FakeUdp([GUID.encode()]))
        transport.connect()
        assert transport.state is SrsState.READY
        transport.close()
        assert transport.state is SrsState.STOPPED


def test_same_transport_start_stop_start_uses_fresh_sockets() -> None:
    tcp_sockets = [FakeTcp([handshake_messages()]), FakeTcp([handshake_messages()])]
    udp_sockets = [FakeUdp([GUID.encode()]), FakeUdp([GUID.encode()])]
    transport = SrsRadioTransport(
        SrsRadioConfig(eam_password="memory-only"),
        lambda _: None,
        client_guid=GUID,
        tcp_connector=lambda *_args, **_kwargs: tcp_sockets.pop(0),  # type: ignore[arg-type]
        udp_socket_factory=lambda *_args, **_kwargs: udp_sockets.pop(0),  # type: ignore[arg-type]
    )
    for _ in range(2):
        transport.connect()
        assert transport.state is SrsState.READY
        transport.close()
        assert transport.state is SrsState.STOPPED


@pytest.mark.parametrize("stage", ["eam", "radio", "udp"])
def test_stop_during_handshake_stages_is_bounded(stage: str) -> None:
    transport: SrsRadioTransport

    class StagedTcp(FakeTcp):
        def sendall(self, data: bytes) -> None:
            super().sendall(data)
            kind = MessageType(int(json.loads(data)["MsgType"]))
            if kind is MessageType.SYNC:
                self.chunks.append(
                    line(
                        {
                            "MsgType": 2,
                            "Version": "2.4.0.0",
                            "ServerSettings": {"EXTERNAL_AWACS_MODE": "true"},
                            "Clients": [],
                        }
                    )
                )
            elif kind is MessageType.EXTERNAL_AWACS_MODE_PASSWORD:
                if stage == "eam":
                    transport.stop_event.set()
                    return
                self.chunks.append(
                    line({"MsgType": 7, "Version": "2.4.0.0", "Client": {"Coalition": 2}})
                )
            elif kind is MessageType.RADIO_UPDATE:
                if stage == "radio":
                    transport.stop_event.set()
                    return
                client = json.loads(data)["Client"]
                self.chunks.append(
                    line({"MsgType": 3, "Version": "2.4.0.0", "Client": client})
                )

    class StoppingUdp(FakeUdp):
        def recv(self, _size: int) -> bytes:
            if stage == "udp":
                transport.stop_event.set()
            raise socket.timeout()

    tcp = StagedTcp([])
    udp = StoppingUdp([])
    transport = make_transport(tcp, udp)
    with pytest.raises(InterruptedError, match="stopped"):
        transport.connect()
    assert transport.state is SrsState.STOPPED
    assert not transport.ready_event.is_set()


def test_tcp_eof_during_fragmented_message_is_fatal() -> None:
    tcp = FakeTcp([b'{"MsgType":2', b""])
    transport = make_transport(tcp, FakeUdp([]))
    with pytest.raises(Exception, match="EOF"):
        transport.connect()
    assert transport.state is SrsState.ERROR


def test_stop_during_connect_is_bounded() -> None:
    transport: SrsRadioTransport

    def connector(*_args: object, **_kwargs: object) -> FakeTcp:
        transport.stop_event.set()
        raise InterruptedError("SRS TCP connect stopped.")

    transport = SrsRadioTransport(
        SrsRadioConfig(eam_password="memory-only"),
        lambda _: None,
        client_guid=GUID,
        tcp_connector=connector,  # type: ignore[arg-type]
    )
    with pytest.raises(InterruptedError, match="stopped"):
        transport.connect()
    assert transport.state is SrsState.STOPPED


def test_post_ready_network_failure_transitions_to_error() -> None:
    class FailingTcp(FakeTcp):
        fail = False

        def recv(self, size: int) -> bytes:
            if self.fail:
                raise ConnectionResetError("simulated reset")
            return super().recv(size)

    tcp = FailingTcp([handshake_messages()])
    transport = make_transport(tcp, FakeUdp([GUID.encode()]))
    transport.connect()
    tcp.fail = True
    deadline = time.monotonic() + 1.0
    while transport.state is not SrsState.ERROR and time.monotonic() < deadline:
        time.sleep(0.01)
    assert transport.state is SrsState.ERROR
    transport.close()
