from __future__ import annotations

import threading
from typing import Any

from pydantic import BaseModel, Field

from orion.qwen_live_audio_core import QwenLiveStartRequest, qwen_live_audio
from orion.realtime_provider import RealtimeLiveStatus
from orion.yandex_live_audio_core import YandexLiveStartRequest, yandex_live_audio


class RealtimeLiveStartRequest(BaseModel):
    provider: str
    api_key: str = Field(min_length=1)
    folder_id: str | None = None
    workspace_id: str | None = None
    region: str = "singapore"
    model: str = "qwen3.5-omni-flash-realtime"
    voice: str = "Tina"


class _QwenLiveAdapter:
    provider_id = "qwen"

    def start_live(self, payload: dict[str, Any]) -> RealtimeLiveStatus:
        status = qwen_live_audio.start(QwenLiveStartRequest.model_validate(payload))
        return self._normalize(status)

    def live_status(self) -> RealtimeLiveStatus:
        return self._normalize(qwen_live_audio.status())

    def stop_live(self) -> RealtimeLiveStatus:
        return self._normalize(qwen_live_audio.stop())

    def _normalize(self, status: Any) -> RealtimeLiveStatus:
        return RealtimeLiveStatus(
            provider=self.provider_id,
            state=str(status.state),
            phase=str(status.phase),
            message=status.message,
            input_name=status.input_name,
            output_name=status.output_name,
            input_rate=status.input_native_rate,
            output_rate=status.output_native_rate,
            input_chunks=status.input_chunks,
            output_chunks=status.output_chunks,
            last_error=status.message if str(status.state) == "error" else None,
        )


class _YandexLiveAdapter:
    provider_id = "yandex"

    def start_live(self, payload: dict[str, Any]) -> RealtimeLiveStatus:
        status = yandex_live_audio.start(YandexLiveStartRequest.model_validate(payload))
        return self._normalize(status)

    def live_status(self) -> RealtimeLiveStatus:
        return self._normalize(yandex_live_audio.status())

    def stop_live(self) -> RealtimeLiveStatus:
        return self._normalize(yandex_live_audio.stop())

    def _normalize(self, status: Any) -> RealtimeLiveStatus:
        return RealtimeLiveStatus(
            provider=self.provider_id,
            state=str(status.state),
            phase=status.phase,
            message=status.message,
            session_id=status.session_id,
            input_name=status.input_name,
            output_name=status.output_name,
            input_rate=status.input_rate,
            output_rate=status.output_rate,
            input_chunks=status.input_chunks,
            output_chunks=status.output_chunks,
            last_error=status.last_error,
        )


class RealtimeLiveCoordinator:
    """Thread-safe owner of provider exclusivity, not provider transport."""

    _ACTIVE_STATES = {"starting", "connected", "streaming"}

    def __init__(self, providers: list[Any] | None = None) -> None:
        self._lock = threading.RLock()
        self._operation_lock = threading.Lock()
        selected = providers or [_QwenLiveAdapter(), _YandexLiveAdapter()]
        self._providers = {provider.provider_id: provider for provider in selected}
        self._active_provider: str | None = None
        self._generation = 0

    def start(self, request: RealtimeLiveStartRequest) -> RealtimeLiveStatus:
        provider_id = request.provider.strip().casefold().removesuffix("_realtime")
        provider = self._providers.get(provider_id)
        if provider is None:
            raise ValueError(f"Unsupported realtime provider: {request.provider}")
        with self._operation_lock:
            with self._lock:
                active = self._active_provider
                if active is not None:
                    current = self._providers[active].live_status()
                    if current.state in self._ACTIVE_STATES:
                        if active == provider_id:
                            raise ValueError(f"{provider_id.title()} realtime voice is already active")
                        raise ValueError(
                            f"Stop current realtime provider ({active}) before starting {provider_id}"
                        )
                    if current.state == "error":
                        raise ValueError(
                            f"Stop errored realtime provider ({active}) before starting {provider_id}"
                        )
                    self._active_provider = None
                self._generation += 1
                generation = self._generation
            payload = request.model_dump(exclude={"provider"}, exclude_none=True)
            result = provider.start_live(payload)
            with self._lock:
                if generation == self._generation:
                    self._active_provider = provider_id
            return result

    def status(self, provider_id: str | None = None) -> RealtimeLiveStatus:
        with self._lock:
            selected = (provider_id or self._active_provider or "").casefold().removesuffix("_realtime")
            provider = self._providers.get(selected)
        if provider is None:
            return RealtimeLiveStatus()
        status = provider.live_status()
        if status.state not in self._ACTIVE_STATES and status.state != "error":
            with self._lock:
                if self._active_provider == selected:
                    self._active_provider = None
        return status

    def stop(self, provider_id: str | None = None) -> RealtimeLiveStatus:
        with self._operation_lock:
            with self._lock:
                selected = (provider_id or self._active_provider or "").casefold().removesuffix("_realtime")
                provider = self._providers.get(selected)
                self._generation += 1
            if provider is None:
                return RealtimeLiveStatus()
            result = provider.stop_live()
            with self._lock:
                if self._active_provider == selected:
                    self._active_provider = None
            return result


realtime_live = RealtimeLiveCoordinator()
