from __future__ import annotations

import asyncio
import hashlib
import threading
import time
import zipfile
from types import SimpleNamespace
from urllib.parse import parse_qs

import aiohttp
import pytest

import orion.yandex_hybrid_probe as hybrid_module
from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
from orion.yandex_hybrid_probe import (
    AcousticReview,
    HybridProbeRunner,
    HybridRuntimeContext,
    RealtimePresentationClient,
    SpeechKitFailureCategory,
    SpeechKitAttemptContext,
    SpeechKitProviderError,
    SpeechKitTtsClient,
    TestSemanticCase as SemanticCase,
    YandexHybridProbeAdapter,
    evaluate_semantics,
    hybrid_probe_cases,
    normalize_speechkit_pcm,
    speechkit_request,
)


def test_speechkit_request_is_direct_finalized_text_lpcm_and_has_no_folder_or_secret_repr() -> None:
    case = hybrid_probe_cases()[4]
    url, headers, body = speechkit_request(case, api_key="top-secret")
    fields = parse_qs(body.decode("utf-8"))
    assert url.endswith("/speech/v1/tts:synthesize")
    assert headers == {
        "Authorization": "Api-Key top-secret",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    assert fields == {
        "text": [case.finalized_text],
        "lang": ["ru-RU"],
        "voice": ["jane"],
        "emotion": ["evil"],
        "speed": ["1.0"],
        "format": ["lpcm"],
        "sampleRateHertz": ["48000"],
    }
    assert b"folder" not in body.lower()
    assert b"top-secret" not in body


class FakeSpeechKitResponse:
    def __init__(self, status: int, payload: bytes) -> None:
        self.status = status
        self._payload = payload

    async def __aenter__(self):  # noqa: ANN204
        return self

    async def __aexit__(self, *_args: object) -> None:
        pass

    async def read(self) -> bytes:
        return self._payload


class FakeSpeechKitSession:
    def __init__(self, response: FakeSpeechKitResponse) -> None:
        self.response = response
        self.request: tuple[str, dict[str, str], bytes] | None = None

    async def __aenter__(self):  # noqa: ANN204
        return self

    async def __aexit__(self, *_args: object) -> None:
        pass

    async def close(self) -> None:
        pass

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        data: bytes,
        trace_request_ctx: object | None = None,
    ) -> FakeSpeechKitResponse:
        del trace_request_ctx
        self.request = (url, headers, data)
        return self.response


class SequencedSpeechKitSession:
    def __init__(self, outcomes: list[FakeSpeechKitResponse | Exception]) -> None:
        self.outcomes = outcomes
        self.requests = 0
        self.closed = False

    async def __aenter__(self):  # noqa: ANN204
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.closed = True

    async def close(self) -> None:
        self.closed = True

    def post(self, *_args: object, **_kwargs: object) -> FakeSpeechKitResponse:
        self.requests += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class TraceAwareSpeechKitResponse:
    def __init__(
        self,
        session: TraceAwareSpeechKitSession,
        trace_request_ctx: object,
        *,
        payload: bytes,
        connection: str,
        fail_body_read: bool = False,
        omit_first_body_callback: bool = False,
    ) -> None:
        self.status = 200
        self._session = session
        self._trace_ctx = session.trace.trace_config_ctx(
            trace_request_ctx=trace_request_ctx,
        )
        self._payload = payload
        self._connection = connection
        self._fail_body_read = fail_body_read
        self._omit_first_body_callback = omit_first_body_callback

    async def _send(self, signal_name: str, **params: object) -> None:
        signal = getattr(self._session.trace, signal_name)
        for callback in signal:
            await callback(self._session, self._trace_ctx, SimpleNamespace(**params))

    async def __aenter__(self):  # noqa: ANN204
        await self._send("on_request_start")
        if self._connection == "connect_failure":
            await self._send("on_connection_create_start")
            raise aiohttp.ConnectionTimeoutError("connect")
        if self._connection == "new":
            await self._send("on_connection_create_start")
            await self._send("on_dns_resolvehost_start")
            await self._send("on_dns_resolvehost_end")
            await self._send("on_connection_create_end")
        elif self._connection == "reused":
            await self._send("on_connection_reuseconn")
        await self._send("on_request_end")
        return self

    async def __aexit__(self, *_args: object) -> None:
        pass

    async def read(self) -> bytes:
        if self._fail_body_read:
            raise aiohttp.ClientPayloadError("truncated")
        if not self._omit_first_body_callback:
            await self._send("on_response_chunk_received", chunk=self._payload)
        return self._payload


class TraceAwareSpeechKitSession:
    def __init__(
        self,
        trace: aiohttp.TraceConfig,
        *,
        outcomes: list[str],
        payload: bytes = bytes(960),
        fail_body_read: bool = False,
        omit_first_body_callback: bool = False,
    ) -> None:
        self.trace = trace
        self.outcomes = outcomes
        self.payload = payload
        self.fail_body_read = fail_body_read
        self.omit_first_body_callback = omit_first_body_callback

    async def __aenter__(self):  # noqa: ANN204
        return self

    async def __aexit__(self, *_args: object) -> None:
        pass

    async def close(self) -> None:
        pass

    def post(self, *_args: object, **kwargs: object) -> TraceAwareSpeechKitResponse:
        return TraceAwareSpeechKitResponse(
            self,
            kwargs["trace_request_ctx"],
            payload=self.payload,
            connection=self.outcomes.pop(0),
            fail_body_read=self.fail_body_read,
            omit_first_body_callback=self.omit_first_body_callback,
        )


def _trace_session_factory(
    monkeypatch,
    *,
    outcomes: list[str],
    payload: bytes = bytes(960),
    fail_body_read: bool = False,
    omit_first_body_callback: bool = False,
) -> None:  # noqa: ANN001
    def factory(**kwargs: object) -> TraceAwareSpeechKitSession:
        trace = kwargs["trace_configs"]
        assert isinstance(trace, list)
        assert len(trace) == 1
        return TraceAwareSpeechKitSession(
            trace[0],
            outcomes=outcomes,
            payload=payload,
            fail_body_read=fail_body_read,
            omit_first_body_callback=omit_first_body_callback,
        )

    monkeypatch.setattr(aiohttp, "ClientSession", factory)


def _attempt_context() -> SpeechKitAttemptContext:
    return SpeechKitAttemptContext("run123", "heading-137", "ia11-run123-heading-137-speechkit")


async def _no_sleep(_seconds: float) -> None:
    pass


@pytest.mark.parametrize(
    ("status", "category", "message"),
    [
        (401, SpeechKitFailureCategory.UNAUTHORIZED, "yc.ai.speechkitTts.execute"),
        (403, SpeechKitFailureCategory.FORBIDDEN, "ai.speechkit-tts.user"),
        (400, SpeechKitFailureCategory.MALFORMED_REQUEST, "rejected"),
        (503, SpeechKitFailureCategory.PROVIDER_UNAVAILABLE, "unavailable"),
    ],
)
def test_speechkit_http_failures_are_safe_and_actionable(
    monkeypatch,
    status: int,
    category: SpeechKitFailureCategory,
    message: str,
) -> None:  # noqa: ANN001
    async def scenario() -> None:
        session = FakeSpeechKitSession(FakeSpeechKitResponse(status, b'{"provider":"detail"}'))
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_kwargs: session)
        with pytest.raises(SpeechKitProviderError) as caught:
            await SpeechKitTtsClient().synthesize(hybrid_probe_cases()[0], "top-secret")
        assert caught.value.status == status
        assert caught.value.category is category
        assert message in str(caught.value)
        assert "top-secret" not in str(caught.value)
        assert "top-secret" not in repr(caught.value)
        assert "provider" not in str(caught.value)

    asyncio.run(scenario())


def test_speechkit_400_surfaces_only_bounded_allowlisted_provider_detail(monkeypatch) -> None:  # noqa: ANN001
    async def scenario() -> None:
        payload = (
            b'{"error_code":"BAD_REQUEST","error_message":"Unsupported voice is requested: dasha; '
            b'top-secret","provider_internal":"must-not-appear"}'
        )
        session = FakeSpeechKitSession(FakeSpeechKitResponse(400, payload))
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_kwargs: session)
        with pytest.raises(SpeechKitProviderError) as caught:
            await SpeechKitTtsClient().synthesize(hybrid_probe_cases()[0], "top-secret")
        assert caught.value.provider_code == "BAD_REQUEST"
        assert caught.value.provider_message == "Unsupported voice is requested: dasha; <redacted>"
        assert "Unsupported voice is requested: dasha" in str(caught.value)
        assert "provider_internal" not in str(caught.value)
        assert "top-secret" not in str(caught.value)
        assert "top-secret" not in repr(caught.value)

    asyncio.run(scenario())


def test_speechkit_success_returns_bounded_lpcm_and_uses_api_key_header(monkeypatch) -> None:  # noqa: ANN001
    async def scenario() -> None:
        pcm = bytes(960)
        session = FakeSpeechKitSession(FakeSpeechKitResponse(200, pcm))
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_kwargs: session)
        events: list[tuple[str, dict[str, object]]] = []
        audio, text = await SpeechKitTtsClient().synthesize(
            hybrid_probe_cases()[0],
            "top-secret",
            attempt_context=_attempt_context(),
            observer=lambda event, fields: events.append((event, fields)),
        )
        assert audio == pcm
        assert text == hybrid_probe_cases()[0].finalized_text
        assert session.request is not None
        _url, headers, body = session.request
        assert headers["Authorization"] == "Api-Key top-secret"
        assert b"top-secret" not in body
        assert [event for event, _fields in events if event.startswith("speechkit_attempt_")] == [
            "speechkit_attempt_started",
            "speechkit_attempt_succeeded",
        ]
        assert events[-1][1]["attempt_number"] == 1
        assert events[-1][1]["pcm_bytes"] == len(pcm)

    asyncio.run(scenario())


def test_speechkit_success_emits_ordered_phase_telemetry(monkeypatch) -> None:  # noqa: ANN001
    async def scenario() -> None:
        pcm = bytes(range(256)) * 4
        _trace_session_factory(monkeypatch, outcomes=["new"], payload=pcm)
        events: list[tuple[str, dict[str, object]]] = []
        outer_started = time.monotonic()
        audio, _text = await SpeechKitTtsClient().synthesize(
            hybrid_probe_cases()[0],
            "top-secret",
            attempt_context=_attempt_context(),
            observer=lambda event, fields: events.append((event, fields)),
        )
        outer_ms = (time.monotonic() - outer_started) * 1000

        assert audio == pcm
        phase_events = [
            event
            for event, _fields in events
            if event.startswith("speechkit_tts_")
        ]
        assert phase_events == [
            "speechkit_tts_client_created",
            "speechkit_tts_session_created",
            "speechkit_tts_request_dispatched",
            "speechkit_tts_connection_acquire_started",
            "speechkit_tts_dns_started",
            "speechkit_tts_dns_completed",
            "speechkit_tts_connection_acquired",
            "speechkit_tts_response_headers_received",
            "speechkit_tts_body_chunk_callback",
            "speechkit_tts_body_completed",
            "speechkit_tts_pcm_validated",
            "speechkit_tts_attempt_completed",
        ]
        completed = next(
            fields
            for event, fields in events
            if event == "speechkit_tts_attempt_completed"
        )
        assert completed["connection_classification"] == "NEW_CONNECTION"
        session_created = next(
            fields for event, fields in events if event == "speechkit_tts_session_created"
        )
        assert isinstance(session_created["session_create_ms"], float)
        assert isinstance(completed["request_to_headers_ms"], float)
        assert completed["request_to_first_body_ms"] == "NOT_OBSERVABLE"
        assert completed["headers_to_first_body_ms"] == "NOT_OBSERVABLE"
        assert completed["first_body_to_complete_ms"] == "NOT_OBSERVABLE"
        assert isinstance(completed["body_read_ms"], float)
        assert isinstance(completed["pcm_validation_ms"], float)
        assert 0 <= completed["total_attempt_ms"] <= outer_ms + 5
        assert completed["latest_tts_phase"] == "pcm_validated"
        validated = next(
            fields for event, fields in events if event == "speechkit_tts_pcm_validated"
        )
        assert validated["raw_response_bytes"] == len(pcm)
        assert validated["validated_pcm_bytes"] == len(pcm)
        assert validated["sample_rate_hz"] == 48_000
        assert validated["channels"] == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("connection", "expected"),
    [
        ("new", "NEW_CONNECTION"),
        ("reused", "REUSED_CONNECTION"),
        ("none", "NOT_OBSERVABLE"),
    ],
)
def test_speechkit_connection_classification_is_trace_derived(
    monkeypatch,
    connection: str,
    expected: str,
) -> None:  # noqa: ANN001
    async def scenario() -> None:
        _trace_session_factory(monkeypatch, outcomes=[connection])
        events: list[tuple[str, dict[str, object]]] = []
        await SpeechKitTtsClient().synthesize(
            hybrid_probe_cases()[0],
            "top-secret",
            attempt_context=_attempt_context(),
            observer=lambda event, fields: events.append((event, fields)),
        )
        completed = next(
            fields
            for event, fields in events
            if event == "speechkit_tts_attempt_completed"
        )
        assert completed["connection_classification"] == expected
        if connection == "reused":
            assert completed["connection_acquire_ms"] == "NOT_OBSERVABLE"

    asyncio.run(scenario())


def test_speechkit_missing_body_chunk_trace_is_nonfatal_and_first_byte_is_not_invented(
    monkeypatch,
) -> None:  # noqa: ANN001
    async def scenario() -> None:
        pcm = bytes(960)
        _trace_session_factory(
            monkeypatch,
            outcomes=["new"],
            payload=pcm,
            omit_first_body_callback=True,
        )
        events: list[tuple[str, dict[str, object]]] = []
        audio, _text = await SpeechKitTtsClient().synthesize(
            hybrid_probe_cases()[0],
            "top-secret",
            attempt_context=_attempt_context(),
            observer=lambda event, fields: events.append((event, fields)),
        )
        assert audio == pcm
        assert not any(event == "speechkit_tts_body_chunk_callback" for event, _ in events)
        completed = next(
            fields
            for event, fields in events
            if event == "speechkit_tts_attempt_completed"
        )
        assert completed["headers_to_first_body_ms"] == "NOT_OBSERVABLE"
        assert completed["first_body_to_complete_ms"] == "NOT_OBSERVABLE"

    asyncio.run(scenario())


def test_speechkit_failed_connect_records_last_bounded_phase(monkeypatch) -> None:  # noqa: ANN001
    async def scenario() -> None:
        _trace_session_factory(
            monkeypatch,
            outcomes=["connect_failure", "connect_failure", "connect_failure"],
        )
        events: list[tuple[str, dict[str, object]]] = []
        with pytest.raises(aiohttp.ConnectionTimeoutError):
            await SpeechKitTtsClient(sleep=_no_sleep).synthesize(
                hybrid_probe_cases()[0],
                "top-secret",
                attempt_context=_attempt_context(),
                observer=lambda event, fields: events.append((event, fields)),
            )
        completions = [
            fields
            for event, fields in events
            if event == "speechkit_tts_attempt_completed"
        ]
        assert [item["attempt_number"] for item in completions] == [1, 2, 3]
        assert all(item["status"] == "failed" for item in completions)
        assert all(item["failure_category"] == "connect_timeout" for item in completions)
        assert all(item["latest_tts_phase"] == "connection_acquire_started" for item in completions)
        assert all(item["connection_classification"] == "NOT_OBSERVABLE" for item in completions)

    asyncio.run(scenario())


def test_speechkit_failed_body_read_records_headers_without_body_completion(monkeypatch) -> None:  # noqa: ANN001
    async def scenario() -> None:
        _trace_session_factory(
            monkeypatch,
            outcomes=["new", "new", "new"],
            fail_body_read=True,
        )
        events: list[tuple[str, dict[str, object]]] = []
        with pytest.raises(aiohttp.ClientPayloadError):
            await SpeechKitTtsClient(sleep=_no_sleep).synthesize(
                hybrid_probe_cases()[0],
                "top-secret",
                attempt_context=_attempt_context(),
                observer=lambda event, fields: events.append((event, fields)),
            )
        completions = [
            fields
            for event, fields in events
            if event == "speechkit_tts_attempt_completed"
        ]
        assert len(completions) == 3
        assert all(item["failure_category"] == "response_body_failure" for item in completions)
        assert all(item["latest_tts_phase"] == "body_read_started" for item in completions)
        assert not any(event == "speechkit_tts_body_completed" for event, _ in events)

    asyncio.run(scenario())


def test_speechkit_invalid_pcm_records_validation_failure_phase(monkeypatch) -> None:  # noqa: ANN001
    async def scenario() -> None:
        _trace_session_factory(monkeypatch, outcomes=["new"], payload=b"x")
        events: list[tuple[str, dict[str, object]]] = []
        with pytest.raises(ValueError, match="invalid LPCM"):
            await SpeechKitTtsClient(sleep=_no_sleep).synthesize(
                hybrid_probe_cases()[0],
                "top-secret",
                attempt_context=_attempt_context(),
                observer=lambda event, fields: events.append((event, fields)),
            )
        assert any(event == "speechkit_tts_body_completed" for event, _ in events)
        assert any(event == "speechkit_tts_pcm_validation_failed" for event, _ in events)
        completed = next(
            fields
            for event, fields in events
            if event == "speechkit_tts_attempt_completed"
        )
        assert completed["failure_category"] == "invalid_audio"
        assert completed["latest_tts_phase"] == "pcm_validation_failed"
        assert isinstance(completed["pcm_validation_ms"], float)

    asyncio.run(scenario())


def test_speechkit_context_reuses_one_session_across_syntheses(monkeypatch) -> None:  # noqa: ANN001
    async def scenario() -> None:
        session = SequencedSpeechKitSession(
            [FakeSpeechKitResponse(200, bytes(960)), FakeSpeechKitResponse(200, bytes(960))]
        )
        sessions_created = 0

        def session_factory(**_kwargs):  # noqa: ANN202
            nonlocal sessions_created
            sessions_created += 1
            return session

        monkeypatch.setattr(aiohttp, "ClientSession", session_factory)
        async with SpeechKitTtsClient() as client:
            await client.synthesize(hybrid_probe_cases()[0], "top-secret")
            await client.synthesize(hybrid_probe_cases()[1], "top-secret")
        assert sessions_created == 1
        assert session.requests == 2
        assert session.closed

    asyncio.run(scenario())


def test_speechkit_connection_timeout_then_success_is_bounded_and_observable(monkeypatch) -> None:  # noqa: ANN001
    async def scenario() -> None:
        session = SequencedSpeechKitSession(
            [aiohttp.ConnectionTimeoutError("connect"), FakeSpeechKitResponse(200, bytes(960))]
        )
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_kwargs: session)
        events: list[tuple[str, dict[str, object]]] = []
        audio, _text = await SpeechKitTtsClient(sleep=_no_sleep).synthesize(
            hybrid_probe_cases()[0],
            "top-secret",
            attempt_context=_attempt_context(),
            observer=lambda event, fields: events.append((event, fields)),
        )
        assert audio == bytes(960)
        assert session.requests == 2
        assert [event for event, _fields in events if event.startswith("speechkit_attempt_")] == [
            "speechkit_attempt_started",
            "speechkit_attempt_failed",
            "speechkit_attempt_started",
            "speechkit_attempt_succeeded",
        ]
        failure = next(fields for event, fields in events if event == "speechkit_attempt_failed")
        assert failure["failure_category"] == "connect_timeout"
        assert failure["retry_scheduled"] is True
        assert events[-1][1]["attempt_number"] == 2

    asyncio.run(scenario())


def test_speechkit_two_transient_failures_then_success(monkeypatch) -> None:  # noqa: ANN001
    async def scenario() -> None:
        session = SequencedSpeechKitSession(
            [
                aiohttp.ConnectionTimeoutError("connect"),
                aiohttp.ServerDisconnectedError("reset"),
                FakeSpeechKitResponse(200, bytes(960)),
            ]
        )
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_kwargs: session)
        events: list[tuple[str, dict[str, object]]] = []
        await SpeechKitTtsClient(sleep=_no_sleep).synthesize(
            hybrid_probe_cases()[0],
            "top-secret",
            attempt_context=_attempt_context(),
            observer=lambda event, fields: events.append((event, fields)),
        )
        assert session.requests == 3
        failures = [fields for event, fields in events if event == "speechkit_attempt_failed"]
        assert [item["failure_category"] for item in failures] == [
            "connect_timeout",
            "connection_failure",
        ]
        assert events[-1][1]["attempt_number"] == 3

    asyncio.run(scenario())


def test_speechkit_all_transient_attempts_exhausted(monkeypatch) -> None:  # noqa: ANN001
    async def scenario() -> None:
        session = SequencedSpeechKitSession(
            [aiohttp.ConnectionTimeoutError("connect") for _index in range(3)]
        )
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_kwargs: session)
        events: list[tuple[str, dict[str, object]]] = []
        with pytest.raises(aiohttp.ConnectionTimeoutError):
            await SpeechKitTtsClient(sleep=_no_sleep).synthesize(
                hybrid_probe_cases()[0],
                "top-secret",
                attempt_context=_attempt_context(),
                observer=lambda event, fields: events.append((event, fields)),
            )
        assert session.requests == 3
        assert events[-1][0] == "speechkit_attempt_failed"
        assert events[-1][1]["retry_scheduled"] is False
        assert events[-1][1]["retry_exhausted"] is True

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [429, 500, 503])
def test_speechkit_retryable_http_status_then_success(monkeypatch, status: int) -> None:  # noqa: ANN001
    async def scenario() -> None:
        session = SequencedSpeechKitSession(
            [FakeSpeechKitResponse(status, b"{}"), FakeSpeechKitResponse(200, bytes(960))]
        )
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_kwargs: session)
        events: list[tuple[str, dict[str, object]]] = []
        await SpeechKitTtsClient(sleep=_no_sleep).synthesize(
            hybrid_probe_cases()[0],
            "top-secret",
            attempt_context=_attempt_context(),
            observer=lambda event, fields: events.append((event, fields)),
        )
        assert session.requests == 2
        failure = next(fields for event, fields in events if event == "speechkit_attempt_failed")
        assert failure["http_status"] == status
        assert failure["retry_scheduled"] is True

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [400, 401, 403])
def test_speechkit_nonretryable_http_status_fails_once(monkeypatch, status: int) -> None:  # noqa: ANN001
    async def scenario() -> None:
        session = SequencedSpeechKitSession([FakeSpeechKitResponse(status, b"{}")])
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_kwargs: session)
        events: list[tuple[str, dict[str, object]]] = []
        with pytest.raises(SpeechKitProviderError):
            await SpeechKitTtsClient(sleep=_no_sleep).synthesize(
                hybrid_probe_cases()[0],
                "top-secret",
                attempt_context=_attempt_context(),
                observer=lambda event, fields: events.append((event, fields)),
            )
        assert session.requests == 1
        assert events[-1][1]["retry_scheduled"] is False
        assert events[-1][1]["retry_exhausted"] is False

    asyncio.run(scenario())


def test_speechkit_unsupported_profile_makes_zero_http_attempts(monkeypatch) -> None:  # noqa: ANN001
    async def scenario() -> None:
        monkeypatch.setattr(
            aiohttp,
            "ClientSession",
            lambda **_kwargs: pytest.fail("HTTP session must not be created"),
        )
        case = SemanticCase("unsupported", "Проверка.", (("провер",),), "dasha", "neutral")
        with pytest.raises(ValueError, match="not supported"):
            await SpeechKitTtsClient().synthesize(case, "top-secret")

    asyncio.run(scenario())


def test_speechkit_cancellation_during_backoff_exits_cleanly(monkeypatch) -> None:  # noqa: ANN001
    async def cancel_backoff(_seconds: float) -> None:
        raise asyncio.CancelledError

    async def scenario() -> None:
        session = SequencedSpeechKitSession([aiohttp.ConnectionTimeoutError("connect")])
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_kwargs: session)
        events: list[tuple[str, dict[str, object]]] = []
        with pytest.raises(asyncio.CancelledError):
            await SpeechKitTtsClient(sleep=cancel_backoff).synthesize(
                hybrid_probe_cases()[0],
                "top-secret",
                attempt_context=_attempt_context(),
                observer=lambda event, fields: events.append((event, fields)),
            )
        assert session.requests == 1
        assert events[-1][0] == "speechkit_retry_cancelled"
        assert events[-1][1]["attempt_number"] == 2

    asyncio.run(scenario())


def test_speechkit_attempt_evidence_never_contains_secret(monkeypatch) -> None:  # noqa: ANN001
    async def scenario() -> None:
        payload = b'{"error_code":"BAD_REQUEST","error_message":"top-secret"}'
        session = SequencedSpeechKitSession([FakeSpeechKitResponse(400, payload)])
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_kwargs: session)
        events: list[tuple[str, dict[str, object]]] = []
        with pytest.raises(SpeechKitProviderError):
            await SpeechKitTtsClient(sleep=_no_sleep).synthesize(
                hybrid_probe_cases()[0],
                "top-secret",
                attempt_context=_attempt_context(),
                observer=lambda event, fields: events.append((event, fields)),
            )
        assert "top-secret" not in repr(events)
        assert "Authorization" not in repr(events)

    asyncio.run(scenario())


def test_all_hybrid_cases_are_one_concept_and_semantically_corruption_sensitive() -> None:
    cases = hybrid_probe_cases()
    assert len(cases) == 10
    assert len({case.case_id for case in cases}) == len(cases)
    assert [case.voice for case in cases[:3]] == ["jane", "ermil", "jane"]
    assert [(case.voice, case.role) for case in cases[3:6]] == [
        ("jane", "neutral"),
        ("jane", "evil"),
        ("jane", "neutral"),
    ]
    for case in cases:
        assert evaluate_semantics(case, case.finalized_text)["status"] == "PASS"
        assert evaluate_semantics(case, "Факт намеренно поврежден.")["status"] == "FAIL"


def test_every_hybrid_case_uses_a_confirmed_speechkit_v1_profile() -> None:
    profiles = {(case.voice, case.role) for case in hybrid_probe_cases()}
    assert profiles == {
        ("jane", "neutral"),
        ("jane", "evil"),
        ("ermil", "neutral"),
    }


def test_speechkit_request_rejects_v3_only_voice_before_network() -> None:
    case = SemanticCase("unsupported", "Проверка.", (("провер",),), "dasha", "neutral")
    with pytest.raises(ValueError, match="not supported by the SpeechKit REST v1 probe"):
        speechkit_request(case, api_key="top-secret")


def test_speechkit_pcm_is_normalized_to_existing_orion_44100_boundary() -> None:
    pcm48 = bytes(48_000 * 2)
    pcm44 = normalize_speechkit_pcm(pcm48)
    assert len(pcm44) % 2 == 0
    assert 44_000 <= len(pcm44) // 2 <= 44_200


def test_realtime_config_wait_ignores_multiple_stale_session_updated_events(monkeypatch) -> None:  # noqa: ANN001
    async def scenario() -> None:
        client = RealtimePresentationClient("secret", "folder")
        events = iter(
            (
                {"type": "session.updated", "session": {"audio": {"output": {"voice": "dasha", "role": "neutral"}}}},
                {"type": "session.updated", "session": {"audio": {"output": {"voice": "alexander", "role": "neutral"}}}},
                {"type": "session.updated", "session": {"id": "probe", "audio": {"output": {"voice": "julia", "role": "strict"}}}},
            )
        )

        async def receive(_deadline: float):  # noqa: ANN202
            return next(events)

        monkeypatch.setattr(client, "_receive_event", receive)
        session, observed = await client._await_effective_config("julia", "strict")
        assert session["id"] == "probe"
        assert observed == [
            {"voice": "dasha", "role": "neutral"},
            {"voice": "alexander", "role": "neutral"},
            {"voice": "julia", "role": "strict"},
        ]

    asyncio.run(scenario())


class FakeEvidence:
    current_context_version = "ctx-before"

    def __init__(self) -> None:
        self.cases: list[tuple[str, str]] = []
        self.events: list[tuple[str, dict[str, object]]] = []
        self.isolation: dict[str, object] = {}

    def record(self, event: str, **fields: object) -> None:
        self.events.append((event, fields))

    def record_hybrid_run(self, **_fields: object) -> None:
        pass

    def record_hybrid_config(self, *_args: object) -> None:
        pass

    def record_hybrid_audio(self, **_fields: object) -> None:
        raise AssertionError("audio capture is disabled")

    def record_hybrid_case(self, **fields: object) -> None:
        self.cases.append((str(fields["case"].case_id), str(fields["backend"])))  # type: ignore[attr-defined]

    def record_hybrid_recovery(self, _run_id: str, result: dict[str, object]) -> None:
        assert result["critical_case_interrupted"] is False

    def record_hybrid_isolation(self, **fields: object) -> None:
        self.isolation = fields


class FakeRealtime:
    session_id = "probe-session"

    async def __aenter__(self):  # noqa: ANN204
        return self

    async def __aexit__(self, *_args: object) -> None:
        pass

    async def apply_voice(self, voice: str, role: str) -> list[dict[str, str]]:
        return [{"voice": "stale", "role": "stale"}, {"voice": voice, "role": role}]

    async def synthesize(self, case: SemanticCase):  # noqa: ANN201
        return bytes(200), case.finalized_text, {"provider_first_audio_ms": 1.0, "provider_complete_ms": 2.0}

    async def interruption_recovery(self) -> dict[str, object]:
        return {"cancel_sent": True, "cancelled_status": "cancelled", "recovery_text_validation": {"status": "PASS"}, "critical_case_interrupted": False}


class FakeSpeechKit:
    async def __aenter__(self):  # noqa: ANN204
        return self

    async def __aexit__(self, *_args: object) -> None:
        pass

    async def synthesize(
        self,
        case: SemanticCase,
        _api_key: str,
        **_kwargs: object,
    ) -> tuple[bytes, str]:
        return bytes(220), case.finalized_text


class SerialEndpoint:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.active = False

    def transmit_probe_audio(self, response_id: str, pcm44: bytes, timeout_s: float) -> dict[str, float]:
        assert not self.active
        assert pcm44 and timeout_s > 0
        self.active = True
        self.calls.append(response_id)
        self.active = False
        return {"queue_to_first_tx_ms": 3.0, "queue_to_complete_ms": 4.0}


def test_runner_serializes_twenty_ab_transmissions_and_preserves_session_isolation(monkeypatch) -> None:  # noqa: ANN001
    async def scenario() -> None:
        evidence = FakeEvidence()
        monkeypatch.setattr(hybrid_module, "realtime_test_evidence", evidence)
        endpoint = SerialEndpoint()

        async def no_sleep(_seconds: float) -> None:
            pass

        runner = HybridProbeRunner(
            speechkit_factory=FakeSpeechKit,
            realtime_factory=lambda _key, _folder: FakeRealtime(),
            sleep=no_sleep,
        )
        completed, probe_id, text_gate_passed = await runner.run(
            HybridRuntimeContext("secret", "folder", endpoint, "main-session", "ctx-before"),
            "run123",
            capture_audio=False,
            progress=lambda *_args: None,
        )
        assert completed == 20
        assert probe_id == "probe-session"
        assert text_gate_passed
        assert len(endpoint.calls) == 20
        assert all(endpoint.calls[index].endswith("-realtime") for index in range(0, 20, 2))
        assert all(endpoint.calls[index].endswith("-speechkit") for index in range(1, 20, 2))
        assert len(evidence.cases) == 20
        assert evidence.isolation["main_session_id"] == "main-session"
        assert evidence.isolation["probe_session_id"] == "probe-session"

    asyncio.run(scenario())


def test_runner_retry_transmits_successful_speechkit_audio_exactly_once(monkeypatch) -> None:  # noqa: ANN001
    async def scenario() -> None:
        evidence = FakeEvidence()
        monkeypatch.setattr(hybrid_module, "realtime_test_evidence", evidence)
        monkeypatch.setattr(hybrid_module, "hybrid_probe_cases", lambda: (hybrid_probe_cases()[0],))
        session = SequencedSpeechKitSession(
            [aiohttp.ConnectionTimeoutError("connect"), FakeSpeechKitResponse(200, bytes(960))]
        )
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_kwargs: session)
        endpoint = SerialEndpoint()
        runner = HybridProbeRunner(
            speechkit_factory=lambda: SpeechKitTtsClient(sleep=_no_sleep),
            realtime_factory=lambda _key, _folder: FakeRealtime(),
            sleep=_no_sleep,
        )
        completed, _probe_id, passed = await runner.run(
            HybridRuntimeContext("secret", "folder", endpoint, "main", "ctx"),
            "run123",
            capture_audio=False,
            progress=lambda *_args: None,
        )
        assert completed == 2
        assert passed
        assert session.requests == 2
        assert endpoint.calls == [
            "ia11-run123-heading-137-realtime",
            "ia11-run123-heading-137-speechkit",
        ]
        assert [event for event, _fields in evidence.events].count(
            "speechkit_attempt_succeeded"
        ) == 1

    asyncio.run(scenario())


def test_speechkit_failure_is_fail_closed_without_realtime_fallback(monkeypatch) -> None:  # noqa: ANN001
    class RejectingSpeechKit:
        async def __aenter__(self):  # noqa: ANN204
            return self

        async def __aexit__(self, *_args: object) -> None:
            pass

        async def synthesize(
            self,
            _case: SemanticCase,
            _api_key: str,
            **_kwargs: object,
        ) -> tuple[bytes, str]:
            raise SpeechKitProviderError(401)

    async def scenario() -> None:
        evidence = FakeEvidence()
        monkeypatch.setattr(hybrid_module, "realtime_test_evidence", evidence)
        endpoint = SerialEndpoint()
        runner = HybridProbeRunner(
            speechkit_factory=RejectingSpeechKit,
            realtime_factory=lambda _key, _folder: FakeRealtime(),
            sleep=lambda _seconds: asyncio.sleep(0),
        )
        with pytest.raises(SpeechKitProviderError):
            await runner.run(
                HybridRuntimeContext("top-secret", "folder", endpoint, "main", "ctx"),
                "run123",
                capture_audio=False,
                progress=lambda *_args: None,
            )
        assert endpoint.calls == ["ia11-run123-heading-137-realtime"]
        assert evidence.cases == [("heading-137", "realtime")]

    asyncio.run(scenario())


def test_adapter_records_redacted_speechkit_failure_for_launcher_and_evidence(monkeypatch) -> None:  # noqa: ANN001
    recorded: list[tuple[str, dict[str, object]]] = []

    class Status:
        active = True

    class Evidence:
        def status(self):  # noqa: ANN201
            return Status()

        def record(self, event: str, **fields: object) -> None:
            recorded.append((event, fields))

    class Runner:
        async def run(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            raise SpeechKitProviderError(401)

    monkeypatch.setattr(hybrid_module, "realtime_test_evidence", Evidence())
    adapter = YandexHybridProbeAdapter(runner_factory=Runner)
    adapter.attach(HybridRuntimeContext("top-secret", "folder", SerialEndpoint(), "main", None))
    adapter.start()
    deadline = time.monotonic() + 1.0
    while adapter.status().state.value == "running" and time.monotonic() < deadline:
        time.sleep(0.01)
    status = adapter.status()
    assert status.state.value == "fail"
    assert "yc.ai.speechkitTts.execute" in status.message
    assert "top-secret" not in status.message
    assert recorded == [
        (
            "ia11_probe_failed",
            {
                "probe_run_id": status.probe_run_id,
                "error_type": "SpeechKitProviderError",
                "failure_category": "unauthorized_credential_or_scope",
                "http_status": 401,
            },
        )
    ]
    assert "top-secret" not in repr(recorded)


def test_audio_evidence_is_opt_in_bounded_correlated_and_contains_no_mic_or_radio_audio(tmp_path) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(provider="yandex", transport="srs")
    recorder.record_hybrid_run(
        run_id="run123",
        main_session_id="main",
        probe_session_id="probe",
        context_version_before=None,
    )
    pcm = b"\x01\x00" * 441
    recorder.record_hybrid_audio(
        run_id="run123",
        case_id="heading-137",
        backend="speechkit",
        response_id="response-1",
        pcm44=pcm,
    )
    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        manifest = archive.read("manifest.txt").decode()
        summary = archive.read("ia11-summary.json").decode()
        wav = archive.read("ia11-audio/heading-137-speechkit.wav")
    assert names == sorted(names)
    assert "synthetic_probe_audio_included=true" in manifest
    assert "microphone_audio_included=false" in manifest
    assert "unrelated_srs_audio_included=false" in manifest
    assert hashlib.sha256(wav).hexdigest() in summary
    assert "response-1" in summary


def test_speechkit_attempt_observability_is_bounded_and_secret_free(tmp_path) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(provider="yandex", transport="srs")
    recorder.record(
        "speechkit_attempt_failed",
        probe_run_id="run123",
        probe_case_id="heading-137",
        response_id="ia11-run123-heading-137-speechkit",
        requested_voice="jane",
        requested_style="neutral",
        attempt_number=1,
        elapsed_ms=5001.25,
        failure_category="connect_timeout",
        http_status=None,
        retry_scheduled=True,
        retry_exhausted=False,
        unsafe_detail="Authorization: Api-Key top-secret",
    )
    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        events = archive.read("events.jsonl").decode("utf-8")
    assert "speechkit_attempt_failed" in events
    assert '"attempt_number": 1' in events
    assert '"failure_category": "connect_timeout"' in events
    assert '"retry_scheduled": true' in events
    assert "unsafe_detail" not in events
    assert "top-secret" not in events
    assert "Authorization" not in events


def test_speechkit_phase_evidence_keeps_only_safe_bounded_scalars(tmp_path) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(provider="yandex", transport="srs")
    recorder.record(
        "speechkit_tts_attempt_completed",
        probe_run_id="run123",
        probe_case_id="heading-137",
        response_id="live-golden-run123-mixed-ru-1",
        attempt_number=1,
        tts_provider="speechkit_rest_v1",
        connection_classification="NEW_CONNECTION",
        latest_tts_phase="pcm_validated",
        request_to_headers_ms=4200.25,
        request_to_first_body_ms="NOT_OBSERVABLE",
        body_read_ms=11.5,
        pcm_validation_ms=0.05,
        total_attempt_ms=4212.0,
        unsafe_headers="Authorization: Api-Key top-secret",
    )
    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        events = archive.read("events.jsonl").decode("utf-8")
    assert '"tts_provider": "speechkit_rest_v1"' in events
    assert '"connection_classification": "NEW_CONNECTION"' in events
    assert '"request_to_first_body_ms": "NOT_OBSERVABLE"' in events
    assert '"total_attempt_ms": 4212.0' in events
    assert "unsafe_headers" not in events
    assert "top-secret" not in events
    assert "Authorization" not in events


def test_hybrid_adapter_requires_active_evidence_and_records_review(monkeypatch) -> None:  # noqa: ANN001
    class Status:
        active = False

    class Evidence:
        def status(self):  # noqa: ANN201
            return Status()

        def record_hybrid_review(self, *_args: object) -> None:
            pass

    evidence = Evidence()
    monkeypatch.setattr(hybrid_module, "realtime_test_evidence", evidence)
    adapter = YandexHybridProbeAdapter()
    adapter.attach(HybridRuntimeContext("secret", "folder", SerialEndpoint(), "main", None))
    with pytest.raises(ValueError, match="Test Evidence"):
        adapter.start()
    assert adapter.status().compatible_session
    with pytest.raises(ValueError, match="awaiting acoustic review"):
        adapter.review(AcousticReview.CLEAR)


def test_hybrid_adapter_completes_text_gate_then_accepts_human_review(monkeypatch) -> None:  # noqa: ANN001
    reviews: list[tuple[str, str]] = []

    class Status:
        active = True

    class Evidence:
        def status(self):  # noqa: ANN201
            return Status()

        def record_hybrid_review(self, run_id: str, result: str) -> None:
            reviews.append((run_id, result))

    class Runner:
        async def run(self, _context, _run_id, *, capture_audio, progress):  # noqa: ANN001, ANN202
            assert capture_audio
            progress("heading-137", "realtime", "probe")
            return 20, "probe", True

    monkeypatch.setattr(hybrid_module, "realtime_test_evidence", Evidence())
    adapter = YandexHybridProbeAdapter(runner_factory=Runner)
    adapter.attach(HybridRuntimeContext("secret", "folder", SerialEndpoint(), "main", None))
    started = adapter.start(capture_audio=True)
    assert started.audio_capture_enabled
    deadline = time.monotonic() + 1.0
    while adapter.status().state.value == "running" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert adapter.status().state.value == "review"
    completed = adapter.review(AcousticReview.CLEAR)
    assert completed.state.value == "pass"
    assert reviews and reviews[0][1] == "clear"


@pytest.mark.parametrize(
    ("label", "size"),
    [("empty", 0), ("unaligned", 1), ("oversized", 44_100 * 2 * 20 + 2)],
)
def test_audio_evidence_rejects_empty_unaligned_or_oversized_pcm(tmp_path, label: str, size: int) -> None:  # noqa: ANN001
    del label
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(provider="yandex", transport="srs")
    recorder.record_hybrid_run(
        run_id="run123",
        main_session_id="main",
        probe_session_id="probe",
        context_version_before="ctx",
    )
    with pytest.raises(ValueError, match="bounded PCM16"):
        recorder.record_hybrid_audio(
            run_id="run123",
            case_id="case",
            backend="realtime",
            response_id="response",
            pcm44=bytes(size),
        )
