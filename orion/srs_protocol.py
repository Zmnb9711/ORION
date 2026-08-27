"""Strict production SRS 2.4.x TCP and UDP wire primitives.

The wire facts are independently expressed from the SRS 2.4.0.0 protocol and
the field-proven ORION reference vectors. Production never imports the
reference tester or SRS assemblies.
"""

from __future__ import annotations

import base64
import json
import math
import re
import struct
import uuid
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

SRS_VERSION = "2.4.0.0"
GUID_LENGTH = 22
PACKET_HEADER_LENGTH = 6
FREQUENCY_SEGMENT_LENGTH = 10
FIXED_TAIL_LENGTH = 57
MIN_VOICE_PACKET_LENGTH = PACKET_HEADER_LENGTH + FIXED_TAIL_LENGTH + 1
MAX_TCP_LINE_BYTES = 1_048_576
AM = 0
FM = 1
DISABLED = 3
ENCRYPTION_OFF = 0
TARGET_FREQUENCY_HZ = 251_000_000.0
FREQUENCY_TOLERANCE_HZ = 500.0
SRS_MAX_RADIOS = 11
SRS_EXTERNAL_AUDIO_RADIO_INDEX = 1

_GUID_RE = re.compile(r"[A-Za-z0-9_-]{22}\Z")


class SrsProtocolError(ValueError):
    """Malformed or incompatible SRS wire data."""


class MessageType(IntEnum):
    UPDATE = 0
    PING = 1
    SYNC = 2
    RADIO_UPDATE = 3
    SERVER_SETTINGS = 4
    CLIENT_DISCONNECT = 5
    VERSION_MISMATCH = 6
    EXTERNAL_AWACS_MODE_PASSWORD = 7
    EXTERNAL_AWACS_MODE_DISCONNECT = 8
    GATEWAY_CLIENT_FULL_UPDATE = 9
    GATEWAY_CLIENT_METADATA_UPDATE = 10
    GATEWAY_CLIENT_DISCONNECT = 11


@dataclass(frozen=True, slots=True)
class Frequency:
    hz: float
    modulation: int
    encryption: int = ENCRYPTION_OFF


@dataclass(frozen=True, slots=True)
class SrsRadioState:
    frequency_hz: float = TARGET_FREQUENCY_HZ
    modulation: int = AM
    unit_id: int = 100_000

    def __post_init__(self) -> None:
        _validate_frequency(Frequency(self.frequency_hz, self.modulation))
        if not 0 <= self.unit_id <= 0xFFFFFFFF:
            raise SrsProtocolError("SRS UnitID is outside uint32 range.")


@dataclass(frozen=True, slots=True)
class VoicePacket:
    audio: bytes
    frequencies: tuple[Frequency, ...]
    unit_id: int
    packet_id: int
    retransmission_count: int
    original_client_guid: str
    current_sender_guid: str


def generate_client_guid() -> str:
    value = base64.urlsafe_b64encode(uuid.uuid4().bytes).decode("ascii").rstrip("=")
    if len(value) != GUID_LENGTH:
        raise RuntimeError("Generated SRS ClientGuid has an unexpected length.")
    return value


def validate_guid(value: str, field: str = "ClientGuid") -> bytes:
    if not _GUID_RE.fullmatch(value):
        raise SrsProtocolError(f"{field} must be exactly 22 URL-safe ASCII characters.")
    return value.encode("ascii")


def mask_guid(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _validate_frequency(item: Frequency) -> None:
    if not math.isfinite(item.hz) or item.hz <= 0:
        raise SrsProtocolError("Frequency must be finite and positive.")
    if not 0 <= item.modulation <= 7:
        raise SrsProtocolError("Malformed SRS modulation value.")
    if not 0 <= item.encryption <= 255:
        raise SrsProtocolError("Malformed SRS encryption value.")


def encode_voice_packet(packet: VoicePacket) -> bytes:
    audio_length = len(packet.audio)
    if not 0 < audio_length <= 0xFFFF:
        raise SrsProtocolError("Opus audio length must be in the uint16 range.")
    if not packet.frequencies:
        raise SrsProtocolError("A voice packet requires at least one frequency.")
    frequency_length = len(packet.frequencies) * FREQUENCY_SEGMENT_LENGTH
    total_length = PACKET_HEADER_LENGTH + audio_length + frequency_length + FIXED_TAIL_LENGTH
    if frequency_length > 0xFFFF or total_length > 0xFFFF:
        raise SrsProtocolError("SRS voice packet exceeds the uint16 packet limit.")
    if not 0 <= packet.unit_id <= 0xFFFFFFFF:
        raise SrsProtocolError("UnitID is outside uint32 range.")
    if not 0 <= packet.packet_id <= 0xFFFFFFFFFFFFFFFF:
        raise SrsProtocolError("PacketID is outside uint64 range.")
    if not 0 <= packet.retransmission_count <= 255:
        raise SrsProtocolError("Retransmission count is outside byte range.")

    original = validate_guid(packet.original_client_guid, "OriginalClientGuid")
    current = validate_guid(packet.current_sender_guid, "current/final Guid")
    encoded = bytearray(struct.pack("<HHH", total_length, audio_length, frequency_length))
    encoded.extend(packet.audio)
    for item in packet.frequencies:
        _validate_frequency(item)
        encoded.extend(struct.pack("<dBB", item.hz, item.modulation, item.encryption))
    encoded.extend(struct.pack("<IQB", packet.unit_id, packet.packet_id, packet.retransmission_count))
    encoded.extend(original)
    encoded.extend(current)
    if len(encoded) != total_length:
        raise AssertionError("SRS packet encoder length invariant failed.")
    return bytes(encoded)


def decode_voice_packet(datagram: bytes) -> VoicePacket:
    if len(datagram) < MIN_VOICE_PACKET_LENGTH:
        raise SrsProtocolError("Datagram is shorter than the minimum SRS voice packet.")
    declared_total, audio_length, frequency_length = struct.unpack_from("<HHH", datagram, 0)
    if declared_total != len(datagram):
        raise SrsProtocolError("Declared packet length does not match datagram length.")
    if audio_length <= 0:
        raise SrsProtocolError("SRS voice packet has no Opus audio.")
    if frequency_length <= 0 or frequency_length % FREQUENCY_SEGMENT_LENGTH:
        raise SrsProtocolError("Frequency segment length is structurally invalid.")

    audio_end = PACKET_HEADER_LENGTH + audio_length
    frequency_end = audio_end + frequency_length
    expected_end = frequency_end + FIXED_TAIL_LENGTH
    if audio_end > len(datagram) or frequency_end > len(datagram) or expected_end != len(datagram):
        raise SrsProtocolError("SRS packet segments overlap or have impossible offsets.")

    frequencies: list[Frequency] = []
    for offset in range(audio_end, frequency_end, FREQUENCY_SEGMENT_LENGTH):
        hz, modulation, encryption = struct.unpack_from("<dBB", datagram, offset)
        item = Frequency(hz, modulation, encryption)
        _validate_frequency(item)
        frequencies.append(item)

    unit_id, packet_id, retransmission_count = struct.unpack_from("<IQB", datagram, frequency_end)
    guid_offset = frequency_end + 13
    original_raw = datagram[guid_offset : guid_offset + GUID_LENGTH]
    current_raw = datagram[guid_offset + GUID_LENGTH : guid_offset + 2 * GUID_LENGTH]
    if len(original_raw) != GUID_LENGTH or len(current_raw) != GUID_LENGTH:
        raise SrsProtocolError("SRS GUID tail is incomplete.")
    try:
        original = original_raw.decode("ascii")
        current = current_raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise SrsProtocolError("SRS GUID tail is not ASCII.") from exc
    validate_guid(original, "OriginalClientGuid")
    validate_guid(current, "current/final Guid")
    return VoicePacket(
        audio=datagram[PACKET_HEADER_LENGTH:audio_end],
        frequencies=tuple(frequencies),
        unit_id=unit_id,
        packet_id=packet_id,
        retransmission_count=retransmission_count,
        original_client_guid=original,
        current_sender_guid=current,
    )


def is_target_frequency(
    packet: VoicePacket,
    frequency_hz: float = TARGET_FREQUENCY_HZ,
    modulation: int = AM,
) -> bool:
    return any(
        abs(item.hz - frequency_hz) < FREQUENCY_TOLERANCE_HZ
        and item.modulation == modulation
        and item.encryption == ENCRYPTION_OFF
        for item in packet.frequencies
    )


class JsonLineParser:
    """Bounded newline-delimited JSON parser supporting arbitrary recv splits."""

    def __init__(self, max_line_bytes: int = MAX_TCP_LINE_BYTES) -> None:
        self._buffer = bytearray()
        self.max_line_bytes = max_line_bytes

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        if not data:
            return []
        self._buffer.extend(data)
        if len(self._buffer) > self.max_line_bytes and b"\n" not in self._buffer:
            self._buffer.clear()
            raise SrsProtocolError("SRS TCP JSON line exceeds the configured limit.")
        messages: list[dict[str, Any]] = []
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                break
            raw = bytes(self._buffer[:newline]).rstrip(b"\r")
            del self._buffer[: newline + 1]
            if not raw:
                continue
            if len(raw) > self.max_line_bytes:
                raise SrsProtocolError("SRS TCP JSON line exceeds the configured limit.")
            try:
                decoded = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SrsProtocolError("Malformed UTF-8 JSON from SRS TCP transport.") from exc
            if not isinstance(decoded, dict):
                raise SrsProtocolError("SRS TCP message root must be an object.")
            messages.append(decoded)
        return messages

    def eof(self) -> None:
        if self._buffer.strip():
            self._buffer.clear()
            raise SrsProtocolError("SRS TCP EOF occurred inside a JSON message.")


def encode_tcp_message(message: dict[str, object]) -> bytes:
    payload = dict(message)
    payload["Version"] = SRS_VERSION
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def base_client(client_guid: str, name: str, coalition: int = 0) -> dict[str, object]:
    validate_guid(client_guid)
    return {
        "ClientGuid": client_guid,
        "Name": name.strip() or "ORION SRS",
        "Coalition": coalition,
        "AllowRecord": False,
        "Seat": 0,
        "LatLngPosition": {"lat": 0.0, "lng": 0.0, "alt": 0.0},
        "Gateway": False,
        "DISEntityId": -1,
        "GatewayClient": False,
    }


def _disabled_radio() -> dict[str, object]:
    return {
        "enc": False,
        "encKey": 0,
        "freq": 1.0,
        "modulation": DISABLED,
        "retransmit": False,
        "secFreq": 1.0,
        "IntercomUnitId": 0,
        "Model": "",
        "Name": "",
    }


def build_radio_info(state: SrsRadioState) -> dict[str, object]:
    radios = [_disabled_radio() for _ in range(SRS_MAX_RADIOS)]
    radios[SRS_EXTERNAL_AUDIO_RADIO_INDEX].update(
        {"freq": state.frequency_hz, "modulation": state.modulation}
    )
    return {
        "ambient": {"vol": 0.0, "abType": ""},
        "iff": {
            "control": 2,
            "mic": -1,
            "mode1": -1,
            "mode2": -1,
            "mode3": -1,
            "mode4": False,
            "status": 0,
        },
        "radios": radios,
        "unit": "",
        "unitId": state.unit_id,
    }


def radio_info_matches_state(value: object, state: SrsRadioState) -> bool:
    if not isinstance(value, dict):
        return False
    expected = build_radio_info(state)
    return all(value.get(key) == expected[key] for key in expected)


def build_sync_message(
    client_guid: str,
    name: str,
    *,
    radio_state: SrsRadioState | None = None,
) -> dict[str, object]:
    client = base_client(client_guid, name)
    client["RadioInfo"] = build_radio_info(radio_state or SrsRadioState())
    return {"Client": client, "MsgType": int(MessageType.SYNC)}


def build_eam_password_message(client_guid: str, name: str, password: str) -> dict[str, object]:
    return {
        "Client": base_client(client_guid, name),
        "ExternalAWACSModePassword": password,
        "MsgType": int(MessageType.EXTERNAL_AWACS_MODE_PASSWORD),
    }


def build_eam_disconnect_message(client_guid: str, name: str, coalition: int) -> dict[str, object]:
    return {
        "Client": base_client(client_guid, name, coalition),
        "MsgType": int(MessageType.EXTERNAL_AWACS_MODE_DISCONNECT),
    }


def build_ping_message(client_guid: str, name: str, coalition: int) -> dict[str, object]:
    return {
        "Client": base_client(client_guid, name, coalition),
        "MsgType": int(MessageType.PING),
    }


def build_radio_update_message(
    client_guid: str,
    name: str,
    coalition: int,
    frequency_hz: float,
    modulation: int = AM,
    unit_id: int = 100_000,
    *,
    radio_state: SrsRadioState | None = None,
) -> dict[str, object]:
    state = radio_state or SrsRadioState(frequency_hz, modulation, unit_id)
    client = base_client(client_guid, name, coalition)
    client["RadioInfo"] = build_radio_info(state)
    return {"Client": client, "MsgType": int(MessageType.RADIO_UPDATE)}


def compatible_server_version(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parts = tuple(int(item) for item in value.split("."))
    except ValueError:
        return False
    return len(parts) == 4 and parts[:2] == (2, 4)


def eam_enabled(settings: object) -> bool:
    if not isinstance(settings, dict):
        return False
    value = settings.get("EXTERNAL_AWACS_MODE")
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.strip().casefold() == "true"
