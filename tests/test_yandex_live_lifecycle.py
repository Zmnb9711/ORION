from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace

import aiohttp

from orion.portaudio_devices import PortAudioEndpoint
from orion.windows_wasapi_backend import WasapiDirection
from orion.yandex_live_audio_core import (
    INPUT_FRAMES,
    ResolvedYandexAudio,
    YandexLiveAudioService,
    YandexLiveStartRequest,
)
from orion.yandex_live_diagnostics import YandexLiveDiagnostics


class _WebSocket:
    def __init__(self, *, handshake: bool = True) -> None:
        self.closed = False
        self.close_code: int | None = None
        self.close_calls = 0
        self.sent: list[dict[str, object]] = []
        self._messages: asyncio.Queue[object] = asyncio.Queue()
        if handshake:
            self._messages.put_nowait(
                SimpleNamespace(
                    type=aiohttp.WSMsgType.TEXT,
                    json=lambda: {"type": "session.updated", "session": {"id": "server-session"}},
                )
            )

    async def send_json(self, event: dict[str, object]) -> None:
        if self.closed:
            raise ConnectionError("closed")
        self.sent.append(event)

    async def receive(self) -> object:
        return await self._messages.get()

    async def close(self, *, code: int = 1000) -> None:
        self.close_calls += 1
        self.closed = True
        self.close_code = code
        self._messages.put_nowait(SimpleNamespace(type=aiohttp.WSMsgType.CLOSED))

    def exception(self) -> None:
        return None


class _ClientSession:
    def __init__(self, websocket: _WebSocket) -> None:
        self.websocket = websocket

    async def __aenter__(self) -> _ClientSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def ws_connect(self, *args: object, **kwargs: object) -> _WebSocket:
        return self.websocket


class _InputStream:
    def __enter__(self) -> _InputStream:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, frames: int) -> tuple[bytes, bool]:
        assert frames == INPUT_FRAMES
        time.sleep(0.002)
        return b"\0" * (frames * 2), False


class _OutputStream:
    def __init__(self) -> None:
        self.written: list[bytes] = []

    def __enter__(self) -> _OutputStream:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def write(self, pcm: bytes) -> None:
        self.written.append(pcm)


class _SoundDevice:
    def __init__(self) -> None:
        self.output = _OutputStream()

    def RawInputStream(self, **kwargs: object) -> _InputStream:
        return _InputStream()

    def RawOutputStream(self, **kwargs: object) -> _OutputStream:
        return self.output


def _endpoint(direction: WasapiDirection, index: int) -> PortAudioEndpoint:
    return PortAudioEndpoint(
        direction=direction,
        device_index=index,
        device_name=f"device-{index}",
        host_api_index=0,
        host_api_name="MME",
        max_input_channels=1 if direction is WasapiDirection.INPUT else 0,
        max_output_channels=1 if direction is WasapiDirection.OUTPUT else 0,
        default_samplerate=44100,
        device_id=f"sounddevice:portaudio:{direction.value}:0:{index}",
        name=f"device-{index}",
    )


def _audio() -> ResolvedYandexAudio:
    return ResolvedYandexAudio(
        _endpoint(WasapiDirection.INPUT, 1),
        _endpoint(WasapiDirection.OUTPUT, 6),
        None,
        None,
    )


def test_live_shutdown_has_one_close_owner_and_no_send_after_close(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    websocket = _WebSocket()
    monkeypatch.setattr(aiohttp, "ClientSession", lambda **kwargs: _ClientSession(websocket))
    stop = threading.Event()
    service = YandexLiveAudioService()
    diagnostics = YandexLiveDiagnostics("session", "secret", tmp_path)

    async def scenario() -> None:
        task = asyncio.create_task(
            service._run_async(
                YandexLiveStartRequest(api_key="secret", folder_id="folder"),
                _audio(),
                _SoundDevice(),
                stop,
                diagnostics,
            )
        )
        for _ in range(100):
            if service.status().state == "streaming":
                break
            await asyncio.sleep(0.005)
        assert service.status().state == "streaming"
        stop.set()
        await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(scenario())
    assert websocket.close_calls == 1
    assert websocket.close_code == 1000
    assert websocket.sent[0]["type"] == "session.update"
    assert all(item["type"] in {"session.update", "input_audio_buffer.append"} for item in websocket.sent)
    assert service.status().clean_close is True


def test_stop_during_session_update_is_bounded_and_clean(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    websocket = _WebSocket(handshake=False)
    monkeypatch.setattr(aiohttp, "ClientSession", lambda **kwargs: _ClientSession(websocket))
    stop = threading.Event()
    service = YandexLiveAudioService()

    async def scenario() -> None:
        task = asyncio.create_task(
            service._run_async(
                YandexLiveStartRequest(api_key="secret", folder_id="folder"),
                _audio(),
                _SoundDevice(),
                stop,
                YandexLiveDiagnostics("connecting", "secret", tmp_path),
            )
        )
        await asyncio.sleep(0.03)
        stop.set()
        await asyncio.wait_for(task, timeout=1.0)

    asyncio.run(scenario())
    assert websocket.close_calls == 1
    assert websocket.close_code == 1000
