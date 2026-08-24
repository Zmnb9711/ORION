from __future__ import annotations

import asyncio
import base64
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from orion.realtime_provider import RealtimeProviderState, RealtimeSmokeResult

YANDEX_REALTIME_ENDPOINT = "wss://ai.api.cloud.yandex.net/v1/realtime"
YANDEX_MODEL = "speech-realtime-260528"
YANDEX_VOICE = "dasha"
YANDEX_LANGUAGE = "ru-RU"
YANDEX_INPUT_RATE = 44_100
YANDEX_OUTPUT_RATE = 44_100
YANDEX_VAD_THRESHOLD = 0.5
YANDEX_VAD_SILENCE_MS = 400
YANDEX_INSTRUCTIONS = (
    "You are a conversational voice assistant. "
    "Respond naturally and concisely in Russian."
)


def sanitize_yandex_error(value: object, api_key: str = "") -> str:
    text = str(value)
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    text = re.sub(r"(?i)(authorization\s*[:=]\s*)[^\s,;]+(?:\s+[^\s,;]+)?", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)\b(api-key|bearer)\s+[^\s,;]+", r"\1 [REDACTED]", text)
    text = re.sub(r"(?i)([?&](?:api[_-]?key|token)=)[^&\s]+", r"\1[REDACTED]", text)
    return text


def build_yandex_model_uri(folder_id: str) -> str:
    folder = folder_id.strip()
    if not folder:
        raise ValueError("Yandex Folder ID is required")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", folder):
        raise ValueError("Yandex Folder ID contains unsupported characters")
    return f"gpt://{folder}/{YANDEX_MODEL}"


def build_yandex_url(folder_id: str) -> str:
    model_uri = build_yandex_model_uri(folder_id)
    return f"{YANDEX_REALTIME_ENDPOINT}?model={quote(model_uri, safe=':/-_.')}"


def yandex_authorization_headers(api_key: str) -> dict[str, str]:
    key = api_key.strip()
    if not key:
        raise ValueError("Yandex API key is required")
    return {"Authorization": f"Api-Key {key}"}


def yandex_session_update() -> dict[str, object]:
    return {
        "type": "session.update",
        "session": {
            "instructions": YANDEX_INSTRUCTIONS,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": YANDEX_INPUT_RATE},
                    "languages": [YANDEX_LANGUAGE],
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": YANDEX_VAD_THRESHOLD,
                        "silence_duration_ms": YANDEX_VAD_SILENCE_MS,
                    },
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": YANDEX_OUTPUT_RATE},
                    "voice": YANDEX_VOICE,
                },
            },
        },
    }


def encode_yandex_input_audio(pcm: bytes) -> dict[str, object]:
    return {
        "type": "input_audio_buffer.append",
        "audio": base64.b64encode(pcm).decode("ascii"),
    }


def decode_yandex_output_audio(event: dict[str, Any]) -> bytes:
    delta = event.get("delta")
    if not isinstance(delta, str):
        raise ValueError("response.output_audio.delta is missing string field 'delta'")
    return base64.b64decode(delta, validate=True)


@dataclass(slots=True, frozen=True)
class YandexRealtimeConfig:
    api_key: str
    folder_id: str
    timeout_s: float = 10.0


class YandexRealtimeProvider:
    provider_id = "yandex"

    def __init__(self, config: YandexRealtimeConfig) -> None:
        self.config = config

    def test_connection(self) -> RealtimeSmokeResult:
        started = time.perf_counter()
        try:
            asyncio.run(self._test_connection_async())
        except Exception as exc:
            return RealtimeSmokeResult(
                ok=False,
                provider=self.provider_id,
                state=RealtimeProviderState.ERROR,
                message=sanitize_yandex_error(exc, self.config.api_key),
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        return RealtimeSmokeResult(
            ok=True,
            provider=self.provider_id,
            state=RealtimeProviderState.READY,
            message="Yandex Realtime connection and session handshake succeeded",
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    def test_tool_call(self) -> RealtimeSmokeResult:
        return RealtimeSmokeResult(
            ok=False,
            provider=self.provider_id,
            state=RealtimeProviderState.DISABLED,
            message="Yandex tool-call integration not implemented yet",
        )

    async def _test_connection_async(self) -> None:
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=self.config.timeout_s)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(
                build_yandex_url(self.config.folder_id),
                headers=yandex_authorization_headers(self.config.api_key),
                heartbeat=20.0,
                autoclose=True,
            ) as websocket:
                await websocket.send_json(yandex_session_update())
                while True:
                    message = await asyncio.wait_for(websocket.receive(), self.config.timeout_s)
                    if message.type is aiohttp.WSMsgType.TEXT:
                        event = message.json()
                        kind = str(event.get("type") or "")
                        if kind == "session.updated":
                            await websocket.close(code=1000)
                            return
                        if kind == "error":
                            raise RuntimeError(event.get("error") or "Yandex provider error")
                    elif message.type in {
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.CLOSING,
                    }:
                        raise ConnectionError(f"Yandex closed during handshake: {websocket.close_code}")
                    elif message.type is aiohttp.WSMsgType.ERROR:
                        raise ConnectionError(websocket.exception() or "Yandex WebSocket error")
