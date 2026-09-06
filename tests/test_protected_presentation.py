import asyncio
from datetime import UTC, datetime
import json
import threading
from uuid import UUID

import pytest

from orion.communication_contracts import (
    CommunicationDomain,
    CommunicationPriority,
    UntrustedConversationalEnvelope,
)
from orion.protected_presentation import (
    PresentationFailure as Code,
    ProtectedPresentationService,
    tx_correlation,
)
from orion.protected_presentation_probe import (
    protected_probe_cases,
    run_cases,
    EXPECTED,
)
from orion.radio_contracts import (
    REQUIRED_TX_CAPABILITIES,
    RadioAdapterOutcome,
    RadioAdapterTxResult,
    RadioContext,
    RadioEntityRef,
    RadioModulation,
    RadioReadiness,
    RadioTransportCapability,
    RadioTransportStatus,
    RadioFailure,
    RadioFailureCode,
)
from orion.radio_router import RadioRouter
from orion.speechkit_tts_adapter import TtsAdapterError, TtsFailureCode


class FakeRadio:
    transport_id = "fake"

    def __init__(self, block=False, cancellable=False):
        self.ready = RadioReadiness.READY
        self.calls = []
        self.release = threading.Event()
        self.entered = threading.Event()
        self.block, self.cancellable = block, cancellable
        self.cancelled = False
        self.shutdown_calls = 0

    def capabilities(self):
        return REQUIRED_TX_CAPABILITIES | (
            {RadioTransportCapability.TRANSMISSION_CANCEL}
            if self.cancellable
            else set()
        )

    def status(self):
        return RadioTransportStatus(
            transport_id=self.transport_id, readiness=self.ready
        )

    def start(self):
        return self.status()

    def transmit(self, request):
        self.calls.append(request)
        self.entered.set()
        if self.block:
            assert self.release.wait(3)
        return RadioAdapterTxResult(
            tx_correlation_id=request.context.tx_correlation_id,
            outcome=RadioAdapterOutcome.CANCELLED
            if self.cancelled
            else RadioAdapterOutcome.COMPLETED,
            completed_at=datetime.now(UTC),
            failure=RadioFailure(
                code=RadioFailureCode.TX_CANCELLED, message="cancelled"
            )
            if self.cancelled
            else None,
        )

    def cancel(self, tx_correlation_id):
        self.cancelled = True
        self.release.set()
        return True

    def shutdown(self, timeout_s):
        self.shutdown_calls += 1
        self.release.set()
        return True


class FakeTts:
    def __init__(self, block=False, pcm: bytes | Exception = bytes(960)):
        self.calls = []
        self.closed = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = False
        self.block, self.pcm = block, pcm

    async def synthesize(self, text, language, tx_id, observer=None):
        self.calls.append((text, language, tx_id))
        self.entered.set()
        if self.block:
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        if isinstance(self.pcm, Exception):
            raise self.pcm
        return self.pcm

    async def aclose(self):
        self.closed = True


def final():
    return protected_probe_cases(UUID(int=7))[0].finalized


def context(value=None):
    value = value or final()
    return RadioContext(
        tx_correlation_id=tx_correlation(value.interaction_id),
        source_domain=value.context.domain,
        radio_entity=RadioEntityRef(
            entity_id="test", operational_callsign="ORION TEST"
        ),
        target_frequency_hz=251000000,
        modulation=RadioModulation.AM,
        communication_priority=value.priority,
        interaction_id=value.interaction_id,
    )


def setup(tts=None, radio=None, **kwargs):
    fake = radio or FakeRadio()
    router = RadioRouter(default_transport_id="fake")
    router.register_adapter(fake)
    router.start()
    adapter = tts or FakeTts()
    return (
        ProtectedPresentationService(adapter, router, transport_id="fake", **kwargs),
        router,
        fake,
        adapter,
    )


def test_exact_pipeline_completion_normalization_provenance_and_replay():
    async def run():
        service, router, radio, tts = setup()
        try:
            value = final()
            result = await service.present(value, context())
            replay = await service.present(value, context())
            assert result == replay and result.state == "completed" and result.terminal
            assert len(tts.calls) == len(radio.calls) == 1
            assert tts.calls[0] == (
                value.text,
                "en-US",
                tx_correlation(value.interaction_id),
            )
            request = radio.calls[0]
            assert request.audio.sample_rate_hz == 44100 and request.audio.channels == 1
            assert len(request.audio.pcm) == 882
            assert request.context.provenance == tuple(
                p.source for p in value.provenance
            )
            assert request.context.interaction_id == value.interaction_id
            evidence = json.dumps(service.diagnostics())
            assert (
                value.text not in evidence
                and "037" not in evidence
                and "pcm48" not in evidence
            )
            assert await service.shutdown()
            assert radio.shutdown_calls == 0 and tts.closed
        finally:
            router.shutdown()

    asyncio.run(run())


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("envelope", Code.UNSUPPORTED_MIXED_OUTPUT),
        ("language", Code.UNSUPPORTED_LANGUAGE),
        ("text", Code.INVALID_FINALIZED_TEXT),
        ("multiple", Code.INVALID_FINALIZED_TEXT),
        ("profile", Code.INVALID_FINALIZED_TEXT),
        ("advisory", Code.INVALID_FINALIZED_TEXT),
    ],
)
def test_admission_fails_before_tts(mutation, code):
    async def run():
        service, router, radio, tts = setup()
        value = final()
        if mutation == "envelope":
            value = value.model_copy(
                update={
                    "envelope": UntrustedConversationalEnvelope(text="SECRET"),
                    "text": "SECRET " + value.text,
                }
            )
        elif mutation == "language":
            value = value.model_copy(
                update={
                    "context": value.context.model_copy(
                        update={"operational_language": "ru-RU"}
                    )
                }
            )
        elif mutation == "profile":
            from orion.communication_contracts import CommunicationProfileId

            value = value.model_copy(
                update={
                    "context": value.context.model_copy(
                        update={"profile_id": CommunicationProfileId.FAA_US}
                    )
                }
            )
        elif mutation == "multiple":
            value = value.model_copy(
                update={
                    "protected_fragments": value.protected_fragments * 2,
                    "text": value.text + " " + value.text,
                }
            )
        elif mutation == "advisory":
            value = {**value.model_dump(), "advisory": ("SECRET",)}
        else:
            value = value.model_copy(update={"text": "SECRET rewrite"})
        try:
            result = await service.present(value, context())  # type: ignore[arg-type]
            assert result.failure == code
            assert not radio.calls and not tts.calls
        finally:
            await service.shutdown()
            router.shutdown()

    asyncio.run(run())


@pytest.mark.parametrize(
    "update",
    [
        {"source_domain": CommunicationDomain.ATC},
        {"communication_priority": CommunicationPriority.URGENT},
        {"interaction_id": UUID(int=2)},
        {"tx_correlation_id": "different"},
    ],
)
def test_radio_context_mismatch(update):
    async def run():
        service, router, radio, tts = setup()
        try:
            result = await service.present(final(), context().model_copy(update=update))
            assert result.failure == Code.RADIO_CONTEXT_MISMATCH and not tts.calls
        finally:
            await service.shutdown()
            router.shutdown()

    asyncio.run(run())


def test_inflight_same_input_shares_one_tts_and_conflict_rejected():
    async def run():
        tts = FakeTts(block=True)
        service, router, radio, _ = setup(tts)
        try:
            first = asyncio.create_task(service.present(final(), context()))
            await tts.entered.wait()
            second = asyncio.create_task(service.present(final(), context()))
            changed = context().model_copy(update={"target_frequency_hz": 252000000})
            assert (
                await service.present(final(), changed)
            ).failure == Code.CONFLICTING_REPLAY
            tts.release.set()
            assert await first == await second
            assert len(tts.calls) == len(radio.calls) == 1
        finally:
            await service.shutdown()
            router.shutdown()

    asyncio.run(run())


@pytest.mark.parametrize(
    "pcm",
    [b"", b"x", bytes(2880002), TtsAdapterError(TtsFailureCode.TIMEOUT)],
    ids=["empty", "odd", "oversized", "timeout"],
)
def test_tts_or_pcm_failure_never_submits(pcm):
    async def run():
        service, router, radio, _ = setup(FakeTts(pcm=pcm))
        try:
            result = await service.present(final(), context())
            assert result.failure in {Code.INVALID_PCM, Code.TTS_TIMEOUT}
            assert not radio.calls
        finally:
            await service.shutdown()
            router.shutdown()

    asyncio.run(run())


def test_radio_not_ready_is_not_success_or_retried():
    async def run():
        service, router, radio, tts = setup()
        radio.ready = RadioReadiness.DEGRADED
        try:
            result = await service.present(final(), context())
            assert result.failure == Code.RADIO_NOT_READY
            assert await service.present(final(), context()) == result
            assert len(tts.calls) == 1 and not radio.calls
        finally:
            await service.shutdown()
            router.shutdown()

    asyncio.run(run())


def test_nonterminal_timeout_and_later_completion_never_resubmit():
    async def run():
        service, router, radio, tts = setup(
            radio=FakeRadio(block=True), radio_timeout_s=0.02
        )
        try:
            result = await service.present(final(), context())
            assert not result.terminal and result.failure == Code.RADIO_TIMEOUT
            assert (await service.present(final(), context())).terminal is False
            radio.release.set()
            await asyncio.to_thread(router.wait, result.tx_id, 1)
            assert (await service.present(final(), context())).state == "completed"
            assert len(tts.calls) == len(radio.calls) == 1
        finally:
            radio.release.set()
            await service.shutdown()
            router.shutdown()

    asyncio.run(run())


def test_cancel_before_tts_completion():
    async def run():
        service, router, radio, tts = setup(FakeTts(block=True))
        task = asyncio.create_task(service.present(final(), context()))
        await tts.entered.wait()
        result = await service.cancel(context().tx_correlation_id)
        assert result.state == "cancelled" and (await task).failure == Code.CANCELLED
        assert tts.cancelled and not radio.calls
        await service.shutdown()
        router.shutdown()

    asyncio.run(run())


@pytest.mark.parametrize("cancellable", [False, True])
def test_cancel_after_acceptance_is_truthful(cancellable):
    async def run():
        radio = FakeRadio(block=True, cancellable=cancellable)
        service, router, _, _ = setup(radio=radio)
        task = asyncio.create_task(service.present(final(), context()))
        await asyncio.to_thread(radio.entered.wait, 1)
        result = await service.cancel(context().tx_correlation_id)
        if not cancellable:
            assert (
                not result.terminal and result.failure == Code.CANCELLATION_UNSUPPORTED
            )
            radio.release.set()
            assert (await task).state == "completed"
        else:
            assert (await task).state == "cancelled"
        await service.shutdown()
        router.shutdown()

    asyncio.run(run())


def test_shutdown_cancels_tts_closes_session_and_blocks_new_admission():
    async def run():
        service, router, radio, tts = setup(FakeTts(block=True))
        task = asyncio.create_task(service.present(final(), context()))
        await tts.entered.wait()
        assert await service.shutdown()
        assert tts.closed and tts.cancelled and radio.shutdown_calls == 0
        assert (await task).state == "cancelled"
        value = protected_probe_cases(UUID(int=8))[0].finalized
        assert (
            await service.present(value, context(value))
        ).failure == Code.SHUTTING_DOWN
        router.shutdown()

    asyncio.run(run())


def test_six_cases_use_real_upstream_and_serialized_router():
    async def run():
        service, router, radio, tts = setup()
        cases = protected_probe_cases(UUID(int=7))
        assert tuple(c.finalized.text for c in cases) == EXPECTED
        try:
            rows = await run_cases(service, cases, context().radio_entity, 251000000)
            assert len(rows) == 6 and all(r["state"] == "completed" for r in rows)
            assert len(radio.calls) == len(tts.calls) == 6
            assert len({r.context.tx_correlation_id for r in radio.calls}) == 6
            assert (
                tuple(r.context.source_domain for r in radio.calls)[3]
                == CommunicationDomain.JTAC
            )
        finally:
            await service.shutdown()
            router.shutdown()

    asyncio.run(run())


def test_cancel_after_pcm_before_admission():
    async def run():
        cancellation = []
        service, router, radio, tts = setup()

        def normalize(pcm):
            cancellation.append(
                asyncio.create_task(service.cancel(context().tx_correlation_id))
            )
            return bytes(882)

        service._normalize = normalize
        try:
            result = await service.present(final(), context())
            await asyncio.gather(*cancellation)
            assert result.failure == Code.CANCELLED
            assert len(tts.calls) == 1 and not radio.calls
        finally:
            await service.shutdown()
            router.shutdown()

    asyncio.run(run())


@pytest.mark.parametrize("pcm", [b"", bytes(2646002)], ids=["empty", "oversized"])
def test_normalized_audio_bound(pcm):
    async def run():
        service, router, radio, _ = setup(normalize=lambda _: pcm)
        try:
            assert (
                await service.present(final(), context())
            ).failure == Code.INVALID_PCM
            assert not radio.calls
        finally:
            await service.shutdown()
            router.shutdown()

    asyncio.run(run())


def test_capacity_has_no_eviction_or_replay_reset():
    async def run():
        service, router, radio, tts = setup(capacity=1)
        try:
            original = await service.present(final(), context())
            other = protected_probe_cases(UUID(int=8))[0].finalized
            assert (
                await service.present(other, context(other))
            ).failure == Code.CAPACITY_EXCEEDED
            assert await service.present(final(), context()) == original
            assert len(tts.calls) == len(radio.calls) == 1
        finally:
            await service.shutdown()
            router.shutdown()

    asyncio.run(run())


def test_shutdown_preserves_active_borrowed_radio():
    async def run():
        service, router, radio, tts = setup(radio=FakeRadio(block=True))
        try:
            task = asyncio.create_task(service.present(final(), context()))
            assert await asyncio.to_thread(radio.entered.wait, 1)
            assert not await service.shutdown()
            assert not (await task).terminal
            assert tts.closed and radio.shutdown_calls == 0 and not radio.cancelled
            radio.release.set()
            await asyncio.to_thread(router.wait, context().tx_correlation_id, 1)
            result = service.get(context().tx_correlation_id)
            assert result is not None and result.state == "completed"
        finally:
            radio.release.set()
            await service.shutdown()
            router.shutdown()

    asyncio.run(run())


def test_unknown_router_state_is_private_nonterminal_without_replay(monkeypatch):
    async def run():
        service, router, radio, tts = setup(radio=FakeRadio(block=True))
        try:
            task = asyncio.create_task(service.present(final(), context()))
            assert await asyncio.to_thread(radio.entered.wait, 1)

            def broken(*args):
                raise RuntimeError("SECRET protected words")

            monkeypatch.setattr(router, "get", broken)
            monkeypatch.setattr(router, "cancel", broken)
            result = await task
            assert not result.terminal and result.failure == Code.RADIO_ERROR
            assert (await service.cancel(result.tx_id)).failure == Code.RADIO_ERROR
            assert await service.present(final(), context()) == result
            assert "SECRET" not in json.dumps(service.diagnostics())
            assert len(tts.calls) == len(radio.calls) == 1
        finally:
            monkeypatch.undo()
            radio.release.set()
            await service.shutdown()
            router.shutdown()

    asyncio.run(run())


def test_untyped_tts_failure_is_normalized_without_provider_details():
    async def run():
        service, router, radio, _ = setup(FakeTts(pcm=RuntimeError("SECRET")))
        try:
            result = await service.present(final(), context())
            assert result.failure == Code.TTS_ERROR and not radio.calls
            assert "SECRET" not in str(result) + json.dumps(service.diagnostics())
        finally:
            await service.shutdown()
            router.shutdown()

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure,expected",
    [
        (RadioFailureCode.TX_REJECTED, Code.RADIO_REJECTED),
        (RadioFailureCode.TX_TIMEOUT, Code.RADIO_TIMEOUT),
    ],
)
def test_terminal_radio_failure_is_normalized_and_not_replayed(
    monkeypatch, failure, expected
):
    async def run():
        service, router, radio, tts = setup()

        def fail(request):
            radio.calls.append(request)
            return RadioAdapterTxResult(
                tx_correlation_id=request.context.tx_correlation_id,
                outcome=RadioAdapterOutcome.FAILED,
                completed_at=datetime.now(UTC),
                failure=RadioFailure(code=failure, message="SECRET transport detail"),
            )

        monkeypatch.setattr(radio, "transmit", fail)
        try:
            result = await service.present(final(), context())
            assert (
                result.terminal
                and result.state == "failed"
                and result.failure == expected
            )
            assert await service.present(final(), context()) == result
            assert len(radio.calls) == len(tts.calls) == 1
            assert "SECRET" not in str(result) + json.dumps(service.diagnostics())
        finally:
            await service.shutdown()
            router.shutdown()

    asyncio.run(run())
