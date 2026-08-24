from __future__ import annotations

import json
import math
import struct

import pytest

from srs_protocol import (
    FIXED_TAIL_LENGTH,
    GUID_LENGTH,
    JsonLineParser,
    MessageType,
    Frequency,
    SrsProtocolError,
    VoicePacket,
    build_eam_password_message,
    build_radio_update_message,
    build_sync_message,
    compatible_server_version,
    decode_voice_packet,
    eam_enabled,
    encode_tcp_message,
    encode_voice_packet,
    generate_client_guid,
)

GUID = "ufYS_WlLVkmFPjqCgxz6GA"


def packet(frequencies: tuple[Frequency, ...] | None = None) -> VoicePacket:
    return VoicePacket(
        audio=bytes(range(6)),
        frequencies=frequencies or (Frequency(100.0, 4, 0),),
        unit_id=1,
        packet_id=1,
        retransmission_count=4,
        original_client_guid=GUID,
        current_sender_guid=GUID,
    )


def test_official_79_byte_golden_vector_and_fixed_tail() -> None:
    expected = bytes(
        [79, 0, 6, 0, 10, 0, 0, 1, 2, 3, 4, 5]
        + [0, 0, 0, 0, 0, 0, 89, 64, 4, 0]
        + [1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 4]
        + list(GUID.encode("ascii"))
        + list(GUID.encode("ascii"))
    )
    encoded = encode_voice_packet(packet())
    assert len(encoded) == 79
    assert FIXED_TAIL_LENGTH == 57
    assert encoded == expected
    assert encode_voice_packet(decode_voice_packet(expected)) == expected


def test_official_99_byte_multiple_frequency_golden_vector() -> None:
    frequencies = (
        Frequency(251_000_000.0, 0, 0),
        Frequency(30_000_000.0, 1, 0),
        Frequency(251_000_000.0, 0, 1),
    )
    value = packet(frequencies)
    value = VoicePacket(
        value.audio,
        value.frequencies,
        value.unit_id,
        value.packet_id,
        254,
        value.original_client_guid,
        value.current_sender_guid,
    )
    encoded = encode_voice_packet(value)
    assert len(encoded) == 99
    assert encoded[:6] == bytes([99, 0, 6, 0, 30, 0])
    assert encoded[12:20] == struct.pack("<d", 251_000_000.0)
    assert encoded[22:30] == struct.pack("<d", 30_000_000.0)
    assert encoded[32:40] == struct.pack("<d", 251_000_000.0)
    decoded = decode_voice_packet(encoded)
    assert decoded == value
    assert encode_voice_packet(decoded) == encoded


@pytest.mark.parametrize(
    "mutator,match",
    [
        (lambda data: data[:20], "shorter"),
        (lambda data: bytes([80, 0]) + data[2:], "Declared"),
        (lambda data: data[:4] + bytes([11, 0]) + data[6:], "Frequency"),
        (lambda data: data[:4] + bytes([20, 0]) + data[6:], "offset"),
        (lambda data: data[:-1], "Declared"),
    ],
)
def test_strict_decoder_rejects_structural_corruption(mutator: object, match: str) -> None:
    encoded = encode_voice_packet(packet())
    with pytest.raises(SrsProtocolError, match=match):
        decode_voice_packet(mutator(encoded))  # type: ignore[operator]


def test_strict_decoder_rejects_invalid_frequency_modulation_and_guid() -> None:
    encoded = bytearray(encode_voice_packet(packet()))
    encoded[20] = 255
    with pytest.raises(SrsProtocolError, match="modulation"):
        decode_voice_packet(bytes(encoded))
    encoded = bytearray(encode_voice_packet(packet()))
    encoded[-1] = 0xFF
    with pytest.raises(SrsProtocolError, match="ASCII"):
        decode_voice_packet(bytes(encoded))
    with pytest.raises(SrsProtocolError, match="finite"):
        encode_voice_packet(packet((Frequency(math.nan, 0, 0),)))


def test_guid_semantics_keep_original_and_current_sender_distinct() -> None:
    relay = "AAAAAAAAAAAAAAAAAAAAAA"
    value = packet()
    relayed = VoicePacket(
        value.audio,
        value.frequencies,
        value.unit_id,
        value.packet_id,
        value.retransmission_count,
        GUID,
        relay,
    )
    decoded = decode_voice_packet(encode_voice_packet(relayed))
    assert decoded.original_client_guid == GUID
    assert decoded.current_sender_guid == relay


def test_json_line_parser_fragmentation_coalescing_malformed_and_eof() -> None:
    parser = JsonLineParser()
    assert parser.feed(b'{"Msg') == []
    messages = parser.feed(b'Type":2}\n{"MsgType":1}\n')
    assert [item["MsgType"] for item in messages] == [2, 1]
    with pytest.raises(SrsProtocolError, match="Malformed"):
        JsonLineParser().feed(b"{bad}\n")
    partial = JsonLineParser()
    partial.feed(b'{"MsgType"')
    with pytest.raises(SrsProtocolError, match="EOF"):
        partial.eof()


def test_tcp_builders_use_current_numeric_schema_and_never_serialize_password_elsewhere() -> None:
    sync = build_sync_message(GUID, "BOT")
    assert sync["MsgType"] == int(MessageType.SYNC)
    assert sync["Client"]["ClientGuid"] == GUID  # type: ignore[index]
    eam = build_eam_password_message(GUID, "BOT", "secret-eam")
    assert eam["ExternalAWACSModePassword"] == "secret-eam"
    encoded = json.loads(encode_tcp_message(eam))
    assert encoded["Version"] == "2.4.0.0"
    radio = build_radio_update_message(GUID, "BOT", 2, 251_000_000.0)
    assert radio["MsgType"] == int(MessageType.RADIO_UPDATE)
    radios = radio["Client"]["RadioInfo"]["radios"]  # type: ignore[index]
    assert len(radios) == 1
    assert radios[0]["freq"] == 251_000_000.0
    assert radios[0]["modulation"] == 0
    assert radios[0]["encKey"] == 0


def test_version_eam_and_generated_guid_policy() -> None:
    assert compatible_server_version("2.4.0.0")
    assert compatible_server_version("2.4.9.1")
    assert not compatible_server_version("2.3.9.9")
    assert not compatible_server_version("3.0.0.0")
    assert not compatible_server_version("garbage")
    assert eam_enabled({"EXTERNAL_AWACS_MODE": "true"})
    assert eam_enabled({"EXTERNAL_AWACS_MODE": True})
    assert not eam_enabled({"EXTERNAL_AWACS_MODE": "false"})
    first, second = generate_client_guid(), generate_client_guid()
    assert len(first) == len(second) == GUID_LENGTH
    assert first != second
