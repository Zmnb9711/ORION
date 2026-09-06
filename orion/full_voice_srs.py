"""Controlled physical RX and optional streamed TX on the proven SRS endpoint."""

from __future__ import annotations

import queue
import threading
import time
from typing import Iterator
from uuid import UUID

from orion.bounded_radio_stream import BoundedPcmStream
from orion.full_voice_capture import PhysicalRadioTurn, RadioTurnEvent, RadioTurnEventKind
from orion.srs_protocol import Frequency, VoicePacket, decode_voice_packet, encode_voice_packet
from orion.srs_radio_adapter import SrsTxCompletion
from orion.srs_transmission import PacketDecision, TxPacer
from orion.srs_tx_state import SrsTxStateListener, SrsTxStateListenerStatus
from orion.yandex_srs_live_core import SrsYandexPcmEndpoint


class FullVoiceSrsEndpoint(SrsYandexPcmEndpoint):
    """No Realtime callbacks or packet-gap EOU. Only the dedicated host uses this."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.turn_events: queue.Queue[RadioTurnEvent] = queue.Queue(maxsize=128)
        self.capture = PhysicalRadioTurn(self._emit_turn, self._abort_turn)
        self.expected_origin: str | None = None
        self.tx_marks: dict[str, float | int] = {}
        self.response_valid_until: float | None = None
        self._stream: BoundedPcmStream | None = None
        self._stream_tx_lock = threading.Lock()
        self.listener = SrsTxStateListener(
            self.stop_event,
            lambda snapshot, _previous: self.capture.snapshot(snapshot),
            self._listener_status,
            lambda event, fields: self.diagnostics.record(event, **fields),
        )

    def arm_physical_capture(self) -> None:
        # Controlled topology: exactly one non-bot server client. Never choose
        # the first arbitrary packet as the human identity.
        peers = [key for key in self.radio.clients if key != self.radio.client_guid]
        if len(peers) != 1:
            raise RuntimeError("controlled_srs_topology_requires_one_human_client")
        self.expected_origin = peers[0]
        self.listener.start()

    def _listener_status(self, status, _age) -> None:
        if status in {SrsTxStateListenerStatus.STALE, SrsTxStateListenerStatus.PORT_UNAVAILABLE}:
            self._abort_turn("physical_evidence_unavailable")

    def _abort_turn(self, code: str) -> None:
        if self._stream is not None:
            self._stream.abort(code)
        self._set_failure(RuntimeError(code))

    def _emit_turn(self, event: RadioTurnEvent) -> None:
        if event.kind is RadioTurnEventKind.END:
            with self._lock:
                self.tracker.complete_active()
        try:
            self.turn_events.put_nowait(event)
        except queue.Full:
            self._abort_turn("physical_event_queue_overflow")

    def _on_radio_datagram(self, datagram: bytes) -> None:
        try:
            packet = decode_voice_packet(datagram)
        except Exception:
            self._abort_turn("malformed_srs_packet")
            return
        now = self.clock()
        with self._lock:
            decision = self.tracker.accept(packet, now, expire_on_quiescence=False)
            if decision in {PacketDecision.SELF, PacketDecision.WRONG_CHANNEL, PacketDecision.DUPLICATE, PacketDecision.OUT_OF_ORDER}:
                return
            if decision is not PacketDecision.ACCEPTED or packet.original_client_guid != self.expected_origin:
                self._abort_turn("srs_collision_or_unexpected_origin")
                return
            try:
                decoded = self.decoder.decode(packet.audio)
            except Exception:
                self._abort_turn("srs_opus_decode_failed")
                return
            self.decoded_samples += len(decoded) // 2
        self.capture.pcm(decoded, now)

    def _boundary_worker(self) -> None:
        while not self.stop_event.wait(.02):
            self.capture.tick(self.clock())
            self.listener.check_liveness()

    def release_turn(self, identity: UUID) -> None:
        self.capture.release(identity)

    def transmit_srs_stream(self, tx_id: str, stream: BoundedPcmStream, timeout_s: float) -> SrsTxCompletion:
        if not self._stream_tx_lock.acquire(blocking=False):
            raise RuntimeError("stream_tx_busy")
        queued = self.clock()
        first: float | None = None
        frames = 0
        self._stream = stream
        self.tx_marks = {"radio_started": queued}
        try:
            stream.wait_prebuffer(timeout=min(10.0, timeout_s))
            while True:
                if self.stop_event.is_set() or self.failure() is not None:
                    raise RuntimeError("stream_tx_unavailable")
                if not self.capture.tx_permitted():
                    raise RuntimeError("physical_turn_not_closed")
                with self._lock:
                    if self.tracker.channel_clear(self.clock()):
                        self.tracker.bot_tx_active = True
                        break
                if self.clock() - queued >= timeout_s:
                    raise TimeoutError("stream_tx_guard_timeout")
                self.stop_event.wait(.01)

            def encoded() -> Iterator[bytes]:
                accumulated = bytearray()
                underruns = 0
                ended = False
                while True:
                    if self.clock() - queued >= timeout_s:
                        raise TimeoutError("stream_tx_timeout")
                    if not self.capture.tx_permitted():
                        raise RuntimeError("physical_overlap_during_tx")
                    while len(accumulated) < 1280 and not ended:
                        pcm44, ended = stream.read(3528)
                        if pcm44 or ended:
                            accumulated.extend(self.tx_resampler.process(pcm44, end_of_input=ended))
                        else:
                            break
                    if len(accumulated) >= 1280:
                        frame = bytes(accumulated[:1280]); del accumulated[:1280]
                        underruns = 0
                    elif ended:
                        if not accumulated:
                            return
                        frame = bytes(accumulated) + bytes(1280 - len(accumulated))
                        accumulated.clear()
                    else:
                        underruns += 1
                        if underruns > 3:
                            raise RuntimeError("stream_underrun_bound")
                        self.tx_marks["underrun_frames"] = int(self.tx_marks.get("underrun_frames", 0)) + 1
                        frame = bytes(1280)
                    yield self.encoder.encode(frame)

            def send_frame(opus: bytes, _sent_at: float) -> None:
                nonlocal first, frames
                if not self.capture.tx_permitted() or self.stop_event.is_set():
                    raise RuntimeError("stream_tx_cancelled")
                if first is None and self.response_valid_until is not None and self.clock() > self.response_valid_until:
                    raise RuntimeError("ownship_expired_before_first_tx")
                packet = VoicePacket(
                    audio=opus, frequencies=(Frequency(self.config.frequency_hz, self.config.modulation),),
                    unit_id=self.config.unit_id, packet_id=self.packet_id, retransmission_count=0,
                    original_client_guid=self.radio.client_guid, current_sender_guid=self.radio.client_guid,
                )
                self.radio.send_voice(encode_voice_packet(packet))
                self.packet_id += 1
                frames += 1
                if first is None:
                    first = self.clock()
                    self.tx_marks["radio_first_frame"] = first
                    self.diagnostics.record("srs_tx_started", response_id=tx_id)

            report = TxPacer(clock=self.clock).send(encoded(), send_frame, self.stop_event, streaming=True)
            if self.stop_event.is_set() or first is None or not report.sent_frames:
                raise RuntimeError("stream_tx_incomplete")
            # Last frame's audible duration precedes downstream release.
            if self.stop_event.wait(.04):
                raise RuntimeError("stream_tx_cancelled")
            completed = self.clock()
            self.tx_marks.update(radio_completed=completed, frames=frames)
            self.tx_transmissions += 1
            self.tx_frames += frames
            self.diagnostics.record("tx_completed", response_id=tx_id, frames=frames)
            return SrsTxCompletion((first - queued) * 1000, (completed - queued) * 1000, frames, (completed - first) * 1000)
        except Exception:
            stream.abort("stream_tx_failed")
            raise
        finally:
            with self._lock:
                self.tracker.bot_tx_active = False
            self.tx_resampler.reset()
            self._stream = None
            self._stream_tx_lock.release()

    def stop(self) -> None:
        if self._stream:
            self._stream.abort()
        self.listener.stop()
        super().stop()
