from __future__ import annotations

import pytest

from orion.yandex_speechkit_streaming_tts import (
    SPEECHKIT_STREAM_TTS_RATE_HZ,
    SpeechKitTtsOutputMode,
    speechkit_stream_options,
    speechkit_stream_requests,
)


def test_streamsynthesis_request_uses_proven_official_sequence_and_pcm() -> None:
    requests = speechkit_stream_requests("ПРИЕМ! Viper 2-1, взлёт разрешён.")
    assert [request.WhichOneof("Event") for request in requests] == [
        "options",
        "synthesis_input",
        "force_synthesis",
    ]
    options = speechkit_stream_options()
    assert options.voice == "jane"
    assert options.role == "neutral"
    assert options.speed == 1.0
    assert options.model == ""
    assert options.output_audio_spec.raw_audio.sample_rate_hertz == 48_000
    assert options.output_audio_spec.raw_audio.audio_encoding == 1
    assert SPEECHKIT_STREAM_TTS_RATE_HZ == 48_000


def test_rest_remains_default_and_streaming_is_explicit() -> None:
    assert SpeechKitTtsOutputMode.REST_BUFFERED.value == "speechkit_rest"
    assert SpeechKitTtsOutputMode.STREAMING_V3.value == "speechkit_v3_streaming"


@pytest.mark.parametrize("text", ["", "   ", "x" * 5_001])
def test_streamsynthesis_text_is_bounded(text: str) -> None:
    with pytest.raises(ValueError, match="1 to 5000"):
        speechkit_stream_requests(text)
