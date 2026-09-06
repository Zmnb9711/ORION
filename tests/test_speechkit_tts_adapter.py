import asyncio
from urllib.parse import parse_qs

import aiohttp
import pytest

from orion.speechkit_tts_adapter import (
    MAX_RAW_PCM_BYTES,
    SpeechKitTtsAdapter,
    TestSemanticCase as LegacyCase,
    TtsAdapterError,
    TtsFailureCode,
    protected_speechkit_request,
)


class Response:
    def __init__(
        self,
        payload: bytes = bytes(960),
        status: int = 200,
        content_type: str = "application/octet-stream",
        advertised: bool = True,
        block: bool = False,
    ) -> None:
        self.payload, self.status = payload, status
        self.headers = {"Content-Type": content_type}
        self.content_length = len(payload) if advertised else None
        self.content = self
        self.block = block
        self.entered = asyncio.Event()
        self.cancelled = False

    async def __aenter__(self):
        self.entered.set()
        if self.block:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return self

    async def __aexit__(self, *_args):
        pass

    async def iter_chunked(self, size: int):
        for offset in range(0, len(self.payload), size):
            yield self.payload[offset : offset + size]


class Session:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.outcomes.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def close(self):
        self.closed = True


async def no_sleep(_seconds: float) -> None:
    pass


def test_request_preserves_text_and_utf8_without_strip_or_normalization():
    text = "  Fly  e\u0301\nzero three seven.  "
    url, headers, body = protected_speechkit_request(
        LegacyCase("id", text, ()), api_key="SECRET"
    )
    decoded = parse_qs(body.decode("utf-8"))
    assert decoded == {
        "text": [text],
        "lang": ["en-US"],
        "voice": ["john"],
        "format": ["lpcm"],
        "sampleRateHertz": ["48000"],
        "speed": ["1.0"],
    }
    assert decoded["text"][0].encode() == text.encode()
    assert url.endswith("/speech/v1/tts:synthesize")
    assert headers["Authorization"] == "Api-Key SECRET"
    assert b"SECRET" not in body


@pytest.mark.parametrize(
    "text,key", [("", "key"), ("x" * 4097, "key"), ("x", ""), ("я" * 4096, "key")]
)
def test_request_bounds(text, key):
    with pytest.raises(TtsAdapterError):
        protected_speechkit_request(LegacyCase("id", text, ()), api_key=key)


def test_session_reused_and_closed_with_redirects_disabled(monkeypatch):
    async def run():
        session = Session([Response(), Response()])
        creations = []

        def factory(**kwargs):
            creations.append(kwargs)
            return session

        monkeypatch.setattr(aiohttp, "ClientSession", factory)
        adapter = SpeechKitTtsAdapter("SECRET")
        for _ in range(2):
            assert await adapter.synthesize("Exact.", "en-US", "p7c-test") == bytes(960)
        assert len(creations) == 1 and len(session.calls) == 2
        assert all(call[1]["allow_redirects"] is False for call in session.calls)
        await adapter.aclose()
        assert session.closed
        with pytest.raises(TtsAdapterError) as error:
            await adapter.synthesize("Exact.", "en-US", "p7c-test")
        assert error.value.code == TtsFailureCode.UNAVAILABLE

    asyncio.run(run())


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_http_retries_once_before_success(monkeypatch, status):
    async def run():
        session = Session([Response(b"{}", status), Response()])
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_: session)
        events = []
        adapter = SpeechKitTtsAdapter("SECRET", sleep=no_sleep)
        assert await adapter.synthesize(
            "Exact.", "en-US", "p7c-fixed", lambda e, f: events.append((e, f))
        ) == bytes(960)
        assert len(session.calls) == 2
        assert {f["response_id"] for _, f in events} == {"p7c-fixed"}
        assert sum(e == "speechkit_attempt_succeeded" for e, _ in events) == 1
        await adapter.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("status", [400, 401, 403, 302])
def test_nonretryable_failure_is_private(monkeypatch, status):
    async def run():
        session = Session(
            [Response(b'{"error_message":"SECRET protected wording"}', status)]
        )
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_: session)
        adapter = SpeechKitTtsAdapter("SECRET", sleep=no_sleep)
        with pytest.raises(TtsAdapterError) as error:
            await adapter.synthesize("protected wording", "en-US", "p7c-fixed")
        assert len(session.calls) == 1
        assert str(error.value) in {"tts_rejected", "tts_unavailable"}
        assert "SECRET" not in str(error.value) and "wording" not in str(error.value)
        await adapter.aclose()

    asyncio.run(run())


def test_timeout_retries_and_exhaustion_are_bounded(monkeypatch):
    async def run():
        session = Session([aiohttp.ConnectionTimeoutError()] * 3)
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_: session)
        adapter = SpeechKitTtsAdapter("key", sleep=no_sleep)
        with pytest.raises(TtsAdapterError) as error:
            await adapter.synthesize("Exact.", "en-US", "p7c-fixed")
        assert error.value.code == TtsFailureCode.TIMEOUT
        assert len(session.calls) == 3
        await adapter.aclose()

    asyncio.run(run())


def test_total_deadline_cancels_first_hung_request(monkeypatch):
    async def run():
        response = Response(block=True)
        session = Session([response])
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_: session)
        adapter = SpeechKitTtsAdapter("key", deadline_s=0.01)
        with pytest.raises(TtsAdapterError) as error:
            await adapter.synthesize("Exact.", "en-US", "p7c-fixed")
        assert error.value.code == TtsFailureCode.TIMEOUT and response.cancelled
        assert len(session.calls) == 1
        await adapter.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("during_backoff", [False, True])
def test_cancellation_stops_request_or_backoff(monkeypatch, during_backoff):
    async def run():
        response = Response(block=True)
        sleeping = asyncio.Event()

        async def blocked_sleep(_seconds):
            sleeping.set()
            await asyncio.Event().wait()

        session = Session(
            [aiohttp.ConnectionTimeoutError()] if during_backoff else [response]
        )
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_: session)
        adapter = SpeechKitTtsAdapter("key", sleep=blocked_sleep)
        task = asyncio.create_task(adapter.synthesize("Exact.", "en-US", "p7c-fixed"))
        await (sleeping.wait() if during_backoff else response.entered.wait())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(session.calls) == 1
        await adapter.aclose()
        assert session.closed

    asyncio.run(run())


@pytest.mark.parametrize(
    "response",
    [
        Response(b""),
        Response(b"x"),
        Response(bytes(MAX_RAW_PCM_BYTES + 2)),
        Response(bytes(MAX_RAW_PCM_BYTES + 2), advertised=False),
        Response(b"{}", content_type="application/json"),
        Response(b"RIFF1234"),
        Response(b"OggS1234"),
        Response(b'{"error":true}'),
    ],
)
def test_invalid_pcm_is_never_retried(monkeypatch, response):
    async def run():
        session = Session([response])
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_: session)
        adapter = SpeechKitTtsAdapter("key", sleep=no_sleep)
        with pytest.raises(TtsAdapterError) as error:
            await adapter.synthesize("Exact.", "en-US", "p7c-fixed")
        assert error.value.code == TtsFailureCode.INVALID_PCM
        assert len(session.calls) == 1
        await adapter.aclose()

    asyncio.run(run())


def test_maximum_valid_pcm_accepted(monkeypatch):
    async def run():
        session = Session([Response(bytes(MAX_RAW_PCM_BYTES))])
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_: session)
        adapter = SpeechKitTtsAdapter("key")
        assert (
            len(await adapter.synthesize("Exact.", "en-US", "p7c-fixed"))
            == MAX_RAW_PCM_BYTES
        )
        await adapter.aclose()

    asyncio.run(run())


def test_language_rejected_without_http(monkeypatch):
    async def run():
        def forbidden(**kwargs):
            raise AssertionError("network must not start")

        monkeypatch.setattr(aiohttp, "ClientSession", forbidden)
        adapter = SpeechKitTtsAdapter("key")
        with pytest.raises(TtsAdapterError):
            await adapter.synthesize("Exact.", "ru-RU", "p7c-fixed")
        await adapter.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "error", [aiohttp.ClientConnectionError(), aiohttp.ClientPayloadError()]
)
def test_transient_connection_and_body_errors_retry(monkeypatch, error):
    async def run():
        session = Session([error, Response()])
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_: session)
        adapter = SpeechKitTtsAdapter("key", sleep=no_sleep)
        try:
            assert await adapter.synthesize("Exact.", "en-US", "p7c-fixed")
            assert len(session.calls) == 2
        finally:
            await adapter.aclose()

    asyncio.run(run())


def test_tls_validation_never_retries(monkeypatch):
    async def run():
        session = Session([aiohttp.ServerFingerprintMismatch(b"a", b"b", "host", 443)])
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_: session)
        adapter = SpeechKitTtsAdapter("key", sleep=no_sleep)
        try:
            with pytest.raises(TtsAdapterError) as error:
                await adapter.synthesize("Exact.", "en-US", "p7c-fixed")
            assert error.value.code == TtsFailureCode.ERROR and len(session.calls) == 1
        finally:
            await adapter.aclose()

    asyncio.run(run())


def test_overall_deadline_includes_backoff(monkeypatch):
    async def run():
        session = Session([Response(b"{}", 503)])
        monkeypatch.setattr(aiohttp, "ClientSession", lambda **_: session)
        adapter = SpeechKitTtsAdapter("key", deadline_s=0.01)
        try:
            with pytest.raises(TtsAdapterError) as error:
                await adapter.synthesize("Exact.", "en-US", "p7c-fixed")
            assert (
                error.value.code == TtsFailureCode.TIMEOUT and len(session.calls) == 1
            )
        finally:
            await adapter.aclose()

    asyncio.run(run())
