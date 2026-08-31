"""Small PCM boundary used by the Yandex live session.

This intentionally models neither provider protocols nor a general voice
framework. It only carries provider-native PCM and response lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RealtimePcmFormat:
    sample_rate: int = 44_100
    channels: int = 1
    sample_width_bytes: int = 2


@dataclass(frozen=True, slots=True)
class RealtimeInputTransmissionStarted:
    """Provider-neutral metadata for the start of one transport transmission."""

    transmission_id: str


@dataclass(frozen=True, slots=True)
class RealtimeInputTransmissionCompleted:
    """Provider-neutral metadata; this is not a provider commit request."""

    transmission_id: str
    boundary: str = "transport_transmission_end"
    first_accepted_packet_timestamp: str | None = None
    last_accepted_packet_timestamp: str | None = None
    accepted_packet_count: int | None = None
    first_packet_id: int | None = None
    last_packet_id: int | None = None
    sequence_gap_count: int | None = None
    decode_error_count: int | None = None
    decoded_pcm_bytes: int | None = None
    padding_bytes: int | None = None
    framed_pcm_bytes: int | None = None
    packet_quiescence_completed_timestamp: str | None = None
    boundary_gap_ms: int | None = None


@dataclass(frozen=True, slots=True)
class RealtimeTranscriptSegment:
    """One immutable provider-finalized input transcription segment."""

    transcript: str
    turn_id: str | None
    event_id: str
    provider_item_id: str
    speech_stopped_at: float | None
    provider_audio_start_ms: int | None = None
    provider_audio_end_ms: int | None = None


@dataclass(frozen=True, slots=True)
class FinalizedUserUtterance:
    """One provider-native final correlated to one physical input transmission."""

    transmission_id: str
    transcript: str
    provider_id: str
    provider_session_id: str
    provider_final_index: int
    event_id: str
    provider_item_id: str
    finalized_at: float


class RealtimePcmEndpoint(Protocol):
    transport_id: str
    pcm_format: RealtimePcmFormat

    def start(self) -> None: ...

    def read_input(
        self, timeout: float = 0.1
    ) -> (
        bytes
        | RealtimeInputTransmissionStarted
        | RealtimeInputTransmissionCompleted
        | None
    ): ...

    def failure(self) -> BaseException | None: ...

    def input_speech_started(self) -> None: ...

    def response_started(self, response_id: str) -> None: ...

    def response_audio(self, response_id: str, pcm16le: bytes) -> None: ...

    def response_audio_done(self, response_id: str) -> None: ...

    def response_done(self, response_id: str, status: str) -> None: ...

    def stop(self) -> None: ...
