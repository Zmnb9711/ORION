from __future__ import annotations

import threading
from dataclasses import replace

import pytest
from pydantic import ValidationError

from orion.communication_contracts import CommunicationDomain, CommunicationPriority
from orion.radio_contracts import (
    REQUIRED_TX_CAPABILITIES,
    FinalizedPcmAudio,
    RadioAdapterOutcome,
    RadioContext,
    RadioEntityRef,
    RadioFailureCode,
    RadioModulation,
    RadioReadiness,
    RadioTransmissionRequest,
    RadioTransmissionState,
)
from orion.radio_router import RadioRouter
from orion.srs_protocol import AM, FM
from orion.srs_radio_adapter import (
    SRS_ADAPTER_ID,
    SrsAdapterRuntime,
    SrsRadioTransportAdapter,
    SrsTxCompletion,
    map_srs_readiness,
    radio_modulation_from_srs,
    radio_modulation_to_srs,
)
from orion.srs_radio_transport import SrsState


class FakeSrsPort:
    def __init__(
        self,
        runtime: SrsAdapterRuntime | None = None,
        *,
        failure: BaseException | None = None,
        block: bool = False,
    ) -> None:
        self.runtime = runtime or _runtime()
        self.failure = failure
        self.block = block
        self.calls: list[tuple[str, bytes, float]] = []
        self.shutdown_calls: list[float] = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def srs_adapter_runtime(self) -> SrsAdapterRuntime:
        return self.runtime

    def transmit_srs_pcm(
        self,
        tx_correlation_id: str,
        pcm44: bytes,
        timeout_s: float,
    ) -> SrsTxCompletion:
        self.calls.append((tx_correlation_id, pcm44, timeout_s))
        self.entered.set()
        if self.block:
            assert self.release.wait(2)
        if self.failure is not None:
            raise self.failure
        return SrsTxCompletion(
            queue_to_first_tx_ms=2.0,
            queue_to_complete_ms=82.0,
            frame_count=2,
            duration_ms=80.0,
        )

    def shutdown_srs_adapter(self, timeout_s: float) -> bool:
        self.shutdown_calls.append(timeout_s)
        self.release.set()
        self.runtime = replace(
            self.runtime,
            state=SrsState.STOPPED,
            endpoint_started=False,
            radio_registered=False,
            udp_registered=False,
        )
        return True


def _runtime(**updates: object) -> SrsAdapterRuntime:
    values: dict[str, object] = {
        "state": SrsState.READY,
        "endpoint_started": True,
        "radio_registered": True,
        "udp_registered": True,
        "frequency_hz": 251_000_000.0,
        "modulation": AM,
        "bot_name": "ORION SRS",
        "coalition": 2,
        "failed": False,
    }
    values.update(updates)
    return SrsAdapterRuntime(**values)


def _request(
    tx_id: str = "srs-adapter-tx",
    *,
    frequency_hz: float = 251_000_000.0,
    modulation: RadioModulation = RadioModulation.AM,
    callsign: str = "ORION SRS",
    coalition: str | None = "blue",
    sample_rate_hz: int = 44_100,
    pcm: bytes = b"\x00\x00" * 882,
    timeout_s: float = 2.0,
) -> RadioTransmissionRequest:
    return RadioTransmissionRequest(
        context=RadioContext(
            tx_correlation_id=tx_id,
            source_domain=CommunicationDomain.GENERAL,
            radio_entity=RadioEntityRef(
                entity_id="orion.srs.test",
                operational_callsign=callsign,
                coalition=coalition,
            ),
            target_frequency_hz=frequency_hz,
            modulation=modulation,
            communication_priority=CommunicationPriority.IMPORTANT,
        ),
        audio=FinalizedPcmAudio(pcm=pcm, sample_rate_hz=sample_rate_hz),
        transport_id=SRS_ADAPTER_ID,
        timeout_s=timeout_s,
    )


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (SrsState.DISCONNECTED, RadioReadiness.UNAVAILABLE),
        (SrsState.CONNECTING_TCP, RadioReadiness.STARTING),
        (SrsState.SYNCING, RadioReadiness.STARTING),
        (SrsState.AUTHENTICATING_EAM, RadioReadiness.STARTING),
        (SrsState.REGISTERING_RADIO, RadioReadiness.STARTING),
        (SrsState.RADIO_REGISTERED, RadioReadiness.STARTING),
        (SrsState.REGISTERING_UDP, RadioReadiness.STARTING),
        (SrsState.READY, RadioReadiness.READY),
        (SrsState.ERROR, RadioReadiness.ERROR),
        (SrsState.STOPPING, RadioReadiness.STOPPING),
        (SrsState.STOPPED, RadioReadiness.STOPPED),
    ],
)
def test_readiness_mapping_is_truthful(
    state: SrsState,
    expected: RadioReadiness,
) -> None:
    assert map_srs_readiness(_runtime(state=state)) is expected


def test_ready_without_both_registration_prerequisites_is_degraded() -> None:
    assert map_srs_readiness(_runtime(udp_registered=False)) is RadioReadiness.DEGRADED
    assert (
        map_srs_readiness(_runtime(radio_registered=False)) is RadioReadiness.DEGRADED
    )
    assert map_srs_readiness(_runtime(failed=True)) is RadioReadiness.ERROR


def test_adapter_identity_capabilities_and_truthful_cancellation() -> None:
    adapter = SrsRadioTransportAdapter(FakeSrsPort())
    assert adapter.transport_id == "srs"
    assert adapter.capabilities() == REQUIRED_TX_CAPABILITIES
    assert adapter.start().readiness is RadioReadiness.READY
    assert adapter.cancel("active-srs-tx") is False


@pytest.mark.parametrize(
    ("generic", "wire"),
    [(RadioModulation.AM, AM), (RadioModulation.FM, FM)],
)
def test_am_and_fm_mapping_is_explicit(
    generic: RadioModulation,
    wire: int,
) -> None:
    assert radio_modulation_to_srs(generic) == wire
    assert radio_modulation_from_srs(wire) is generic


def test_adapter_transmits_pcm_exactly_once_and_maps_completion() -> None:
    port = FakeSrsPort()
    events: list[tuple[str, dict[str, object]]] = []
    adapter = SrsRadioTransportAdapter(
        port,
        diagnostic=lambda event, fields: events.append((event, fields)),
    )
    adapter.start()
    request = _request(timeout_s=3.0)

    result = adapter.transmit(request)

    assert result.outcome is RadioAdapterOutcome.COMPLETED
    assert result.tx_correlation_id == "srs-adapter-tx"
    assert result.frame_count == 2
    assert result.duration_ms == 80.0
    assert result.started_at is not None
    assert result.completed_at > result.started_at
    assert port.calls == [("srs-adapter-tx", request.audio.pcm, 3.0)]
    assert [event for event, _fields in events] == [
        "srs_adapter_started",
        "srs_adapter_tx_started",
        "srs_adapter_tx_completed",
    ]
    assert all(
        "pcm" not in fields and "audio" not in fields for _event, fields in events
    )


def test_fm_request_uses_same_adapter_mapping_when_endpoint_is_registered_for_fm() -> (
    None
):
    port = FakeSrsPort(_runtime(modulation=FM))
    adapter = SrsRadioTransportAdapter(port)
    adapter.start()
    result = adapter.transmit(_request(modulation=RadioModulation.FM))
    assert result.outcome is RadioAdapterOutcome.COMPLETED
    assert len(port.calls) == 1


@pytest.mark.parametrize(
    "candidate",
    [
        _request(frequency_hz=264_500_000),
        _request(modulation=RadioModulation.FM),
        _request(callsign="Different Bot"),
        _request(coalition="red"),
    ],
)
def test_registered_radio_context_mismatch_fails_without_srs_enqueue(
    candidate: RadioTransmissionRequest,
) -> None:
    port = FakeSrsPort()
    adapter = SrsRadioTransportAdapter(port)
    adapter.start()
    result = adapter.transmit(candidate)
    assert result.failure is not None
    assert result.failure.code is RadioFailureCode.RADIO_UNAVAILABLE
    assert port.calls == []


def test_unsupported_pcm_rate_fails_before_existing_resampler() -> None:
    port = FakeSrsPort()
    adapter = SrsRadioTransportAdapter(port)
    adapter.start()
    result = adapter.transmit(_request(sample_rate_hz=48_000))
    assert result.failure is not None
    assert result.failure.code is RadioFailureCode.UNSUPPORTED_CAPABILITY
    assert port.calls == []


def test_not_ready_is_typed_and_does_not_enqueue() -> None:
    port = FakeSrsPort(_runtime(state=SrsState.REGISTERING_UDP))
    adapter = SrsRadioTransportAdapter(port)
    adapter.start()
    result = adapter.transmit(_request())
    assert result.failure is not None
    assert result.failure.code is RadioFailureCode.NOT_READY
    assert port.calls == []


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (TimeoutError("secret timeout detail"), RadioFailureCode.TX_TIMEOUT),
        (
            ConnectionError("secret socket detail"),
            RadioFailureCode.TRANSPORT_UNAVAILABLE,
        ),
        (RuntimeError("secret queue detail"), RadioFailureCode.TX_REJECTED),
        (Exception("secret protocol detail"), RadioFailureCode.TRANSPORT_ERROR),
    ],
)
def test_srs_failures_are_normalized_without_raw_detail(
    exception: BaseException,
    expected: RadioFailureCode,
) -> None:
    port = FakeSrsPort(failure=exception)
    events: list[tuple[str, dict[str, object]]] = []
    adapter = SrsRadioTransportAdapter(
        port,
        diagnostic=lambda event, fields: events.append((event, fields)),
    )
    adapter.start()
    result = adapter.transmit(_request())
    assert result.failure is not None
    assert result.failure.code is expected
    assert "secret" not in result.failure.message
    assert "secret" not in repr(events)


def test_router_replay_and_conflict_preserve_exactly_once_srs_transmission() -> None:
    port = FakeSrsPort()
    adapter = SrsRadioTransportAdapter(port)
    router = RadioRouter(default_transport_id="srs", queue_capacity=1)
    router.register_adapter(adapter)
    router.start()
    try:
        request = _request("replay-srs")
        assert router.submit(request).accepted
        completed = router.wait("replay-srs", 2)
        assert completed is not None
        assert completed.state is RadioTransmissionState.COMPLETED
        replay = router.submit(request)
        conflict = router.submit(_request("replay-srs", pcm=b"\x01\x00" * 882))
        assert replay.accepted and replay.replayed
        assert not conflict.accepted
        assert conflict.failure is not None
        assert conflict.failure.code is RadioFailureCode.INVALID_CONTEXT
        assert len(port.calls) == 1
    finally:
        router.shutdown()


def test_router_queued_cancel_never_reaches_srs_and_active_cancel_is_unsupported() -> (
    None
):
    port = FakeSrsPort(block=True)
    adapter = SrsRadioTransportAdapter(port)
    router = RadioRouter(default_transport_id="srs", queue_capacity=1)
    router.register_adapter(adapter)
    router.start()
    try:
        assert router.submit(_request("active-srs")).accepted
        assert port.entered.wait(1)
        assert router.submit(_request("queued-srs")).accepted
        queued = router.cancel("queued-srs")
        active = router.cancel("active-srs")
        assert queued.cancelled
        assert not active.cancelled
        assert active.failure is not None
        assert active.failure.code is RadioFailureCode.UNSUPPORTED_CAPABILITY
        port.release.set()
        assert router.wait("active-srs", 2) is not None
        assert [call[0] for call in port.calls] == ["active-srs"]
    finally:
        router.shutdown()


def test_adapter_shutdown_is_bounded_idempotent_and_stops_port() -> None:
    port = FakeSrsPort()
    adapter = SrsRadioTransportAdapter(port)
    adapter.start()
    assert adapter.shutdown(0.5)
    assert adapter.shutdown(0.5)
    assert port.shutdown_calls == [0.5]
    assert adapter.status().readiness is RadioReadiness.STOPPED


def test_radio_request_timeout_is_bounded_and_part_of_validation() -> None:
    with pytest.raises(ValidationError):
        _request(timeout_s=0)
    with pytest.raises(ValidationError):
        _request(timeout_s=121)
