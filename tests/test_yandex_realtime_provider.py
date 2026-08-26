from __future__ import annotations

import base64

import pytest

from orion.yandex_realtime_provider import (
    YANDEX_INPUT_RATE,
    YANDEX_LANGUAGE,
    YANDEX_MODEL,
    YANDEX_OUTPUT_RATE,
    YANDEX_REALTIME_ENDPOINT,
    YANDEX_VAD_SILENCE_MS,
    YANDEX_VAD_THRESHOLD,
    YANDEX_VOICE,
    YANDEX_VOICE_ROLE,
    YandexRealtimeConfig,
    YandexRealtimeProvider,
    build_yandex_model_uri,
    build_yandex_url,
    decode_yandex_output_audio,
    encode_yandex_input_audio,
    sanitize_yandex_error,
    yandex_authorization_headers,
    yandex_session_update,
)


def test_yandex_endpoint_authorization_and_model_uri_are_exact() -> None:
    assert YANDEX_REALTIME_ENDPOINT == "wss://ai.api.cloud.yandex.net/v1/realtime"
    assert build_yandex_model_uri("folder_123") == f"gpt://folder_123/{YANDEX_MODEL}"
    assert build_yandex_url("folder_123") == (
        "wss://ai.api.cloud.yandex.net/v1/realtime?"
        "model=gpt://folder_123/speech-realtime-260528"
    )
    assert yandex_authorization_headers("secret") == {"Authorization": "Api-Key secret"}


def test_yandex_session_update_has_production_defaults_and_no_tools() -> None:
    payload = yandex_session_update()
    session = payload["session"]
    assert isinstance(session, dict)
    audio = session["audio"]
    assert isinstance(audio, dict)
    input_audio = audio["input"]
    output_audio = audio["output"]
    assert input_audio == {
        "format": {"type": "audio/pcm", "rate": YANDEX_INPUT_RATE},
        "languages": [YANDEX_LANGUAGE],
        "turn_detection": {
            "type": "server_vad",
            "threshold": YANDEX_VAD_THRESHOLD,
            "silence_duration_ms": YANDEX_VAD_SILENCE_MS,
        },
    }
    assert output_audio == {
        "format": {"type": "audio/pcm", "rate": YANDEX_OUTPUT_RATE},
        "voice": YANDEX_VOICE,
        "role": YANDEX_VOICE_ROLE,
    }
    assert "tools" not in session


def test_yandex_input_and_output_base64_are_bit_exact() -> None:
    pcm = bytes(range(256)) * 7
    encoded = encode_yandex_input_audio(pcm)
    assert encoded["type"] == "input_audio_buffer.append"
    assert base64.b64decode(str(encoded["audio"]), validate=True) == pcm
    assert decode_yandex_output_audio({"delta": encoded["audio"]}) == pcm


def test_yandex_output_decode_is_strict() -> None:
    with pytest.raises(ValueError):
        decode_yandex_output_audio({"delta": "not base64!!!"})


def test_yandex_errors_redact_key_and_authorization() -> None:
    text = sanitize_yandex_error(
        "request secret Authorization: Api-Key secret?api_key=secret",
        "secret",
    )
    assert "secret" not in text
    assert "[REDACTED]" in text


def test_yandex_tool_call_is_honestly_unsupported() -> None:
    provider = YandexRealtimeProvider(YandexRealtimeConfig("key", "folder"))
    result = provider.test_tool_call()
    assert result.ok is False
    assert "not implemented" in result.message
