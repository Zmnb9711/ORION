"""Offline differential oracle against the immutable 333ca5e archive.

No informational implementation is present. Baseline tests are replayed against
both service classes, and gRPC is replaced before any channel can be opened.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Any, cast
import subprocess

import pytest

import orion.protected_presentation as current
import orion.protected_streaming_tts as tts_current
import test_protected_presentation as regression


def baseline_module(path: str, name: str) -> Any:
    code = subprocess.check_output(["git", "show", "474d11bc:" + path], cwd=Path(__file__).resolve().parents[1])
    module = ModuleType(name)
    module.__file__ = "333ca5e:" + path
    sys.modules[name] = module
    exec(compile(code, module.__file__, "exec"), module.__dict__)
    return module


before: Any = baseline_module("orion/protected_presentation.py", "_gate_before_presentation")
tts_before: Any = baseline_module("orion/protected_streaming_tts.py", "_gate_before_tts")


@pytest.fixture(params=[before.ProtectedPresentationService, current.ProtectedPresentationService],
                ids=["333ca5e", "seam"])
def service_class(request, monkeypatch):
    monkeypatch.setattr(regression, "ProtectedPresentationService", request.param)
    return request.param


@pytest.mark.parametrize("name", [
    "test_exact_pipeline_completion_normalization_provenance_and_replay",
    "test_inflight_same_input_shares_one_tts_and_conflict_rejected",
    "test_radio_not_ready_is_not_success_or_retried",
    "test_nonterminal_timeout_and_later_completion_never_resubmit",
    "test_cancel_before_tts_completion",
    "test_shutdown_cancels_tts_closes_session_and_blocks_new_admission",
    "test_cancel_after_pcm_before_admission",
    "test_capacity_has_no_eviction_or_replay_reset",
    "test_shutdown_preserves_active_borrowed_radio",
    "test_untyped_tts_failure_is_normalized_without_provider_details",
])
def test_before_after_existing_characterization(service_class, name):
    getattr(regression, name)()


@pytest.mark.parametrize("mutation,code", [
    ("envelope", current.PresentationFailure.UNSUPPORTED_MIXED_OUTPUT),
    ("language", current.PresentationFailure.UNSUPPORTED_LANGUAGE),
    ("text", current.PresentationFailure.INVALID_FINALIZED_TEXT),
    ("multiple", current.PresentationFailure.INVALID_FINALIZED_TEXT),
    ("profile", current.PresentationFailure.INVALID_FINALIZED_TEXT),
    ("advisory", current.PresentationFailure.INVALID_FINALIZED_TEXT),
])
def test_before_after_rejections(service_class, mutation, code):
    regression.test_admission_fails_before_tts(mutation, code)


@pytest.mark.parametrize("cancellable", [False, True])
def test_before_after_cancellation(service_class, cancellable):
    regression.test_cancel_after_acceptance_is_truthful(cancellable)


def test_no_raw_string_admission(service_class):
    async def run():
        service, router, radio, tts = regression.setup()
        try:
            result = await service.present(cast(Any, "untrusted informational text"), regression.context())
            assert result.failure == current.PresentationFailure.INVALID_FINALIZED_TEXT
            assert not radio.calls and not tts.calls and not service._operations
        finally:
            await service.shutdown()
            router.shutdown()
    asyncio.run(run())


class OfflineRpcError(Exception):
    def code(self):
        return SimpleNamespace(name="UNAVAILABLE")


class FakeCall:
    def __init__(self, mode):
        self.mode = mode
        self.cancel_count = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    def cancel(self):
        self.cancel_count += 1

    async def __aiter__(self):
        self.entered.set()
        if self.mode in {"cancel", "close-active"}:
            await self.release.wait()
        if self.mode == "error":
            raise RuntimeError("offline_failure")
        if self.mode == "rpc-error":
            raise OfflineRpcError("untrusted provider detail must not escape")
        chunks = {"normal": [b"", b"\x01\x00", b"\x02\x00"],
                  "empty": [], "odd": [b"x"], "oversize": [bytes(2880002)]}
        for data in chunks.get(self.mode, []):
            yield SimpleNamespace(audio_chunk=SimpleNamespace(data=data))


class FakeGrpc:
    def __init__(self, mode):
        self.mode = mode
        self.calls = []
        self.requests = []
        self.options = []
        self.closed = 0
        self.credentials = 0
        self.kwargs: dict[str, Any] = {}
        self.metadata_names: tuple[str, ...] = ()

    def ssl_channel_credentials(self):
        self.credentials += 1
        return "offline-tls"

    def secure_channel(self, target, credentials, *, options):
        self.options.append((target, credentials, options))
        return self

    def stream_stream(self, method, **serializers):
        self.method = method
        self.serializers = serializers

        def start(requests, **kwargs):
            self.requests = [r.SerializeToString(deterministic=True) for r in requests]
            # Keep only safe, non-secret metadata names in the observation.
            self.kwargs = {k: v for k, v in kwargs.items() if k != "metadata"}
            self.metadata_names = tuple(k for k, _v in kwargs["metadata"])
            call = FakeCall(self.mode)
            self.calls.append(call)
            return call
        return start

    async def close(self):
        self.closed += 1

    def module(self):
        return SimpleNamespace(
            aio=SimpleNamespace(secure_channel=self.secure_channel, AioRpcError=OfflineRpcError),
            ssl_channel_credentials=self.ssl_channel_credentials,
        )


@pytest.mark.parametrize("text", ["Fly heading zero three seven.", "  Exact protected text.\n", "Unavailable."])
@pytest.mark.parametrize("mode", ["normal", "empty", "odd", "oversize", "error", "rpc-error", "cancel", "close-active"])
def test_tts_serialized_requests_and_lifecycle_equal(monkeypatch, text, mode):
    async def one(module):
        fake = FakeGrpc(mode)
        monkeypatch.setitem(sys.modules, "grpc", fake.module())
        client = module.ProtectedStreamingTts("offline-placeholder")
        output, error = [], None

        async def consume():
            async for chunk in client.stream(text):
                output.append(chunk)

        task = asyncio.create_task(consume())
        try:
            if mode in {"cancel", "close-active"}:
                while not fake.calls:
                    await asyncio.sleep(0)
                await fake.calls[0].entered.wait()
                if mode == "close-active":
                    await client.aclose()
                task.cancel()
            await task
        except BaseException as exc:
            error = (type(exc).__name__, str(exc))
        finally:
            await client.aclose()
        assert task.done() and client._call is None
        return (fake.requests, fake.options, fake.method, fake.kwargs,
                fake.metadata_names, fake.closed, [c.cancel_count for c in fake.calls], output, error)

    old, new = asyncio.run(one(tts_before)), asyncio.run(one(tts_current))
    assert new == old
    request = tts_current.p.StreamSynthesisRequest.FromString(new[0][1])
    assert request.synthesis_input.text == text


@pytest.mark.parametrize("text", ["", " ", "x" * 4097, None])
def test_tts_invalid_input_equal(text):
    for module in (tts_before, tts_current):
        with pytest.raises(ValueError, match="invalid_protected_text"):
            module.protected_stream_requests(text)


def test_default_hook_is_only_existing_builder():
    client = tts_current.ProtectedStreamingTts("offline-placeholder")
    text = "  Fly heading zero three seven.\n"
    old = tts_before.protected_stream_requests(text)
    new = client._requests(text)
    assert [m.SerializeToString(deterministic=True) for m in old] == [
        m.SerializeToString(deterministic=True) for m in new]
    assert new[0].options.voice == "john"
    # Language/style presence is established by complete serialized equality,
    # not by inventing a language field that this streaming schema does not set.
