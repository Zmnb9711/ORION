from __future__ import annotations

import base64
import queue
import threading
import time
from typing import Any

import pytest

import yandex_reference_core as core
from srs_protocol import Frequency, VoicePacket, decode_voice_packet, encode_voice_packet
from srs_radio_client import SrsRadioConfig
from srs_transmission import TransmissionTracker
from yandex_srs_session import (
    RESPONSE_MAX_BYTES,
    ResponseBuffer,
    TRAILING_SILENCE_BLOCKS,
    YANDEX_BLOCK_BYTES,
    SrsSessionConfig,
    PreparedResponse,
    YandexSrsReferenceSession,
)

OWN = "OOOOOOOOOOOOOOOOOOOOOO"
HUMAN = "HHHHHHHHHHHHHHHHHHHHHH"


def config() -> SrsSessionConfig:
    return SrsSessionConfig(
        api_key="seeded-api-secret",
        folder_id="folder-id",
        srs=SrsRadioConfig(eam_password="seeded-eam-secret"),
    )


def session(clock: Any | None = None) -> YandexSrsReferenceSession:
    return YandexSrsReferenceSession(config(), lambda *_: None, clock=clock or (lambda: 1.0))


def audio_delta(response_id: str, pcm: bytes) -> dict[str, object]:
    return {
        "type": "response.output_audio.delta",
        "response_id": response_id,
        "delta": base64.b64encode(pcm).decode(),
    }


def test_srs_constructor_and_event_flow_do_not_touch_portaudio(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("PortAudio must not be used by SRS mode")

    monkeypatch.setattr(core, "list_audio_devices", forbidden)
    monkeypatch.setattr(core, "validate_audio_format", forbidden)
    monkeypatch.setattr(core.sd, "RawInputStream", forbidden)
    monkeypatch.setattr(core.sd, "RawOutputStream", forbidden)
    item = session()
    item.handle_event({"type": "session.created", "session": {"id": "session-1"}})
    item.handle_event({"type": "session.updated"})
    assert item.session_ready.is_set()


def test_provider_response_is_buffered_until_audio_done_and_response_done() -> None:
    item = session()
    pcm = bytes(1764 * 3)
    item.handle_event({"type": "response.created", "response": {"id": "r1"}})
    item.handle_event(audio_delta("r1", pcm[:2000]))
    item.handle_event(audio_delta("r1", pcm[2000:]))
    assert item.tx_queue.empty()
    item.handle_event({"type": "response.output_audio.done", "response_id": "r1"})
    assert item.tx_queue.empty()
    item.handle_event({"type": "response.done", "response": {"id": "r1", "status": "completed"}})
    prepared = item.tx_queue.get_nowait()
    assert prepared.response_id == "r1"  # type: ignore[union-attr]
    assert prepared.pcm44 == pcm  # type: ignore[union-attr]
    assert item.responses["r1"].queued


@pytest.mark.parametrize("status", ["cancelled", "failed", "incomplete"])
def test_non_completed_provider_response_is_never_transmitted(status: str) -> None:
    item = session()
    item.handle_event({"type": "response.created", "response": {"id": "bad"}})
    item.handle_event(audio_delta("bad", bytes(100)))
    item.handle_event({"type": "response.output_audio.done", "response_id": "bad"})
    item.handle_event({"type": "response.done", "response": {"id": "bad", "status": status}})
    assert item.tx_queue.empty()
    assert item.responses["bad"].dropped_reason


def test_response_buffer_limit_drops_whole_response() -> None:
    item = session()
    item.handle_event({"type": "response.created", "response": {"id": "large"}})
    item.handle_event(audio_delta("large", bytes(RESPONSE_MAX_BYTES)))
    item.handle_event(audio_delta("large", b"\x00\x00"))
    response = item.responses["large"]
    assert response.dropped_reason == "radio response buffer limit exceeded"
    assert len(response.pcm) == 0
    item.handle_event({"type": "response.output_audio.done", "response_id": "large"})
    item.handle_event({"type": "response.done", "response": {"id": "large", "status": "completed"}})
    assert item.tx_queue.empty()


class FakeDecoder:
    def decode(self, _packet: bytes) -> bytes:
        return b"\x01\x00" * 640


class FakeResampler:
    def __init__(self) -> None:
        self.calls: list[bytes] = []

    def process(self, pcm: bytes, **_kwargs: object) -> bytes:
        self.calls.append(pcm)
        return b"\x02\x00" * 1000


class FakeRadio:
    client_guid = OWN
    clients = {HUMAN: {"Name": "Human One"}}


class FakeClock:
    def __init__(self) -> None:
        self.now = 10.0

    def __call__(self) -> float:
        return self.now


def test_srs_rx_reaches_stateful_resampler_exact_blocks_and_bounded_trailing_silence() -> None:
    clock = FakeClock()
    item = session(clock)
    item.radio = FakeRadio()  # type: ignore[assignment]
    item.decoder = FakeDecoder()  # type: ignore[assignment]
    resampler = FakeResampler()
    item.rx_resampler = resampler  # type: ignore[assignment]
    item.tracker = TransmissionTracker(OWN, 251_000_000.0, 0)
    packet = VoicePacket(
        b"opus",
        (Frequency(251_000_000.0, 0, 0),),
        1,
        1,
        0,
        HUMAN,
        HUMAN,
    )
    item._on_radio_datagram(encode_voice_packet(packet))
    assert len(resampler.calls) == 1
    assert item.input_blocks.qsize() == 1
    assert len(item.input_blocks.get_nowait()) == YANDEX_BLOCK_BYTES
    clock.now = 10.4
    item._poll_rx_end()
    assert item.input_blocks.qsize() == TRAILING_SILENCE_BLOCKS + 1
    blocks = [item.input_blocks.get_nowait() for _ in range(TRAILING_SILENCE_BLOCKS + 1)]
    assert all(len(block) == YANDEX_BLOCK_BYTES for block in blocks)
    assert blocks[-1] == bytes(YANDEX_BLOCK_BYTES)
    before = item.trailing_silence_blocks
    clock.now = 20.0
    item._poll_rx_end()
    assert item.trailing_silence_blocks == before


def test_stop_discards_queued_untransmitted_response() -> None:
    item = session()
    item.handle_event({"type": "response.created", "response": {"id": "queued"}})
    item.handle_event(audio_delta("queued", bytes(100)))
    item.handle_event({"type": "response.output_audio.done", "response_id": "queued"})
    item.handle_event({"type": "response.done", "response": {"id": "queued", "status": "completed"}})
    item.stop()
    assert item.responses["queued"].dropped_reason == "manual stop before radio TX"
    assert len(item.responses["queued"].pcm) == 0


def test_manual_stop_after_error_transitions_visible_status_to_stopped() -> None:
    statuses: list[str] = []
    item = YandexSrsReferenceSession(
        config(),
        lambda event, fields: statuses.append(str(fields.get("value")))
        if event == "status"
        else None,
        clock=lambda: 1.0,
    )
    item._terminal_error("SRS SESSION ERROR", RuntimeError("synthetic"))
    assert statuses[-1] == "ERROR"
    item.stop()
    assert statuses[-1] == "STOPPED"


def test_diagnostics_redact_both_secrets_guid_audio_and_transcript() -> None:
    item = session()
    item.handle_event(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "i1",
            "transcript": "PRIVATE TRANSCRIPT SENTINEL",
        }
    )
    item._emit(
        "synthetic",
        api_key="seeded-api-secret",
        eam_password="seeded-eam-secret",
        authorization="Api-Key seeded-api-secret",
    )
    text = item.diagnostic_text()
    assert "seeded-api-secret" not in text
    assert "seeded-eam-secret" not in text
    assert "PRIVATE TRANSCRIPT SENTINEL" not in text
    assert OWN not in text
    assert "transcript_persisted" in text


class FakeTxRadio:
    client_guid = OWN

    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def send_voice(self, datagram: bytes) -> None:
        self.sent.append(datagram)


class FakeEncoder:
    def encode(self, _pcm: bytes) -> bytes:
        return b"opus"


class FakeTxResampler:
    def __init__(self) -> None:
        self.reset_count = 0

    def process(self, _pcm: bytes, *, end_of_input: bool) -> bytes:
        assert end_of_input
        return bytes(1280 * 2 + 200)

    def reset(self) -> None:
        self.reset_count += 1


def test_completed_response_tx_has_monotonic_ids_exact_channel_guids_and_one_padding() -> None:
    item = session(clock=time.monotonic)
    radio = FakeTxRadio()
    resampler = FakeTxResampler()
    item.radio = radio  # type: ignore[assignment]
    item.encoder = FakeEncoder()  # type: ignore[assignment]
    item.tx_resampler = resampler  # type: ignore[assignment]
    item.tracker = TransmissionTracker(OWN, 251_000_000.0, 0)
    item.responses["r"] = ResponseBuffer("r", 0.0)
    item.tx_queue.put(PreparedResponse("r", bytes(1764), 0.0))
    worker = threading.Thread(target=item._tx_worker)
    worker.start()
    item.tx_queue.put(item._tx_sentinel)
    worker.join(2)
    assert not worker.is_alive()
    decoded = [decode_voice_packet(datagram) for datagram in radio.sent]
    assert [packet.packet_id for packet in decoded] == [1, 2, 3]
    assert all(packet.original_client_guid == OWN for packet in decoded)
    assert all(packet.current_sender_guid == OWN for packet in decoded)
    assert all(packet.frequencies == (Frequency(251_000_000.0, 0, 0),) for packet in decoded)
    assert item.final_padding_samples == 540
    assert resampler.reset_count == 1
