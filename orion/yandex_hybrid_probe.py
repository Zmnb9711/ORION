"""IA-1.1 bounded Yandex Realtime versus SpeechKit presentation probe.

This is deliberately a feasibility probe, not a production presentation router.
Both arms start from the same finalized synthetic case.  Realtime may render the
case, while SpeechKit receives the finalized text directly and never receives
Realtime output or ambient FlightContext.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Protocol
from urllib.parse import urlencode
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from orion.realtime_test_evidence import realtime_test_evidence
from orion.yandex_realtime_provider import (
    build_yandex_url,
    decode_yandex_output_audio,
    yandex_authorization_headers,
)

SPEECHKIT_TTS_ENDPOINT = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
SPEECHKIT_RATE = 48_000
ORION_PROVIDER_RATE = 44_100
PROBE_TIMEOUT_S = 30.0
TX_TIMEOUT_S = 45.0
TX_GUARD_S = 0.250
SPEECHKIT_V1_PROBE_PROFILES = frozenset(
    {
        ("jane", "neutral"),
        ("jane", "evil"),
        ("ermil", "neutral"),
    }
)


class HybridProbeState(StrEnum):
    OFF = "off"
    RUNNING = "running"
    PASS = "pass"
    REVIEW = "review"
    FAIL = "fail"


class SpeechKitFailureCategory(StrEnum):
    UNAUTHORIZED = "unauthorized_credential_or_scope"
    FORBIDDEN = "forbidden_or_missing_permission"
    MALFORMED_REQUEST = "malformed_request"
    RATE_LIMITED = "rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    HTTP_ERROR = "provider_http_error"


class SpeechKitProviderError(RuntimeError):
    """Safe provider failure that never retains the response body or credential."""

    def __init__(
        self,
        status: int,
        *,
        provider_code: str | None = None,
        provider_message: str | None = None,
    ) -> None:
        self.status = status
        self.provider_code = provider_code
        self.provider_message = provider_message
        if status == 401:
            self.category = SpeechKitFailureCategory.UNAUTHORIZED
            message = (
                "SpeechKit authorization failed (HTTP 401): verify the service-account "
                "API key, yc.ai.speechkitTts.execute scope, and ai.speechkit-tts.user role"
            )
        elif status == 403:
            self.category = SpeechKitFailureCategory.FORBIDDEN
            message = (
                "SpeechKit permission denied (HTTP 403): verify ai.speechkit-tts.user "
                "access and Yandex Cloud policy"
            )
        elif status == 400:
            self.category = SpeechKitFailureCategory.MALFORMED_REQUEST
            message = "SpeechKit rejected the synthesis request (HTTP 400)"
        elif status == 429:
            self.category = SpeechKitFailureCategory.RATE_LIMITED
            message = "SpeechKit synthesis rate limit reached (HTTP 429)"
        elif 500 <= status <= 599:
            self.category = SpeechKitFailureCategory.PROVIDER_UNAVAILABLE
            message = f"SpeechKit service unavailable (HTTP {status})"
        else:
            self.category = SpeechKitFailureCategory.HTTP_ERROR
            message = f"SpeechKit request failed (HTTP {status})"
        if provider_code or provider_message:
            detail = ": ".join(item for item in (provider_code, provider_message) if item)
            message = f"{message}: {detail}"
        super().__init__(message)

    @classmethod
    def from_payload(cls, status: int, payload: bytes, *, secret: str) -> SpeechKitProviderError:
        """Extract only bounded allow-listed provider fields from an error response."""

        provider_code: str | None = None
        provider_message: str | None = None
        try:
            decoded = json.loads(payload[:2048].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            decoded = None
        if isinstance(decoded, dict):
            raw_code = decoded.get("error_code")
            raw_message = decoded.get("error_message")
            if isinstance(raw_code, str):
                provider_code = _bounded_provider_field(raw_code, secret, 80)
            if isinstance(raw_message, str):
                provider_message = _bounded_provider_field(raw_message, secret, 240)
        return cls(
            status,
            provider_code=provider_code,
            provider_message=provider_message,
        )


def _bounded_provider_field(value: str, secret: str, limit: int) -> str:
    safe = value.replace(secret, "<redacted>") if secret else value
    safe = re.sub(r"[\x00-\x1f\x7f]+", " ", safe)
    return re.sub(r"\s+", " ", safe).strip()[:limit]


class AcousticReview(StrEnum):
    CLEAR = "clear"
    REVIEW = "review"
    FAIL = "fail"


class HybridProbeStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: HybridProbeState = HybridProbeState.OFF
    message: str = "Hybrid presentation probe is off"
    compatible_session: bool = False
    probe_run_id: str | None = None
    case_id: str | None = None
    backend: str | None = None
    main_session_id: str | None = None
    probe_session_id: str | None = None
    completed_pairs: int = 0
    total_pairs: int = 20
    latest_artifact: str | None = None
    audio_capture_enabled: bool = False


@dataclass(frozen=True, slots=True)
class TestSemanticCase:
    case_id: str
    finalized_text: str
    required_groups: tuple[tuple[str, ...], ...]
    voice: str = "jane"
    role: str = "neutral"


def hybrid_probe_cases() -> tuple[TestSemanticCase, ...]:
    """One synthetic aviation concept per finalized phrase."""

    return (
        TestSemanticCase("heading-137", "Курс сто тридцать семь градусов.", (("137", "сто тридцать семь"), ("градус",))),
        TestSemanticCase("tas-286", "Истинная воздушная скорость двести восемьдесят шесть узлов.", (("286", "двести восемьдесят шесть"), ("узл",)), "ermil"),
        TestSemanticCase("altitude-12450", "Высота двенадцать тысяч четыреста пятьдесят футов.", (("12450", "12 450", "двенадцать тысяч четыреста пятьдесят"), ("фут",))),
        TestSemanticCase("radio-264500", "Радио двести шестьдесят четыре целых пять десятых мегагерца, амплитудная модуляция.", (("264.500", "264,500", "двести шестьдесят четыре целых пять"), ("мегагерц",), ("амплитуд", " am")), "jane"),
        TestSemanticCase("tacan-44x", "ТАКАН сорок четыре икс.", (("44x", "44 x", "сорок четыре икс"),), "jane", "evil"),
        TestSemanticCase("laser-1577", "Лазерный код один пять семь семь.", (("1577", "один пять семь семь"), ("лазер",)), "jane"),
        TestSemanticCase("callsign-viper21", "Позывной Вайпер два один.", (("viper 2-1", "вайпер два один", "вайпер 2 1"), ("позывн",))),
        TestSemanticCase("distance-63", "Дистанция шестьдесят три морские мили.", (("63", "шестьдесят три"), ("морск", " nm"))),
        TestSemanticCase("negative-850", "Поправка минус восемьсот пятьдесят футов.", (("-850", "минус восемьсот пятьдесят"), ("фут",))),
        TestSemanticCase("tacan-unavailable", "ТАКАН недоступен.", (("tacan", "такан"), ("недоступ",))),
    )


def _normalized(value: str) -> str:
    value = value.casefold().replace("ё", "е")
    value = re.sub(r"[^a-zа-я0-9.,+-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def evaluate_semantics(case: TestSemanticCase, observed: str) -> dict[str, object]:
    """Deterministic text gate; acoustic quality remains an explicit human review."""

    normalized = _normalized(observed)
    groups = [any(_normalized(token) in normalized for token in group) for group in case.required_groups]
    return {
        "status": "PASS" if groups and all(groups) else "FAIL",
        "required_group_matches": groups,
        "sign_preserved": ("minus" not in case.case_id) or ("минус" in normalized or "-850" in normalized),
        "unavailable_preserved": ("unavailable" not in case.case_id) or "недоступ" in normalized,
    }


def speechkit_request(
    case: TestSemanticCase,
    *,
    api_key: str,
) -> tuple[str, dict[str, str], bytes]:
    """Build the documented SpeechKit v1 REST request without retaining secrets."""

    key = api_key.strip()
    if not key:
        raise ValueError("Yandex API key is required")
    text = case.finalized_text.strip()
    if not text or len(text) > 5000:
        raise ValueError("SpeechKit text must contain 1 to 5000 characters")
    if (case.voice, case.role) not in SPEECHKIT_V1_PROBE_PROFILES:
        raise ValueError(
            f"Voice/role {case.voice}/{case.role} is not supported by the SpeechKit REST v1 probe"
        )
    fields = {
        "text": text,
        "lang": "ru-RU",
        "voice": case.voice,
        "emotion": case.role,
        "speed": "1.0",
        "format": "lpcm",
        "sampleRateHertz": str(SPEECHKIT_RATE),
    }
    body = urlencode(fields).encode("utf-8")
    if len(body) > 15 * 1024:
        raise ValueError("SpeechKit request exceeds the documented 15 KB limit")
    return (
        SPEECHKIT_TTS_ENDPOINT,
        {
            "Authorization": f"Api-Key {key}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        body,
    )


class ProbeTxEndpoint(Protocol):
    def transmit_probe_audio(self, response_id: str, pcm44: bytes, timeout_s: float) -> dict[str, float]: ...


@dataclass(slots=True)
class HybridRuntimeContext:
    api_key: str = field(repr=False)
    folder_id: str
    endpoint: ProbeTxEndpoint
    main_session_id: str
    context_version: str | None


class SpeechKitTtsClient:
    async def synthesize(self, case: TestSemanticCase, api_key: str) -> tuple[bytes, str]:
        import aiohttp

        url, headers, body = speechkit_request(case, api_key=api_key)
        timeout = aiohttp.ClientTimeout(total=PROBE_TIMEOUT_S, connect=5.0)
        async with aiohttp.ClientSession(timeout=timeout) as client:
            async with client.post(url, headers=headers, data=body) as response:
                payload = await response.read()
                if response.status != 200:
                    raise SpeechKitProviderError.from_payload(
                        response.status,
                        payload,
                        secret=api_key,
                    )
        if not payload or len(payload) % 2:
            raise ValueError("SpeechKit returned invalid LPCM audio")
        return payload, case.finalized_text


class RealtimePresentationClient:
    """Disposable probe-only Realtime session with strict effective-config acks."""

    def __init__(self, api_key: str, folder_id: str) -> None:
        self._api_key = api_key
        self._folder_id = folder_id
        self._client: Any = None
        self._websocket: Any = None
        self.session_id: str | None = None

    async def __aenter__(self) -> RealtimePresentationClient:
        import aiohttp

        self._client = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, connect=5.0))
        self._websocket = await self._client.ws_connect(
            build_yandex_url(self._folder_id),
            headers=yandex_authorization_headers(self._api_key),
            heartbeat=20.0,
            autoclose=True,
        )
        await self._websocket.send_json(
            {
                "type": "session.update",
                "session": {
                    "instructions": "Озвучивай только переданный финализированный текст. Не добавляй и не изменяй факты.",
                    "output_modalities": ["audio"],
                    "audio": {"output": {"format": {"type": "audio/pcm", "rate": ORION_PROVIDER_RATE}, "voice": "dasha", "role": "neutral"}},
                },
            }
        )
        session, _observed = await self._await_effective_config("dasha", "neutral")
        self.session_id = str(session.get("id") or "")
        if not self.session_id:
            raise RuntimeError("Probe session.updated did not expose a session ID")
        return self

    async def __aexit__(self, *_args: object) -> None:
        if self._websocket is not None and not self._websocket.closed:
            await self._websocket.close(code=1000)
        if self._client is not None:
            await self._client.close()

    async def apply_voice(self, voice: str, role: str) -> list[dict[str, str]]:
        await self._websocket.send_json(
            {"type": "session.update", "session": {"audio": {"output": {"voice": voice, "role": role}}}}
        )
        _session, observed = await self._await_effective_config(voice, role)
        return observed

    async def _await_effective_config(
        self, voice: str, role: str
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        observed: list[dict[str, str]] = []
        deadline = time.monotonic() + PROBE_TIMEOUT_S
        while time.monotonic() < deadline:
            event = await self._receive_event(deadline)
            kind = str(event.get("type") or "")
            if kind == "error":
                raise RuntimeError("Yandex rejected hybrid probe session configuration")
            if kind != "session.updated":
                continue
            session = dict(event.get("session") or {})
            output = ((session.get("audio") or {}).get("output") or {})
            effective = {"voice": str(output.get("voice") or ""), "role": str(output.get("role") or "")}
            observed.append(effective)
            if effective == {"voice": voice, "role": role}:
                return session, observed
        raise TimeoutError("Timed out waiting for effective Yandex voice/role configuration")

    async def synthesize(self, case: TestSemanticCase) -> tuple[bytes, str, dict[str, float]]:
        await self._websocket.send_json(
            {
                "type": "conversation.item.create",
                "item": {"type": "message", "object": "realtime.item", "role": "user", "content": [{"type": "input_text", "text": case.finalized_text}]},
            }
        )
        await self._websocket.send_json(
            {"type": "response.create", "response": {"instructions": "Произнеси дословно только текст последнего сообщения.", "output_modalities": ["audio"]}}
        )
        started = time.monotonic()
        first_audio: float | None = None
        pcm = bytearray()
        transcript = ""
        response_id = ""
        deadline = started + PROBE_TIMEOUT_S
        while time.monotonic() < deadline:
            event = await self._receive_event(deadline)
            kind = str(event.get("type") or "")
            if kind == "error":
                raise RuntimeError("Yandex rejected hybrid Realtime rendering")
            if kind == "response.created":
                response_id = str((event.get("response") or {}).get("id") or event.get("response_id") or "")
            elif kind == "response.output_audio.delta":
                if first_audio is None:
                    first_audio = time.monotonic()
                pcm.extend(decode_yandex_output_audio(event))
            elif kind in {"response.output_audio_transcript.done", "response.output_text.done"}:
                transcript = str(event.get("transcript") or event.get("text") or "")
            elif kind == "response.done":
                response = event.get("response") or {}
                current_id = str(response.get("id") or event.get("response_id") or "")
                if not response_id or current_id == response_id:
                    status = str(response.get("status") or "")
                    if status != "completed":
                        raise RuntimeError(f"Realtime rendering ended with status {status or 'unknown'}")
                    if not pcm:
                        raise RuntimeError("Realtime rendering completed without audio")
                    finished = time.monotonic()
                    return bytes(pcm), transcript, {
                        "provider_first_audio_ms": ((first_audio or finished) - started) * 1000,
                        "provider_complete_ms": (finished - started) * 1000,
                    }
        raise TimeoutError("Timed out waiting for hybrid Realtime rendering")

    async def interruption_recovery(self) -> dict[str, object]:
        """Cancel one noncritical probe response, then prove the session can respond again."""

        await self._websocket.send_json(
            {
                "type": "conversation.item.create",
                "item": {"type": "message", "object": "realtime.item", "role": "user", "content": [{"type": "input_text", "text": "Неприоритетная проверка прерывания."}]},
            }
        )
        await self._websocket.send_json(
            {"type": "response.create", "response": {"instructions": "Произнеси переданный текст медленно.", "output_modalities": ["audio"]}}
        )
        response_id = ""
        cancel_sent = False
        deadline = time.monotonic() + PROBE_TIMEOUT_S
        cancelled_status = "NOT OBSERVABLE"
        while time.monotonic() < deadline:
            event = await self._receive_event(deadline)
            kind = str(event.get("type") or "")
            if kind == "error":
                raise RuntimeError("Yandex rejected interruption probe")
            if kind == "response.created":
                response_id = str((event.get("response") or {}).get("id") or "")
            elif kind == "response.output_audio.delta" and response_id and not cancel_sent:
                await self._websocket.send_json({"type": "response.cancel", "response_id": response_id})
                cancel_sent = True
            elif kind == "response.done":
                response = event.get("response") or {}
                if str(response.get("id") or "") == response_id:
                    cancelled_status = str(response.get("status") or "unknown")
                    break
        recovery_case = TestSemanticCase(
            "recovery-noncritical",
            "Восстановление после прерывания подтверждено.",
            (("восстанов",), ("подтвержд",)),
        )
        _pcm, transcript, _timing = await self.synthesize(recovery_case)
        return {
            "cancel_sent": cancel_sent,
            "cancelled_status": cancelled_status,
            "recovery_text_validation": evaluate_semantics(recovery_case, transcript),
            "critical_case_interrupted": False,
        }

    async def _receive_event(self, deadline: float) -> dict[str, Any]:
        import aiohttp

        remaining = max(0.01, deadline - time.monotonic())
        message = await asyncio.wait_for(self._websocket.receive(), remaining)
        if message.type is aiohttp.WSMsgType.TEXT:
            return dict(message.json())
        raise ConnectionError("Yandex closed the disposable hybrid probe session")


def normalize_speechkit_pcm(pcm48: bytes) -> bytes:
    from orion.srs_resampler import StreamingPcm16Resampler

    resampler = StreamingPcm16Resampler(SPEECHKIT_RATE, ORION_PROVIDER_RATE)
    return resampler.process(pcm48, end_of_input=True)


class HybridProbeRunner:
    def __init__(
        self,
        *,
        speechkit_factory: Callable[[], SpeechKitTtsClient] = SpeechKitTtsClient,
        realtime_factory: Callable[[str, str], RealtimePresentationClient] = RealtimePresentationClient,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self._speechkit_factory = speechkit_factory
        self._realtime_factory = realtime_factory
        self._sleep = sleep

    async def run(
        self,
        context: HybridRuntimeContext,
        run_id: str,
        *,
        capture_audio: bool,
        progress: Callable[[str, str, str | None], None],
    ) -> tuple[int, str, bool]:
        completed = 0
        text_gate_passed = True
        speechkit = self._speechkit_factory()
        probe_session_id = ""
        async with self._realtime_factory(context.api_key, context.folder_id) as realtime:
            probe_session_id = realtime.session_id or ""
            realtime_test_evidence.record_hybrid_run(
                run_id=run_id,
                main_session_id=context.main_session_id,
                probe_session_id=probe_session_id,
                context_version_before=context.context_version,
            )
            current_config: tuple[str, str] | None = None
            for case in hybrid_probe_cases():
                if current_config != (case.voice, case.role):
                    observations = await realtime.apply_voice(case.voice, case.role)
                    realtime_test_evidence.record_hybrid_config(run_id, case.case_id, case.voice, case.role, observations)
                    current_config = (case.voice, case.role)
                for backend in ("realtime", "speechkit"):
                    progress(case.case_id, backend, probe_session_id)
                    request_at = time.monotonic()
                    if backend == "realtime":
                        pcm44, transcript, provider_timing = await realtime.synthesize(case)
                    else:
                        pcm48, transcript = await speechkit.synthesize(case, context.api_key)
                        first_at = time.monotonic()
                        pcm44 = normalize_speechkit_pcm(pcm48)
                        provider_timing = {
                            "provider_first_audio_ms": (first_at - request_at) * 1000,
                            "provider_complete_ms": (time.monotonic() - request_at) * 1000,
                        }
                    observed_text = transcript if backend == "realtime" else case.finalized_text
                    evaluation = evaluate_semantics(case, observed_text)
                    text_gate_passed = text_gate_passed and evaluation["status"] == "PASS"
                    response_id = f"ia11-{run_id[:8]}-{case.case_id}-{backend}"
                    if capture_audio:
                        realtime_test_evidence.record_hybrid_audio(
                            run_id=run_id,
                            case_id=case.case_id,
                            backend=backend,
                            response_id=response_id,
                            pcm44=pcm44,
                        )
                    queue_at = time.monotonic()
                    tx = await asyncio.to_thread(
                        context.endpoint.transmit_probe_audio,
                        response_id,
                        pcm44,
                        TX_TIMEOUT_S,
                    )
                    completed += 1
                    realtime_test_evidence.record_hybrid_case(
                        run_id=run_id,
                        case=case,
                        backend=backend,
                        response_id=response_id,
                        transcript=observed_text,
                        evaluation=evaluation,
                        provider_timing=provider_timing,
                        queue_latency_ms=(queue_at - request_at) * 1000,
                        tx_timing=tx,
                    )
                    await self._sleep(TX_GUARD_S)
            recovery = await realtime.interruption_recovery()
            realtime_test_evidence.record_hybrid_recovery(run_id, recovery)
            realtime_test_evidence.record_hybrid_isolation(
                run_id=run_id,
                main_session_id=context.main_session_id,
                probe_session_id=probe_session_id,
                context_version_before=context.context_version,
                context_version_after=realtime_test_evidence.current_context_version,
            )
        return completed, probe_session_id, text_gate_passed


class YandexHybridProbeAdapter:
    """Owns one opt-in probe and only memory-scoped live credentials."""

    def __init__(self, runner_factory: Callable[[], HybridProbeRunner] = HybridProbeRunner) -> None:
        self._lock = threading.RLock()
        self._context: HybridRuntimeContext | None = None
        self._runner_factory = runner_factory
        self._status = HybridProbeStatus()

    def attach(self, context: HybridRuntimeContext) -> None:
        with self._lock:
            self._context = context
            self._status = self._status.model_copy(update={"compatible_session": True, "main_session_id": context.main_session_id})

    def detach(self, main_session_id: str) -> None:
        with self._lock:
            if self._context is None or self._context.main_session_id != main_session_id:
                return
            self._context = None
            update: dict[str, object] = {"compatible_session": False}
            if self._status.state is HybridProbeState.RUNNING:
                update.update(state=HybridProbeState.FAIL, message="Compatible Yandex SRS session closed during probe")
            self._status = self._status.model_copy(update=update)

    def start(self, *, capture_audio: bool = False) -> HybridProbeStatus:
        with self._lock:
            if not realtime_test_evidence.status().active:
                raise ValueError("Start Test Evidence Session before the hybrid probe")
            if self._context is None:
                raise ValueError("Hybrid probe requires an active Yandex + SRS session")
            if self._status.state is HybridProbeState.RUNNING:
                raise ValueError("Hybrid presentation probe is already running")
            context = self._context
            run_id = uuid4().hex
            self._status = HybridProbeStatus(
                state=HybridProbeState.RUNNING,
                message="Hybrid presentation probe is running",
                compatible_session=True,
                probe_run_id=run_id,
                main_session_id=context.main_session_id,
                audio_capture_enabled=capture_audio,
            )
            thread = threading.Thread(
                target=self._run,
                args=(context, run_id, capture_audio),
                name="orion-ia11-hybrid-probe",
                daemon=True,
            )
            thread.start()
            return self._status.model_copy(deep=True)

    def _run(self, context: HybridRuntimeContext, run_id: str, capture_audio: bool) -> None:
        def progress(case_id: str, backend: str, probe_session_id: str | None) -> None:
            with self._lock:
                self._status = self._status.model_copy(update={"case_id": case_id, "backend": backend, "probe_session_id": probe_session_id})

        try:
            completed, probe_id, text_gate_passed = asyncio.run(
                self._runner_factory().run(
                    context,
                    run_id,
                    capture_audio=capture_audio,
                    progress=progress,
                )
            )
        except Exception as exc:
            failure: dict[str, object] = {
                "probe_run_id": run_id,
                "error_type": type(exc).__name__,
            }
            if isinstance(exc, SpeechKitProviderError):
                failure.update(
                    failure_category=exc.category.value,
                    http_status=exc.status,
                )
            realtime_test_evidence.record("ia11_probe_failed", **failure)
            with self._lock:
                self._status = self._status.model_copy(
                    update={"state": HybridProbeState.FAIL, "message": f"{type(exc).__name__}: {str(exc)[:160]}", "case_id": None, "backend": None}
                )
            return
        with self._lock:
            final_state = HybridProbeState.REVIEW if text_gate_passed else HybridProbeState.FAIL
            final_message = (
                "Text gates passed; complete acoustic review in Test Evidence"
                if text_gate_passed
                else "One or more automatic semantic text gates failed"
            )
            self._status = self._status.model_copy(
                update={
                    "state": final_state,
                    "message": final_message,
                    "case_id": None,
                    "backend": None,
                    "completed_pairs": completed,
                    "probe_session_id": probe_id,
                }
            )

    def review(self, result: AcousticReview) -> HybridProbeStatus:
        with self._lock:
            if self._status.state is not HybridProbeState.REVIEW:
                raise ValueError("No completed hybrid probe is awaiting acoustic review")
            realtime_test_evidence.record_hybrid_review(self._status.probe_run_id or "unknown", result.value)
            state = HybridProbeState.PASS if result is AcousticReview.CLEAR else (HybridProbeState.FAIL if result is AcousticReview.FAIL else HybridProbeState.REVIEW)
            self._status = self._status.model_copy(update={"state": state, "message": f"Acoustic review recorded: {result.value}"})
            return self._status.model_copy(deep=True)

    def status(self) -> HybridProbeStatus:
        with self._lock:
            return self._status.model_copy(deep=True)


yandex_hybrid_probe = YandexHybridProbeAdapter()
