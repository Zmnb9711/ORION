from __future__ import annotations

import threading
from typing import Any

from pydantic import BaseModel, Field, SecretStr

from orion.qwen_live_audio_core import QwenLiveStartRequest, qwen_live_audio
from orion.realtime_provider import RealtimeLiveStatus
from orion.yandex_live_audio_core import YandexLiveStartRequest, yandex_live_audio


class SrsLiveStartRequest(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=5002, ge=1, le=65_535)
    bot_name: str = Field(default="ORION SRS", min_length=1, max_length=80)
    frequency_hz: float = Field(default=251_000_000.0, gt=0)
    modulation: int = 0
    eam_password: SecretStr


class RealtimeLiveStartRequest(BaseModel):
    provider: str
    transport: str = "direct"
    api_key: str = Field(min_length=1, repr=False)
    folder_id: str | None = None
    workspace_id: str | None = None
    region: str = "singapore"
    model: str = "qwen3.5-omni-flash-realtime"
    voice: str = "Tina"
    radio_stt_provider: str = "yandex_realtime"
    srs: SrsLiveStartRequest | None = None


class _QwenLiveAdapter:
    provider_id = "qwen"
    transport_id = "direct"

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
            transport=self.transport_id,
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
    transport_id = "direct"

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
            transport=self.transport_id,
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


class _YandexSrsLiveAdapter:
    provider_id = "yandex"
    transport_id = "srs"

    def start_live(self, payload: dict[str, Any]) -> RealtimeLiveStatus:
        from orion.yandex_srs_live_core import YandexSrsStartRequest, yandex_srs_live

        srs = payload.pop("srs", None)
        if not isinstance(srs, dict):
            raise ValueError("Yandex + SRS requires SRS connection settings")
        password = srs.get("eam_password")
        if isinstance(password, SecretStr):
            srs["eam_password"] = password
        status = yandex_srs_live.start(YandexSrsStartRequest.model_validate({**payload, **srs}))
        return self._normalize(status)

    def live_status(self) -> RealtimeLiveStatus:
        from orion.yandex_srs_live_core import yandex_srs_live

        return self._normalize(yandex_srs_live.status())

    def stop_live(self) -> RealtimeLiveStatus:
        from orion.yandex_srs_live_core import yandex_srs_live

        return self._normalize(yandex_srs_live.stop())

    def _normalize(self, status: Any) -> RealtimeLiveStatus:
        return RealtimeLiveStatus(
            provider=self.provider_id,
            transport=self.transport_id,
            state=str(status.state),
            phase=str(status.phase),
            message=status.message,
            session_id=status.session_id,
            input_name=f"SRS {status.frequency_hz / 1_000_000:.3f} AM",
            output_name=f"SRS {status.frequency_hz / 1_000_000:.3f} AM",
            input_rate=16_000,
            output_rate=16_000,
            input_chunks=status.input_chunks,
            output_chunks=status.output_chunks,
            last_error=status.last_error,
        )


class RealtimeLiveCoordinator:
    """Thread-safe owner of one active provider/transport combination."""

    _ACTIVE_STATES = {"starting", "connected", "streaming"}

    def __init__(self, providers: list[Any] | None = None) -> None:
        self._lock = threading.RLock()
        self._operation_lock = threading.Lock()
        selected = providers or [_QwenLiveAdapter(), _YandexLiveAdapter(), _YandexSrsLiveAdapter()]
        self._providers = {
            (provider.provider_id, getattr(provider, "transport_id", "direct")): provider
            for provider in selected
        }
        self._active_selection: tuple[str, str] | None = None
        self._generation = 0

    def start(self, request: RealtimeLiveStartRequest) -> RealtimeLiveStatus:
        provider_id = request.provider.strip().casefold().removesuffix("_realtime")
        transport_id = request.transport.strip().casefold().removesuffix("_audio")
        selection = (provider_id, transport_id)
        provider = self._providers.get(selection)
        if provider is None:
            if provider_id == "qwen" and transport_id == "srs":
                raise ValueError("Unsupported realtime combination: Qwen + SRS is not available in v0.1")
            raise ValueError(
                f"Unsupported realtime combination: {request.provider} + {request.transport}"
            )
        if transport_id == "srs" and request.srs is None:
            raise ValueError("SRS transport settings are required")
        with self._operation_lock:
            with self._lock:
                active = self._active_selection
                if active is not None:
                    current = self._providers[active].live_status()
                    if current.state in self._ACTIVE_STATES:
                        if active == selection:
                            raise ValueError(
                                f"{provider_id.title()} {transport_id} realtime voice is already active"
                            )
                        raise ValueError(
                            f"Stop current realtime provider ({active[0]}) before starting {provider_id}"
                        )
                    if current.state == "error":
                        raise ValueError(
                            f"Stop errored realtime provider ({active[0]}) before starting {provider_id}"
                        )
                    self._active_selection = None
                self._generation += 1
                generation = self._generation
            payload = request.model_dump(
                exclude={"provider", "transport"},
                exclude_none=True,
            )
            if transport_id == "direct":
                payload.pop("srs", None)
                payload.pop("radio_stt_provider", None)
            result = provider.start_live(payload)
            with self._lock:
                if generation == self._generation:
                    self._active_selection = selection
            return result

    def status(self, provider_id: str | None = None) -> RealtimeLiveStatus:
        with self._lock:
            if provider_id:
                requested = provider_id.casefold().removesuffix("_realtime")
                selected = (
                    self._active_selection
                    if self._active_selection is not None and self._active_selection[0] == requested
                    else (requested, "direct")
                )
            else:
                selected = self._active_selection
            provider = self._providers.get(selected) if selected is not None else None
        if provider is None:
            return RealtimeLiveStatus()
        status = provider.live_status()
        if status.state not in self._ACTIVE_STATES and status.state != "error":
            with self._lock:
                if self._active_selection == selected:
                    self._active_selection = None
        return status

    def stop(self, provider_id: str | None = None) -> RealtimeLiveStatus:
        with self._operation_lock:
            with self._lock:
                if provider_id:
                    requested = provider_id.casefold().removesuffix("_realtime")
                    selected = (
                        self._active_selection
                        if self._active_selection is not None and self._active_selection[0] == requested
                        else (requested, "direct")
                    )
                else:
                    selected = self._active_selection
                provider = self._providers.get(selected) if selected is not None else None
                self._generation += 1
            if provider is None:
                return RealtimeLiveStatus()
            result = provider.stop_live()
            with self._lock:
                if self._active_selection == selected:
                    self._active_selection = None
            return result


realtime_live = RealtimeLiveCoordinator()
