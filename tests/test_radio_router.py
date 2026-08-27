from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import Literal

import pytest

from orion.communication_contracts import CommunicationDomain, CommunicationPriority
from orion.radio_contracts import (
    REQUIRED_TX_CAPABILITIES,
    FinalizedPcmAudio,
    RadioAdapterOutcome,
    RadioAdapterTxResult,
    RadioContext,
    RadioDiagnosticStage,
    RadioEntityRef,
    RadioFailure,
    RadioFailureCode,
    RadioModulation,
    RadioReadiness,
    RadioTransmissionRequest,
    RadioTransmissionState,
    RadioTransportCapability,
    RadioTransportStatus,
)
from orion.radio_router import RadioRouter


class FakeRadioTransportAdapter:
    """Deterministic tests-only proof of the generic adapter contract."""

    def __init__(
        self,
        *,
        transport_id: str = "fake-radio",
        readiness: RadioReadiness = RadioReadiness.READY,
        capabilities: frozenset[RadioTransportCapability] = REQUIRED_TX_CAPABILITIES,
        outcome: Literal["complete", "fail", "raise"] = "complete",
        block: bool = False,
        shutdown_success: bool = True,
        start_failure: bool = False,
    ) -> None:
        self.transport_id = transport_id
        self.readiness = readiness
        self._capabilities = capabilities
        self.outcome = outcome
        self.block = block
        self.shutdown_success = shutdown_success
        self.start_failure = start_failure
        self.started = False
        self.shutdown_calls = 0
        self.transmit_calls: list[RadioTransmissionRequest] = []
        self.cancel_calls: list[str] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self._cancelled: set[str] = set()

    def capabilities(self) -> frozenset[RadioTransportCapability]:
        return self._capabilities

    def status(self) -> RadioTransportStatus:
        return RadioTransportStatus(
            transport_id=self.transport_id,
            readiness=self.readiness,
        )

    def start(self) -> RadioTransportStatus:
        if self.start_failure:
            raise RuntimeError("fake start secret")
        self.started = True
        return self.status()

    def transmit(self, request: RadioTransmissionRequest) -> RadioAdapterTxResult:
        self.transmit_calls.append(request)
        self.entered.set()
        started_at = datetime.now(UTC)
        if self.block:
            assert self.release.wait(2), "Fake adapter was not released"
        tx_id = str(request.context.tx_correlation_id)
        completed_at = datetime.now(UTC)
        if tx_id in self._cancelled:
            return RadioAdapterTxResult(
                tx_correlation_id=tx_id,
                outcome=RadioAdapterOutcome.CANCELLED,
                started_at=started_at,
                completed_at=completed_at,
                failure=RadioFailure(
                    code=RadioFailureCode.TX_CANCELLED,
                    message="Fake cancellation",
                    transport_id=self.transport_id,
                ),
            )
        if self.outcome == "raise":
            raise RuntimeError("provider-secret-must-not-cross-boundary")
        if self.outcome == "fail":
            return RadioAdapterTxResult(
                tx_correlation_id=tx_id,
                outcome=RadioAdapterOutcome.FAILED,
                started_at=started_at,
                completed_at=completed_at,
                failure=RadioFailure(
                    code=RadioFailureCode.TX_TIMEOUT,
                    message="transport-specific sensitive timeout detail",
                    transport_id=self.transport_id,
                    retryable=True,
                ),
            )
        return RadioAdapterTxResult(
            tx_correlation_id=tx_id,
            outcome=RadioAdapterOutcome.COMPLETED,
            started_at=started_at,
            completed_at=completed_at,
            frame_count=7,
            duration_ms=140.0,
        )

    def cancel(self, tx_correlation_id: str) -> bool:
        self.cancel_calls.append(tx_correlation_id)
        if RadioTransportCapability.TRANSMISSION_CANCEL not in self._capabilities:
            return False
        self._cancelled.add(tx_correlation_id)
        self.release.set()
        return True

    def shutdown(self, timeout_s: float) -> bool:
        assert timeout_s > 0
        self.shutdown_calls += 1
        self.release.set()
        return self.shutdown_success


def _request(
    tx_id: str,
    *,
    priority: CommunicationPriority = CommunicationPriority.ROUTINE,
    transport_id: str | None = "fake-radio",
    pcm: bytes = b"\x00\x00" * 441,
) -> RadioTransmissionRequest:
    return RadioTransmissionRequest(
        context=RadioContext(
            tx_correlation_id=tx_id,
            source_domain=CommunicationDomain.MISSION_CONTROL,
            radio_entity=RadioEntityRef(
                entity_id="mission.orion",
                operational_callsign="Orion",
                coalition="blue",
            ),
            target_frequency_hz=251_000_000,
            modulation=RadioModulation.AM,
            communication_priority=priority,
            session_id="radio-session",
            turn_id=f"turn-{tx_id}",
        ),
        audio=FinalizedPcmAudio(pcm=pcm, sample_rate_hz=44_100),
        transport_id=transport_id,
    )


def _started_router(
    adapter: FakeRadioTransportAdapter,
    **router_options: object,
) -> RadioRouter:
    router = RadioRouter(**router_options)
    router.register_adapter(adapter)
    statuses = router.start()
    assert statuses == (adapter.status(),)
    return router


def _wait_state(
    router: RadioRouter,
    tx_id: str,
    expected: RadioTransmissionState,
    timeout_s: float = 2,
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        snapshot = router.get(tx_id)
        if snapshot is not None and snapshot.state is expected:
            return
        time.sleep(0.005)
    pytest.fail(f"Transmission {tx_id} did not reach {expected}")


def test_fake_adapter_capabilities_readiness_transmit_and_shutdown() -> None:
    adapter = FakeRadioTransportAdapter()
    assert adapter.capabilities() == REQUIRED_TX_CAPABILITIES
    assert adapter.status().readiness is RadioReadiness.READY
    assert adapter.start().readiness is RadioReadiness.READY

    result = adapter.transmit(_request("adapter-direct"))
    assert result.outcome is RadioAdapterOutcome.COMPLETED
    assert result.frame_count == 7
    assert len(adapter.transmit_calls) == 1
    assert adapter.shutdown(0.5)


def test_adapter_registration_is_bounded_and_rejects_duplicates() -> None:
    router = RadioRouter(max_adapters=1)
    first = FakeRadioTransportAdapter()
    assert router.register_adapter(first).transport_id == "fake-radio"
    with pytest.raises(ValueError, match="already registered"):
        router.register_adapter(first)
    with pytest.raises(ValueError, match="hard bound"):
        router.register_adapter(FakeRadioTransportAdapter(transport_id="second"))
    router.start()
    with pytest.raises(RuntimeError, match="before Router start"):
        router.register_adapter(FakeRadioTransportAdapter(transport_id="late"))
    assert router.shutdown().clean


def test_unknown_adapter_and_missing_default_never_fall_back() -> None:
    adapter = FakeRadioTransportAdapter()
    router = _started_router(adapter)
    try:
        unknown = router.submit(_request("unknown", transport_id="other-radio"))
        no_default = router.submit(_request("no-default", transport_id=None))
        assert unknown.failure is not None
        assert unknown.failure.code is RadioFailureCode.TRANSPORT_UNAVAILABLE
        assert no_default.failure is not None
        assert no_default.failure.code is RadioFailureCode.TRANSPORT_UNAVAILABLE
        assert adapter.transmit_calls == []
    finally:
        router.shutdown()


@pytest.mark.parametrize(
    ("readiness", "expected"),
    [
        (RadioReadiness.STARTING, RadioFailureCode.NOT_READY),
        (RadioReadiness.DEGRADED, RadioFailureCode.NOT_READY),
        (RadioReadiness.UNAVAILABLE, RadioFailureCode.TRANSPORT_UNAVAILABLE),
    ],
)
def test_router_rejects_adapter_that_is_not_ready(
    readiness: RadioReadiness,
    expected: RadioFailureCode,
) -> None:
    adapter = FakeRadioTransportAdapter(readiness=readiness)
    router = _started_router(adapter)
    try:
        result = router.submit(_request(f"readiness-{readiness.value}"))
        assert not result.accepted
        assert result.failure is not None
        assert result.failure.code is expected
        assert adapter.transmit_calls == []
    finally:
        router.shutdown()


def test_router_rejects_missing_baseline_capability() -> None:
    adapter = FakeRadioTransportAdapter(
        capabilities=REQUIRED_TX_CAPABILITIES - {RadioTransportCapability.TX_COMPLETION}
    )
    router = _started_router(adapter)
    try:
        result = router.submit(_request("missing-capability"))
        assert result.failure is not None
        assert result.failure.code is RadioFailureCode.UNSUPPORTED_CAPABILITY
        assert not adapter.transmit_calls
    finally:
        router.shutdown()


def test_adapter_start_failure_remains_not_ready_and_is_normalized() -> None:
    adapter = FakeRadioTransportAdapter(start_failure=True)
    router = RadioRouter()
    router.register_adapter(adapter)
    statuses = router.start()
    try:
        assert statuses[0].readiness is RadioReadiness.ERROR
        result = router.submit(_request("start-failed"))
        assert result.failure is not None
        assert result.failure.code is RadioFailureCode.NOT_READY
        assert "secret" not in result.failure.message
        assert not adapter.transmit_calls
    finally:
        router.shutdown()


def test_successful_transmission_preserves_correlation_and_safe_diagnostics() -> None:
    adapter = FakeRadioTransportAdapter()
    router = _started_router(adapter, max_diagnostics=3)
    try:
        request = _request("successful-tx")
        submitted = router.submit(request)
        completed = router.wait("successful-tx", 2)

        assert submitted.accepted and not submitted.replayed
        assert completed is not None
        assert completed.tx_correlation_id == "successful-tx"
        assert completed.state is RadioTransmissionState.COMPLETED
        assert completed.frame_count == 7
        assert completed.duration_ms == 140.0
        assert adapter.transmit_calls == [request]
        diagnostics = router.diagnostic_snapshot()
        assert [event.stage for event in diagnostics] == [
            RadioDiagnosticStage.ENQUEUED,
            RadioDiagnosticStage.STARTED,
            RadioDiagnosticStage.COMPLETED,
        ]
        assert all("pcm" not in event.model_dump() for event in diagnostics)
    finally:
        router.shutdown()


def test_priority_then_fifo_ordering_without_active_preemption() -> None:
    adapter = FakeRadioTransportAdapter(block=True)
    router = _started_router(adapter, queue_capacity=6)
    try:
        assert router.submit(
            _request("active", priority=CommunicationPriority.ROUTINE)
        ).accepted
        assert adapter.entered.wait(1)
        for tx_id, priority in (
            ("routine", CommunicationPriority.ROUTINE),
            ("urgent-1", CommunicationPriority.URGENT),
            ("immediate", CommunicationPriority.IMMEDIATE),
            ("urgent-2", CommunicationPriority.URGENT),
            ("important", CommunicationPriority.IMPORTANT),
        ):
            assert router.submit(_request(tx_id, priority=priority)).accepted

        assert [
            str(item.context.tx_correlation_id) for item in adapter.transmit_calls
        ] == ["active"]
        adapter.release.set()
        assert router.wait("routine", 2) is not None
        assert [
            str(item.context.tx_correlation_id) for item in adapter.transmit_calls
        ] == [
            "active",
            "immediate",
            "urgent-1",
            "urgent-2",
            "important",
            "routine",
        ]
    finally:
        router.shutdown()


def test_bounded_queue_rejects_new_work_when_full() -> None:
    adapter = FakeRadioTransportAdapter(block=True)
    router = _started_router(adapter, queue_capacity=2, max_replay_entries=3)
    try:
        assert router.submit(_request("active-full")).accepted
        assert adapter.entered.wait(1)
        assert router.submit(_request("queued-1")).accepted
        assert router.submit(_request("queued-2")).accepted
        rejected = router.submit(_request("queue-overflow"))
        assert not rejected.accepted
        assert rejected.failure is not None
        assert rejected.failure.code is RadioFailureCode.TX_REJECTED
        adapter.release.set()
    finally:
        router.shutdown()


def test_queued_cancellation_never_reaches_adapter() -> None:
    adapter = FakeRadioTransportAdapter(block=True)
    router = _started_router(adapter)
    try:
        router.submit(_request("active-cancel-queue"))
        assert adapter.entered.wait(1)
        router.submit(_request("queued-cancel"))
        cancelled = router.cancel("queued-cancel")
        assert cancelled.cancelled
        assert cancelled.state is RadioTransmissionState.CANCELLED
        snapshot = router.wait("queued-cancel", 1)
        assert snapshot is not None
        assert snapshot.failure is not None
        assert snapshot.failure.code is RadioFailureCode.TX_CANCELLED
        adapter.release.set()
        router.wait("active-cancel-queue", 2)
        assert [
            str(item.context.tx_correlation_id) for item in adapter.transmit_calls
        ] == ["active-cancel-queue"]
    finally:
        router.shutdown()


def test_unsupported_active_cancellation_is_explicit() -> None:
    adapter = FakeRadioTransportAdapter(block=True)
    router = _started_router(adapter)
    try:
        router.submit(_request("active-no-cancel"))
        assert adapter.entered.wait(1)
        result = router.cancel("active-no-cancel")
        assert not result.cancelled
        assert result.failure is not None
        assert result.failure.code is RadioFailureCode.UNSUPPORTED_CAPABILITY
        assert adapter.cancel_calls == []
        adapter.release.set()
    finally:
        router.shutdown()


def test_supported_active_cancellation_is_adapter_correlated() -> None:
    adapter = FakeRadioTransportAdapter(
        block=True,
        capabilities=REQUIRED_TX_CAPABILITIES
        | {RadioTransportCapability.TRANSMISSION_CANCEL},
    )
    router = _started_router(adapter)
    try:
        router.submit(_request("active-supported-cancel"))
        assert adapter.entered.wait(1)
        result = router.cancel("active-supported-cancel")
        assert result.cancelled
        assert adapter.cancel_calls == ["active-supported-cancel"]
        _wait_state(
            router,
            "active-supported-cancel",
            RadioTransmissionState.CANCELLED,
        )
    finally:
        router.shutdown()


def test_identical_replay_transmits_once_and_conflicting_replay_fails_closed() -> None:
    adapter = FakeRadioTransportAdapter()
    router = _started_router(adapter)
    try:
        original = _request("replay-id")
        assert router.submit(original).accepted
        assert router.wait("replay-id", 2) is not None

        replay = router.submit(original)
        conflict = router.submit(_request("replay-id", pcm=b"\x01\x00" * 441))
        assert replay.accepted and replay.replayed
        assert not conflict.accepted
        assert conflict.failure is not None
        assert conflict.failure.code is RadioFailureCode.INVALID_CONTEXT
        assert len(adapter.transmit_calls) == 1
        assert (
            sum(
                event.stage is RadioDiagnosticStage.COMPLETED
                for event in router.diagnostic_snapshot()
            )
            == 1
        )
    finally:
        router.shutdown()


@pytest.mark.parametrize(
    ("outcome", "expected_code"),
    [
        ("fail", RadioFailureCode.TX_TIMEOUT),
        ("raise", RadioFailureCode.TRANSPORT_ERROR),
    ],
)
def test_adapter_failures_are_typed_and_normalized(
    outcome: Literal["fail", "raise"],
    expected_code: RadioFailureCode,
) -> None:
    adapter = FakeRadioTransportAdapter(outcome=outcome)
    router = _started_router(adapter)
    try:
        router.submit(_request(f"failure-{outcome}"))
        failed = router.wait(f"failure-{outcome}", 2)
        assert failed is not None
        assert failed.state is RadioTransmissionState.FAILED
        assert failed.failure is not None
        assert failed.failure.code is expected_code
        assert "secret" not in failed.failure.message
        assert "sensitive" not in failed.failure.message
    finally:
        router.shutdown()


def test_shutdown_cancels_queued_work_and_is_idempotent() -> None:
    adapter = FakeRadioTransportAdapter(block=True)
    router = _started_router(adapter)
    router.submit(_request("shutdown-active"))
    assert adapter.entered.wait(1)
    router.submit(_request("shutdown-queued"))

    first = router.shutdown(1)
    second = router.shutdown(1)
    queued = router.get("shutdown-queued")
    rejected = router.submit(_request("after-shutdown"))

    assert first.clean
    assert first.queued_cancelled == 1
    assert first.adapters_stopped == 1
    assert first.worker_stopped
    assert not first.already_stopped
    assert second.already_stopped
    assert adapter.shutdown_calls == 1
    assert queued is not None and queued.state is RadioTransmissionState.CANCELLED
    assert rejected.failure is not None
    assert rejected.failure.code is RadioFailureCode.NOT_READY


def test_failed_adapter_shutdown_is_bounded_and_reported() -> None:
    adapter = FakeRadioTransportAdapter(shutdown_success=False)
    router = _started_router(adapter)
    result = router.shutdown(0.5)
    assert not result.clean
    assert result.adapter_shutdown_failures == 1
    assert result.worker_stopped
