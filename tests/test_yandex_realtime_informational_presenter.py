from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from orion.aircraft_identity_query import (
    AircraftIdentityFormulationError,
    AircraftIdentityQueryResult,
    AircraftIdentityQueryStatus,
    AircraftIdentityRealtimeCandidateService,
)
from orion.world_model_contracts import (
    WorldFactAuthority,
    WorldFactSource,
    WorldFactStatus,
)
from orion.yandex_realtime_informational_presenter import (
    InformationalPresenterError,
    InformationalPresenterErrorCode,
    InformationalPresenterState,
    RealtimeInformationalRequest,
    RealtimeInformationalResult,
    RealtimeTextResponseAssembler,
    YandexRealtimeInformationalPresenter,
    YandexRealtimeTextConfig,
)


INTERACTION_ID = UUID("12345678-1234-5678-1234-567812345678")


def _request(request_id: str = "request-1") -> RealtimeInformationalRequest:
    return RealtimeInformationalRequest(
        request_id=request_id,
        semantic_meaning="flight.current_aircraft_identity",
        language="ru-RU",
        required_marker="{{aircraft_identity}}",
        fact_status="available",
        fact_source="dcs_export",
        fact_authority="authoritative",
        fact_generation=7,
        freshness_status="known",
    )


class _Transport:
    def __init__(
        self,
        _config: YandexRealtimeTextConfig,
        *,
        response_text: str = "Вы сейчас находитесь в {{aircraft_identity}}.",
        block_response: asyncio.Event | None = None,
        stall_after_created: bool = False,
    ) -> None:
        self.response_text = response_text
        self.block_response = block_response
        self.stall_after_created = stall_after_created
        self.sent: list[dict[str, object]] = []
        self.events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.events.put_nowait({"type": "session.updated", "session": {"id": "session-1"}})
        self.connected = False
        self.closed = False

    async def connect(self) -> None:
        self.connected = True

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)
        if payload.get("type") != "response.create":
            return
        if self.block_response is not None:
            await self.block_response.wait()
        response_id = "response-1"
        self.events.put_nowait(
            {"type": "response.created", "response": {"id": response_id}}
        )
        if self.stall_after_created:
            return
        self.events.put_nowait(
            {
                "type": "response.output_text.delta",
                "response_id": response_id,
                "delta": self.response_text,
            }
        )
        self.events.put_nowait(
            {
                "type": "response.output_text.done",
                "response_id": response_id,
                "text": self.response_text,
            }
        )
        self.events.put_nowait(
            {
                "type": "response.done",
                "response": {"id": response_id, "status": "completed"},
            }
        )

    async def receive_json(self) -> dict[str, Any]:
        return await self.events.get()

    async def close(self) -> None:
        self.closed = True


async def _presenter_is_explicit_text_only_ready_and_reuses_one_session() -> None:
    transports: list[_Transport] = []

    def factory(config: YandexRealtimeTextConfig) -> _Transport:
        transport = _Transport(config)
        transports.append(transport)
        return transport

    presenter = YandexRealtimeInformationalPresenter(
        YandexRealtimeTextConfig(api_key="secret", folder_id="folder"),
        transport_factory=factory,
    )
    assert presenter.state is InformationalPresenterState.DISCONNECTED
    assert presenter.queue_maxsize == 1
    assert await presenter.connect() is False
    assert await presenter.connect() is True
    assert presenter.session_id == "session-1"

    first = await presenter.formulate(_request())
    second = await presenter.formulate(_request("request-2"))
    assert first.output_text == "Вы сейчас находитесь в {{aircraft_identity}}."
    assert first.session_reused is False
    assert second.session_reused is True
    assert len(transports) == 1
    assert all(
        payload.get("type") not in {"input_audio_buffer.append", "input_audio_buffer.commit"}
        for payload in transports[0].sent
    )
    session = transports[0].sent[0]["session"]
    assert session == {
        "instructions": transports[0].sent[0]["session"]["instructions"],
        "output_modalities": ["text"],
    }
    provider_input = transports[0].sent[1]["item"]["content"][0]["text"]
    assert "FA-18" not in provider_input
    assert "secret" not in str(presenter.diagnostic_snapshot())
    await presenter.close()


def test_presenter_is_explicit_text_only_ready_and_reuses_one_session() -> None:
    asyncio.run(_presenter_is_explicit_text_only_ready_and_reuses_one_session())


async def _presenter_busy_request_is_rejected_without_hidden_wait() -> None:
    release = asyncio.Event()
    holder: list[_Transport] = []

    def factory(config: YandexRealtimeTextConfig) -> _Transport:
        transport = _Transport(config, block_response=release)
        holder.append(transport)
        return transport

    presenter = YandexRealtimeInformationalPresenter(
        YandexRealtimeTextConfig(api_key="secret", folder_id="folder"),
        transport_factory=factory,
    )
    await presenter.connect()
    first = asyncio.create_task(presenter.formulate(_request()))
    await asyncio.sleep(0)
    with pytest.raises(InformationalPresenterError) as caught:
        await presenter.formulate(_request("request-2"))
    assert caught.value.code is InformationalPresenterErrorCode.BUSY
    release.set()
    await first
    await presenter.close()


def test_presenter_busy_request_is_rejected_without_hidden_wait() -> None:
    asyncio.run(_presenter_busy_request_is_rejected_without_hidden_wait())


async def _presenter_ready_gate_timeout_cancel_and_reconnect() -> None:
    transports: list[_Transport] = []

    def factory(config: YandexRealtimeTextConfig) -> _Transport:
        transport = _Transport(config, stall_after_created=not transports)
        transports.append(transport)
        return transport

    presenter = YandexRealtimeInformationalPresenter(
        YandexRealtimeTextConfig(
            api_key="secret",
            folder_id="folder",
            request_timeout_s=0.01,
            reconnect_delay_s=0.001,
        ),
        transport_factory=factory,
    )
    with pytest.raises(InformationalPresenterError) as not_ready:
        await presenter.formulate(_request())
    assert not_ready.value.code is InformationalPresenterErrorCode.UNAVAILABLE

    await presenter.connect()
    with pytest.raises(InformationalPresenterError) as timed_out:
        await presenter.formulate(_request())
    assert timed_out.value.code is InformationalPresenterErrorCode.TIMEOUT
    assert any(payload.get("type") == "response.cancel" for payload in transports[0].sent)
    assert transports[0].closed is True
    await asyncio.sleep(0.02)
    assert presenter.state is InformationalPresenterState.READY
    assert len(transports) == 2
    result = await presenter.formulate(_request("request-2"))
    assert result.output_text
    event_names = [str(item["event"]) for item in presenter.diagnostic_snapshot()]
    assert "formulation_cancel_requested" in event_names
    assert "formulation_session_reconnect_scheduled" in event_names
    await presenter.close()


def test_presenter_ready_gate_timeout_cancel_and_reconnect() -> None:
    asyncio.run(_presenter_ready_gate_timeout_cancel_and_reconnect())


def test_response_assembler_requires_matching_complete_text_and_terminal_success() -> None:
    events: list[tuple[str, dict[str, object]]] = []

    def record(event: str, **metadata: object) -> None:
        events.append((event, metadata))

    assembler = RealtimeTextResponseAssembler(
        generation=3,
        request_id="request-1",
        started=0.0,
        record=record,
    )
    assembler.handle({"type": "response.created", "response": {"id": "r1"}}, generation=3)
    assembler.handle(
        {"type": "response.done", "response": {"id": "r1", "status": "completed"}},
        generation=3,
    )
    assert assembler.completed is False
    assembler.handle(
        {"type": "response.output_text.done", "response_id": "r1", "text": "Hello {{aircraft_identity}}."},
        generation=3,
    )
    assert assembler.completed is True
    assembler.handle(
        {"type": "response.done", "response": {"id": "r1", "status": "completed"}},
        generation=3,
    )
    assembler.invalidate()
    assembler.handle(
        {"type": "response.output_text.delta", "response_id": "r1", "delta": "late"},
        generation=4,
    )
    assert any(event == "formulation_late_response_ignored" for event, _ in events)


class _StaticQuery:
    def __init__(self, result: AircraftIdentityQueryResult) -> None:
        self.result = result

    def resolve(self) -> AircraftIdentityQueryResult:
        return self.result


class _FakePresenter:
    provider_id = "yandex.realtime.text"

    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[RealtimeInformationalRequest] = []
        self.events: list[str] = []

    async def formulate(self, request: RealtimeInformationalRequest) -> RealtimeInformationalResult:
        self.requests.append(request)
        return RealtimeInformationalResult(
            request_id=request.request_id,
            provider_response_id="response-1",
            output_text=self.text,
            first_token_latency_ms=5,
            complete_latency_ms=8,
            session_reused=True,
        )

    def record_event(self, event: str, **_metadata: object) -> None:
        self.events.append(event)


def _known_result() -> AircraftIdentityQueryResult:
    return AircraftIdentityQueryResult(
        status=AircraftIdentityQueryStatus.AVAILABLE,
        raw_aircraft_id="FA-18C_hornet",
        display_name="F/A-18C Hornet",
        fact_status=WorldFactStatus.KNOWN,
        source=WorldFactSource.DCS_EXPORT,
        authority=WorldFactAuthority.AUTHORITATIVE,
        observed_at=datetime(2026, 9, 3, tzinfo=UTC),
        age_seconds=1,
        generation=7,
    )


async def _in_memory_candidate_preserves_core_fact_and_one_final_response() -> None:
    presenter = _FakePresenter("Вы сейчас находитесь в {{aircraft_identity}}.")
    service = AircraftIdentityRealtimeCandidateService(query=_StaticQuery(_known_result()))
    outcome = await service.execute(
        presenter=presenter,  # type: ignore[arg-type]
        interaction_id=INTERACTION_ID,
        language="ru-RU",
    )
    assert outcome.final_text == "Вы сейчас находитесь в F/A-18C Hornet."
    assert outcome.provider_fact_authority is False
    assert outcome.semantic_response.authoritative_facts[0].value == "FA-18C_hornet"
    assert presenter.requests[0].provider_fact_authority is False
    assert "FA-18" not in presenter.requests[0].provider_input()
    assert presenter.events == [
        "formulation_validation_completed",
        "core_fact_binding_completed",
    ]


def test_in_memory_candidate_preserves_core_fact_and_one_final_response() -> None:
    asyncio.run(_in_memory_candidate_preserves_core_fact_and_one_final_response())


async def _invalid_candidate_stops_before_downstream_seam() -> None:
    presenter = _FakePresenter(
        "Вы в {{aircraft_identity}} и топливо заканчивается."
    )
    service = AircraftIdentityRealtimeCandidateService(query=_StaticQuery(_known_result()))
    downstream_calls = 0
    with pytest.raises(AircraftIdentityFormulationError):
        await service.execute(
            presenter=presenter,  # type: ignore[arg-type]
            interaction_id=INTERACTION_ID,
            language="ru-RU",
        )
    assert downstream_calls == 0
    assert "core_fact_binding_completed" not in presenter.events


def test_invalid_candidate_stops_before_downstream_seam() -> None:
    asyncio.run(_invalid_candidate_stops_before_downstream_seam())
