"""Shared historical SpeechKit transport and bounded protected v1 adapter."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode

SPEECHKIT_TTS_ENDPOINT = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
SPEECHKIT_RATE = 48_000
ORION_PROVIDER_RATE = 44_100
PROBE_TIMEOUT_S = 30.0
TX_TIMEOUT_S = 45.0
TX_GUARD_S = 0.250
SPEECHKIT_MAX_ATTEMPTS = 3
SPEECHKIT_RETRY_BACKOFF_S = (0.250, 0.750)
SPEECHKIT_RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})
SPEECHKIT_V1_PROBE_PROFILES = frozenset(
    {
        ("jane", "neutral"),
        ("jane", "evil"),
        ("ermil", "neutral"),
    }
)


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
            detail = ": ".join(
                item for item in (provider_code, provider_message) if item
            )
            message = f"{message}: {detail}"
        super().__init__(message)

    @classmethod
    def from_payload(
        cls, status: int, payload: bytes, *, secret: str
    ) -> SpeechKitProviderError:
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


@dataclass(frozen=True, slots=True)
class TestSemanticCase:
    case_id: str
    finalized_text: str
    required_groups: tuple[tuple[str, ...], ...]
    voice: str = "jane"
    role: str = "neutral"


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


@dataclass(frozen=True, slots=True)
class SpeechKitAttemptContext:
    run_id: str
    case_id: str
    response_id: str


SpeechKitAttemptObserver = Callable[[str, dict[str, object]], None]


def _speechkit_failure(exc: Exception) -> tuple[str, int | None, bool]:
    """Return a safe category, optional HTTP status, and retry decision."""

    import aiohttp

    if isinstance(exc, SpeechKitProviderError):
        return (
            exc.category.value,
            exc.status,
            exc.status in SPEECHKIT_RETRYABLE_HTTP_STATUSES,
        )
    if isinstance(exc, aiohttp.ConnectionTimeoutError):
        return "connect_timeout", None, True
    if isinstance(exc, aiohttp.SocketTimeoutError):
        return "read_timeout", None, True
    if isinstance(exc, aiohttp.ClientConnectorDNSError):
        return "dns_failure", None, True
    if isinstance(
        exc,
        (
            aiohttp.ClientConnectorCertificateError,
            aiohttp.ClientConnectorSSLError,
            aiohttp.ServerFingerprintMismatch,
        ),
    ):
        return "tls_validation_failure", None, False
    if isinstance(exc, aiohttp.ClientPayloadError):
        return "response_body_failure", None, True
    if isinstance(exc, aiohttp.ClientConnectionError):
        return "connection_failure", None, True
    if isinstance(exc, asyncio.TimeoutError):
        return "request_timeout", None, True
    if isinstance(exc, ValueError):
        return "invalid_audio", None, False
    return "local_error", None, False


class SpeechKitTtsClient:
    """Reusable async SpeechKit REST v1 transport with bounded transient retry."""

    def __init__(
        self,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._sleep = sleep
        self._session: Any = None

    @staticmethod
    def _timeout() -> Any:
        import aiohttp

        return aiohttp.ClientTimeout(total=PROBE_TIMEOUT_S, connect=5.0)

    async def __aenter__(self) -> SpeechKitTtsClient:
        import aiohttp

        if self._session is not None:
            raise RuntimeError("SpeechKit client session is already open")
        self._session = aiohttp.ClientSession(timeout=self._timeout())
        return self

    async def __aexit__(self, *_args: object) -> None:
        session = self._session
        self._session = None
        if session is not None:
            await session.close()

    _request = staticmethod(speechkit_request)

    async def _read_response(self, response: Any) -> bytes:
        # Legacy probe compatibility; the protected subclass uses a bounded reader.
        return await response.read()

    def _post(self, client: Any, url: str, headers: dict[str, str], body: bytes) -> Any:
        return client.post(url, headers=headers, data=body)

    async def synthesize(
        self,
        case: TestSemanticCase,
        api_key: str,
        *,
        attempt_context: SpeechKitAttemptContext | None = None,
        observer: SpeechKitAttemptObserver | None = None,
    ) -> tuple[bytes, str]:
        import aiohttp

        url, headers, body = self._request(case, api_key=api_key)
        if self._session is not None:
            return await self._synthesize_with_session(
                self._session,
                case,
                api_key,
                url,
                headers,
                body,
                attempt_context,
                observer,
            )
        async with aiohttp.ClientSession(timeout=self._timeout()) as client:
            return await self._synthesize_with_session(
                client,
                case,
                api_key,
                url,
                headers,
                body,
                attempt_context,
                observer,
            )

    async def _synthesize_with_session(
        self,
        client: Any,
        case: TestSemanticCase,
        api_key: str,
        url: str,
        headers: dict[str, str],
        body: bytes,
        attempt_context: SpeechKitAttemptContext | None,
        observer: SpeechKitAttemptObserver | None,
    ) -> tuple[bytes, str]:
        for attempt in range(1, SPEECHKIT_MAX_ATTEMPTS + 1):
            started = time.monotonic()
            self._emit_attempt(
                observer,
                "speechkit_attempt_started",
                attempt_context,
                case,
                attempt_number=attempt,
            )
            try:
                async with self._post(client, url, headers, body) as response:
                    payload = await self._read_response(response)
                    if response.status != 200:
                        raise SpeechKitProviderError.from_payload(
                            response.status,
                            payload,
                            secret=api_key,
                        )
                if not payload or len(payload) % 2:
                    raise ValueError("SpeechKit returned invalid LPCM audio")
            except asyncio.CancelledError:
                self._emit_attempt(
                    observer,
                    "speechkit_attempt_cancelled",
                    attempt_context,
                    case,
                    attempt_number=attempt,
                    elapsed_ms=(time.monotonic() - started) * 1000,
                    retry_scheduled=False,
                    retry_exhausted=False,
                )
                raise
            except Exception as exc:
                category, http_status, retryable = _speechkit_failure(exc)
                retry_scheduled = retryable and attempt < SPEECHKIT_MAX_ATTEMPTS
                self._emit_attempt(
                    observer,
                    "speechkit_attempt_failed",
                    attempt_context,
                    case,
                    attempt_number=attempt,
                    elapsed_ms=(time.monotonic() - started) * 1000,
                    failure_category=category,
                    http_status=http_status,
                    retry_scheduled=retry_scheduled,
                    retry_exhausted=retryable and not retry_scheduled,
                )
                if not retry_scheduled:
                    raise
                try:
                    await self._sleep(SPEECHKIT_RETRY_BACKOFF_S[attempt - 1])
                except asyncio.CancelledError:
                    self._emit_attempt(
                        observer,
                        "speechkit_retry_cancelled",
                        attempt_context,
                        case,
                        attempt_number=attempt + 1,
                    )
                    raise
                continue
            self._emit_attempt(
                observer,
                "speechkit_attempt_succeeded",
                attempt_context,
                case,
                attempt_number=attempt,
                elapsed_ms=(time.monotonic() - started) * 1000,
                pcm_bytes=len(payload),
                retry_scheduled=False,
                retry_exhausted=False,
            )
            return payload, case.finalized_text
        raise AssertionError("SpeechKit retry loop exhausted without a result")

    @staticmethod
    def _emit_attempt(
        observer: SpeechKitAttemptObserver | None,
        event: str,
        context: SpeechKitAttemptContext | None,
        case: TestSemanticCase,
        **fields: object,
    ) -> None:
        if observer is None:
            return
        safe: dict[str, object] = {
            "probe_run_id": context.run_id if context else "NOT OBSERVABLE",
            "probe_case_id": context.case_id if context else case.case_id,
            "response_id": context.response_id if context else "NOT OBSERVABLE",
            "requested_voice": case.voice,
            "requested_style": case.role,
            **fields,
        }
        observer(event, safe)


def normalize_speechkit_pcm(pcm48: bytes) -> bytes:
    from orion.srs_resampler import StreamingPcm16Resampler

    resampler = StreamingPcm16Resampler(SPEECHKIT_RATE, ORION_PROVIDER_RATE)
    return resampler.process(pcm48, end_of_input=True)


MAX_RAW_PCM_BYTES = 2_880_000
TTS_DEADLINE_S = 30.0


class TtsFailureCode(StrEnum):
    UNAVAILABLE = "tts_unavailable"
    TIMEOUT = "tts_timeout"
    REJECTED = "tts_rejected"
    ERROR = "tts_error"
    INVALID_PCM = "invalid_pcm"


class TtsAdapterError(ValueError):
    def __init__(self, code: TtsFailureCode) -> None:
        self.code = code
        super().__init__(code.value)


def protected_speechkit_request(
    case: TestSemanticCase, *, api_key: str
) -> tuple[str, dict[str, str], bytes]:
    """Verified en-US/john form. No transformation of caller text."""
    if not api_key or not case.finalized_text or len(case.finalized_text) > 4096:
        raise TtsAdapterError(TtsFailureCode.REJECTED)
    fields = {
        "text": case.finalized_text,
        "lang": "en-US",
        "voice": "john",
        "format": "lpcm",
        "sampleRateHertz": "48000",
        "speed": "1.0",
    }
    body = urlencode(fields).encode("utf-8")
    if len(body) > 15 * 1024:
        raise TtsAdapterError(TtsFailureCode.REJECTED)
    return (
        SPEECHKIT_TTS_ENDPOINT,
        {
            "Authorization": f"Api-Key {api_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        body,
    )


def validate_pcm48(payload: bytes) -> None:
    """Raw PCM has no self-describing header; reject known container/text bodies."""
    if (
        not isinstance(payload, bytes)
        or not payload
        or len(payload) % 2
        or len(payload) > MAX_RAW_PCM_BYTES
        or payload.startswith((b"RIFF", b"OggS", b"fLaC", b"ID3", b"{", b"[", b"<"))
    ):
        raise TtsAdapterError(TtsFailureCode.INVALID_PCM)


class _ProtectedClient(SpeechKitTtsClient):
    _request = staticmethod(protected_speechkit_request)

    def _post(self, client: Any, url: str, headers: dict[str, str], body: bytes) -> Any:
        return client.post(url, headers=headers, data=body, allow_redirects=False)

    async def _read_response(self, response: Any) -> bytes:
        limit = MAX_RAW_PCM_BYTES if response.status == 200 else 2048
        if response.status == 200:
            content_type = (
                response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            )
            if content_type not in {
                "application/octet-stream",
                "audio/x-pcm",
                "audio/pcm",
                "audio/lpcm",
            }:
                raise TtsAdapterError(TtsFailureCode.INVALID_PCM)
            if response.content_length is not None and response.content_length > limit:
                raise TtsAdapterError(TtsFailureCode.INVALID_PCM)
        payload = bytearray()
        async for chunk in response.content.iter_chunked(65536):
            if len(payload) + len(chunk) > limit:
                if response.status != 200:
                    return bytes(payload + chunk[: limit - len(payload)])
                raise TtsAdapterError(TtsFailureCode.INVALID_PCM)
            payload.extend(chunk)
        result = bytes(payload)
        if response.status == 200:
            validate_pcm48(result)
        return result


class SpeechKitTtsAdapter:
    """Protected English synthesis; shared retry engine, one bounded session."""

    def __init__(
        self,
        api_key: str,
        *,
        deadline_s: float = TTS_DEADLINE_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not api_key or not 0 < deadline_s <= TTS_DEADLINE_S:
            raise TtsAdapterError(TtsFailureCode.REJECTED)
        self._key = api_key
        self._deadline = deadline_s
        self._client = _ProtectedClient(sleep=sleep)
        self._lock = asyncio.Lock()
        self._opened = False
        self._closed = False

    async def synthesize(
        self,
        text: str,
        language: str,
        tx_id: str,
        observer: SpeechKitAttemptObserver | None = None,
    ) -> bytes:
        if language != "en-US":
            raise TtsAdapterError(TtsFailureCode.REJECTED)
        try:
            async with asyncio.timeout(self._deadline):
                async with self._lock:
                    if self._closed:
                        raise TtsAdapterError(TtsFailureCode.UNAVAILABLE)
                    if not self._opened:
                        await self._client.__aenter__()
                        self._opened = True
                case = TestSemanticCase(tx_id, text, (), "john", "neutral")
                pcm, _input_echo = await self._client.synthesize(
                    case,
                    self._key,
                    attempt_context=SpeechKitAttemptContext(tx_id, tx_id, tx_id),
                    observer=observer,
                )
                return pcm
        except asyncio.CancelledError:
            raise
        except TtsAdapterError:
            raise
        except asyncio.TimeoutError:
            raise TtsAdapterError(TtsFailureCode.TIMEOUT) from None
        except SpeechKitProviderError as exc:
            code = (
                TtsFailureCode.REJECTED
                if exc.status in (400, 401, 403)
                else TtsFailureCode.UNAVAILABLE
            )
            raise TtsAdapterError(code) from None
        except Exception as exc:
            category, _status, retryable = _speechkit_failure(exc)
            code = (
                TtsFailureCode.TIMEOUT
                if "timeout" in category
                else (TtsFailureCode.UNAVAILABLE if retryable else TtsFailureCode.ERROR)
            )
            raise TtsAdapterError(code) from None

    async def aclose(self) -> None:
        async with self._lock:
            self._closed = True
            self._key = ""
            if self._opened:
                self._opened = False
                await self._client.__aexit__()
