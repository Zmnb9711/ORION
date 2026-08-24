from __future__ import annotations

import json
import socket
from typing import Any

import pytest

from srs_protocol import MessageType
import srs_radio_client as radio_module
from srs_radio_client import SrsRadioClient, SrsRadioConfig, SrsState

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
        self.endpoint: tuple[str, int] | None = None

    def settimeout(self, _value: float) -> None:
        return None

    def connect(self, endpoint: tuple[str, int]) -> None:
        self.endpoint = endpoint

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


def handshake_messages(coalition: int = 2, version: str = "2.4.0.0") -> bytes:
    return line(
        {
            "MsgType": int(MessageType.SYNC),
            "Version": version,
            "ServerSettings": {"EXTERNAL_AWACS_MODE": "true"},
            "Clients": [{"ClientGuid": "HHHHHHHHHHHHHHHHHHHHHH", "Name": "Human"}],
        }
    ) + line(
        {
            "MsgType": int(MessageType.EXTERNAL_AWACS_MODE_PASSWORD),
            "Version": version,
            "Client": {"Coalition": coalition},
        }
    )


def make_client(tcp: FakeTcp, udp: FakeUdp, events: list[tuple[str, dict[str, object]]]) -> SrsRadioClient:
    return SrsRadioClient(
        SrsRadioConfig(eam_password="test-password"),
        lambda _datagram: None,
        lambda event, fields: events.append((event, fields)),
        client_guid=GUID,
        tcp_connector=lambda *_args, **_kwargs: tcp,  # type: ignore[arg-type]
        udp_socket_factory=lambda *_args, **_kwargs: udp,  # type: ignore[arg-type]
    )


def decoded_sent(tcp: FakeTcp) -> list[dict[str, Any]]:
    return [json.loads(raw.decode()) for raw in tcp.sent]


def test_full_fake_handshake_fragmented_tcp_udp_echo_gate_and_clean_stop() -> None:
    combined = handshake_messages()
    tcp = FakeTcp([combined[:17], combined[17:]])
    udp = FakeUdp([b"voice-before-ready", GUID.encode()])
    events: list[tuple[str, dict[str, object]]] = []
    client = make_client(tcp, udp, events)
    client.connect()
    assert client.state is SrsState.READY
    assert client.ready_event.is_set()
    assert client.server_version == "2.4.0.0"
    assert client.coalition == 2
    assert client.clients["HHHHHHHHHHHHHHHHHHHHHH"]["Name"] == "Human"
    assert client.udp_voice_before_ready == 1
    assert udp.sent[0] == GUID.encode()
    sent = decoded_sent(tcp)
    assert [item["MsgType"] for item in sent[:3]] == [2, 7, 3]
    assert sent[1]["ExternalAWACSModePassword"] == "test-password"
    client._send_keepalive()
    assert decoded_sent(tcp)[-1]["MsgType"] == int(MessageType.PING)
    assert udp.sent[-1] == GUID.encode()
    assert client.tcp_ping_count == 1
    assert client.udp_ping_count == 2
    client.close()
    assert client.state is SrsState.STOPPED
    assert not client.ready_event.is_set()
    assert decoded_sent(tcp)[-1]["MsgType"] == 8


@pytest.mark.parametrize(
    "coalition,version,match",
    [(0, "2.4.0.0", "coalition"), (2, "2.3.9.0", "Unsupported")],
)
def test_eam_zero_and_unsupported_version_are_fatal(
    coalition: int, version: str, match: str
) -> None:
    tcp = FakeTcp([handshake_messages(coalition, version)])
    udp = FakeUdp([GUID.encode()])
    client = make_client(tcp, udp, [])
    with pytest.raises(Exception, match=match):
        client.connect()
    assert client.state is SrsState.ERROR
    client.close()
    assert client.state is SrsState.STOPPED


def test_udp_wrong_echo_is_rejected_before_correct_echo() -> None:
    tcp = FakeTcp([handshake_messages()])
    udp = FakeUdp([b"XXXXXXXXXXXXXXXXXXXXXX", GUID.encode()])
    client = make_client(tcp, udp, [])
    client.connect()
    assert client.udp_wrong_echo == 1
    client.close()


def test_voice_tx_is_impossible_before_ready() -> None:
    client = SrsRadioClient(
        SrsRadioConfig(eam_password="x"),
        lambda _: None,
        lambda *_: None,
        client_guid=GUID,
    )
    with pytest.raises(RuntimeError, match="before GUID echo"):
        client.send_voice(b"voice")


def test_udp_echo_timeout_is_fatal_and_manual_stop_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(radio_module, "UDP_READY_TIMEOUT_SECONDS", 0.02)
    tcp = FakeTcp([handshake_messages()])
    udp = FakeUdp([])
    client = make_client(tcp, udp, [])
    with pytest.raises(TimeoutError, match="GUID echo"):
        client.connect()
    assert client.state is SrsState.ERROR
    client.close()
    assert client.state is SrsState.STOPPED


def test_stop_during_udp_echo_wait_is_bounded() -> None:
    tcp = FakeTcp([handshake_messages()])
    events: list[tuple[str, dict[str, object]]] = []
    client: SrsRadioClient

    class StoppingUdp(FakeUdp):
        def recv(self, _size: int) -> bytes:
            client.stop_event.set()
            raise socket.timeout()

    udp = StoppingUdp([])
    client = make_client(tcp, udp, events)
    with pytest.raises(InterruptedError, match="stopped"):
        client.connect()
    assert client.state is SrsState.STOPPED
