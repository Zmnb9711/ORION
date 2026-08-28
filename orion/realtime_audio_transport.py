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
class RealtimeInputCommit:
    """Transport-owned end of one complete input utterance."""

    boundary: str = "transport_transmission_end"


class RealtimePcmEndpoint(Protocol):
    transport_id: str
    pcm_format: RealtimePcmFormat

    def start(self) -> None: ...

    def read_input(
        self, timeout: float = 0.1
    ) -> bytes | RealtimeInputCommit | None: ...

    def failure(self) -> BaseException | None: ...

    def input_speech_started(self) -> None: ...

    def response_started(self, response_id: str) -> None: ...

    def response_audio(self, response_id: str, pcm16le: bytes) -> None: ...

    def response_audio_done(self, response_id: str) -> None: ...

    def response_done(self, response_id: str, status: str) -> None: ...

    def stop(self) -> None: ...
