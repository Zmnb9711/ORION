from __future__ import annotations

import copy
import json
import socket
import threading
from typing import Any

import pytest

from srs_protocol import MessageType, SrsRadioState, build_radio_info
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


class Srs240StatefulFakeTcp(FakeTcp):
    """Minimal SRS 2.4 registry with its null-sensitive radio update behavior."""

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
                + line(
                    {
                        "MsgType": int(MessageType.RADIO_UPDATE),
                        "Version": "2.4.0.0",
                        "Client": copy.deepcopy(self.registry),
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
            # SRS 2.4.0 calls client.RadioInfo.Equals(...) before assignment.
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

    def route_human_voice(
        self,
        udp: FakeUdp,
        datagram: bytes,
        *,
        frequency_hz: float,
        modulation: int,
        encryption: int,
    ) -> bool:
        if self.registry is None:
            return False
        radio_info = self.registry.get("RadioInfo")
        if not isinstance(radio_info, dict):
            return False
        radios = radio_info.get("radios")
        if not isinstance(radios, list):
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
    ) + line(
        {
            "MsgType": int(MessageType.RADIO_UPDATE),
            "Version": version,
            "Client": {
                "ClientGuid": GUID,
                "Name": "ORION YANDEX TEST",
                "Coalition": coalition,
                "RadioInfo": build_radio_info(SrsRadioState()),
            },
        }
    )


def make_client(
    tcp: FakeTcp,
    udp: FakeUdp,
    events: list[tuple[str, dict[str, object]]],
    voice_callback: Any = None,
) -> SrsRadioClient:
    return SrsRadioClient(
        SrsRadioConfig(eam_password="test-password"),
        voice_callback or (lambda _datagram: None),
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
    assert client.radio_registered is True
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
    with pytest.raises(RuntimeError, match="before radio and UDP"):
        client.send_voice(b"voice")


def test_srs240_stateful_registry_does_not_hit_null_sensitive_radio_update() -> None:
    tcp = Srs240StatefulFakeTcp()
    udp = FakeUdp([GUID.encode()])
    client = make_client(tcp, udp, [])
    client.connect()
    sent = decoded_sent(tcp)
    initial = sent[0]["Client"]["RadioInfo"]
    subsequent = sent[2]["Client"]["RadioInfo"]
    assert initial is not None
    assert initial == subsequent
    assert tcp.radio_update_exception is False
    assert tcp.registry is not None
    assert tcp.registry["RadioInfo"] == initial
    client.close()


def test_guid_echo_cannot_bypass_missing_server_radio_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(radio_module, "HANDSHAKE_TIMEOUT_SECONDS", 0.02)
    tcp = Srs240StatefulFakeTcp(broadcast_radio_update=False)
    udp = FakeUdp([GUID.encode()])
    client = make_client(tcp, udp, [])
    with pytest.raises(TimeoutError, match="TCP handshake"):
        client.connect()
    assert client.radio_registered is False
    assert not client.ready_event.is_set()
    assert udp.sent == []
    client.close()


def test_srs240_routing_delivers_251_am_only_with_valid_server_radio_state() -> None:
    delivered: list[bytes] = []
    received = threading.Event()

    def on_voice(datagram: bytes) -> None:
        delivered.append(datagram)
        received.set()

    tcp = Srs240StatefulFakeTcp()
    udp = FakeUdp([GUID.encode()])
    client = make_client(tcp, udp, [], on_voice)
    client.connect()
    assert tcp.route_human_voice(
        udp,
        b"human-251-am",
        frequency_hz=251_000_000.0,
        modulation=0,
        encryption=0,
    )
    assert received.wait(1.0)
    assert delivered == [b"human-251-am"]
    assert tcp.registry is not None
    tcp.registry["RadioInfo"] = None
    assert not tcp.route_human_voice(
        udp,
        b"must-not-route",
        frequency_hz=251_000_000.0,
        modulation=0,
        encryption=0,
    )
    assert delivered == [b"human-251-am"]
    client.close()


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
