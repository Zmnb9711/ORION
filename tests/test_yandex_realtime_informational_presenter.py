from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from orion.aircraft_identity_query import (
    AIRCRAFT_IDENTITY_SEMANTIC_POLICY,
    AircraftIdentityFormulationError,
    AircraftIdentityQueryResult,
    AircraftIdentityQueryStatus,
    AircraftIdentityRealtimeCandidateService,
)
from orion.aircraft_identity_presentation import AircraftIdentityShellValidationError
from orion.semantic_response_validation import (
    SemanticClaimCategory,
    SemanticConformanceResult,
    SemanticConformanceRequest,
    SemanticConformanceVerdict,
    SemanticValidationError,
    SemanticValidationErrorCode,
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


def _semantic_request() -> SemanticConformanceRequest:
    return SemanticConformanceRequest(
        request_id="semantic-request-1",
        semantic_response_id=INTERACTION_ID,
        interaction_id=INTERACTION_ID,
        policy=AIRCRAFT_IDENTITY_SEMANTIC_POLICY,
        language="ru-RU",
        fact_state="known",
        required_marker="{{aircraft_identity}}",
        candidate_text="Вы сейчас находитесь в {{aircraft_identity}}.",
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
        self.connected = False
        self.closed = False

    async def connect(self) -> None:
        self.connected = True

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)
        if payload.get("type") == "session.update":
            self.events.put_nowait(
                {"type": "session.updated", "session": {"id": "session-1"}}
            )
            return
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


async def _semantic_judge_reuses_the_same_fact_free_text_session() -> None:
    transports: list[_Transport] = []

    def factory(config: YandexRealtimeTextConfig) -> _Transport:
        transport = _Transport(config)
        transports.append(transport)
        return transport

    presenter = YandexRealtimeInformationalPresenter(
        YandexRealtimeTextConfig(api_key="secret", folder_id="folder"),
        transport_factory=factory,
    )
    await presenter.connect()
    await presenter.formulate(_request())
    transports[0].response_text = (
        '{"verdict":"conformant","unsupported_categories":[]}'
    )
    result = await presenter.evaluate_semantic_conformance(_semantic_request())
    assert result.verdict is SemanticConformanceVerdict.CONFORMANT
    assert result.session_reused is True
    assert len(transports) == 1
    updates = [
        payload for payload in transports[0].sent if payload.get("type") == "session.update"
    ]
    assert len(updates) == 3
    assert "semantic-conformance classifier" in updates[1]["session"]["instructions"]
    assert updates[2]["session"]["instructions"] == updates[0]["session"]["instructions"]
    judge_item = next(
        payload
        for payload in transports[0].sent
        if payload.get("type") == "conversation.item.create"
        and str(payload.get("event_id", "")).startswith("orion-semantic-item-")
    )
    judge_input = judge_item["item"]["content"][0]["text"]
    assert "FA-18" not in judge_input
    assert "secret" not in judge_input
    assert "candidate_text" in judge_input
    event_names = [str(item["event"]) for item in presenter.diagnostic_snapshot()]
    assert "semantic_validation_started" in event_names
    assert "semantic_validation_completed" in event_names
    await presenter.close()


def test_semantic_judge_reuses_the_same_fact_free_text_session() -> None:
    asyncio.run(_semantic_judge_reuses_the_same_fact_free_text_session())


async def _semantic_judge_malformed_output_fails_closed() -> None:
    presenter = YandexRealtimeInformationalPresenter(
        YandexRealtimeTextConfig(api_key="secret", folder_id="folder"),
        transport_factory=lambda config: _Transport(config, response_text="not-json"),
    )
    await presenter.connect()
    with pytest.raises(SemanticValidationError) as caught:
        await presenter.evaluate_semantic_conformance(_semantic_request())
    assert caught.value.code is SemanticValidationErrorCode.JUDGE_PROTOCOL
    await presenter.close()


def test_semantic_judge_malformed_output_fails_closed() -> None:
    asyncio.run(_semantic_judge_malformed_output_fails_closed())


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


class _FakeSemanticJudge:
    def __init__(
        self,
        *,
        verdict: SemanticConformanceVerdict,
        categories: tuple[SemanticClaimCategory, ...] = (),
    ) -> None:
        self.verdict = verdict
        self.categories = categories
        self.requests: list[SemanticConformanceRequest] = []

    async def evaluate_semantic_conformance(
        self,
        request: SemanticConformanceRequest,
    ) -> SemanticConformanceResult:
        self.requests.append(request)
        return SemanticConformanceResult(
            request_id=request.request_id,
            verdict=self.verdict,
            unsupported_categories=self.categories,
            provider_id="fake.semantic.judge",
            provider_response_id="judge-response-1",
            latency_ms=6,
            session_reused=True,
        )


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


def _unavailable_result() -> AircraftIdentityQueryResult:
    return AircraftIdentityQueryResult(
        status=AircraftIdentityQueryStatus.UNAVAILABLE,
        raw_aircraft_id=None,
        display_name=None,
        fact_status=WorldFactStatus.UNAVAILABLE,
        source=WorldFactSource.DCS_EXPORT,
        authority=WorldFactAuthority.AUTHORITATIVE,
        observed_at=None,
        age_seconds=None,
        generation=7,
        unavailable_reason="source_not_connected",
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


@pytest.mark.parametrize(
    ("text", "language"),
    (
        ("Вы сейчас находитесь в {{aircraft_identity}}.", "ru-RU"),
        (
            "Воздушное судно, выполняющее текущий полёт, имеет идентификатор "
            "{{aircraft_identity}}.",
            "ru-RU",
        ),
        ("Current aircraft identity: {{aircraft_identity}}.", "en-US"),
        (
            "The aircraft identity currently associated with the flight is "
            "{{aircraft_identity}}.",
            "en-US",
        ),
    ),
)
def test_semantic_candidate_accepts_safe_natural_ru_en_without_grammar_rules(
    text: str,
    language: str,
) -> None:
    async def run() -> None:
        presenter = _FakePresenter(text)
        judge = _FakeSemanticJudge(verdict=SemanticConformanceVerdict.CONFORMANT)
        outcome = await AircraftIdentityRealtimeCandidateService(
            query=_StaticQuery(_known_result())
        ).execute(
            presenter=presenter,  # type: ignore[arg-type]
            semantic_validator=judge,
            interaction_id=INTERACTION_ID,
            language=language,  # type: ignore[arg-type]
        )
        assert outcome.validation_model == "semantic_conformance"
        assert outcome.final_text.count("F/A-18C Hornet") == 1
        assert outcome.semantic_judge_response_id == "judge-response-1"
        assert "FA-18" not in judge.requests[0].provider_input()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("text", "category"),
    (
        (
            "Вы в {{aircraft_identity}}, второй самолёт относится к типу МиГ.",
            SemanticClaimCategory.SECOND_ENTITY_IDENTITY,
        ),
        (
            "Вы в {{aircraft_identity}}, высота большая.",
            SemanticClaimCategory.ALTITUDE,
        ),
        (
            "Вы в {{aircraft_identity}}, топлива достаточно.",
            SemanticClaimCategory.FUEL,
        ),
        (
            "Вы в {{aircraft_identity}}, курс северный.",
            SemanticClaimCategory.HEADING,
        ),
        (
            "Вы в {{aircraft_identity}}, позиция известна.",
            SemanticClaimCategory.POSITION,
        ),
        (
            "Вы в {{aircraft_identity}}, радиочастота настроена.",
            SemanticClaimCategory.RADIO_FREQUENCY,
        ),
        (
            "Вы в {{aircraft_identity}}, TACAN доступен.",
            SemanticClaimCategory.TACAN,
        ),
        (
            "Вы в {{aircraft_identity}}, миссия продолжается.",
            SemanticClaimCategory.MISSION_STATE,
        ),
        (
            "Вы в {{aircraft_identity}}, код — девять.",
            SemanticClaimCategory.NUMERIC_IDENTIFIER,
        ),
        (
            "Вы в {{aircraft_identity}}, полёт продолжается штатно.",
            SemanticClaimCategory.OPERATIONAL_ASSERTION,
        ),
        (
            "Возможно, вы в {{aircraft_identity}}.",
            SemanticClaimCategory.UNCERTAINTY_DRIFT,
        ),
    ),
)
def test_semantic_candidate_rejects_adversarial_meaning_before_downstream(
    text: str,
    category: SemanticClaimCategory,
) -> None:
    async def run() -> None:
        presenter = _FakePresenter(text)
        judge = _FakeSemanticJudge(
            verdict=SemanticConformanceVerdict.NONCONFORMANT,
            categories=(category,),
        )
        with pytest.raises(SemanticValidationError) as caught:
            await AircraftIdentityRealtimeCandidateService(
                query=_StaticQuery(_known_result())
            ).execute(
                presenter=presenter,  # type: ignore[arg-type]
                semantic_validator=judge,
                interaction_id=INTERACTION_ID,
                language="ru-RU",
            )
        assert caught.value.code is SemanticValidationErrorCode.JUDGE_REJECTED
        assert "core_fact_binding_completed" not in presenter.events

    asyncio.run(run())


def test_semantic_candidate_rejects_identity_leak_before_judge() -> None:
    async def run() -> None:
        presenter = _FakePresenter(
            "Вы в F/A-18C Hornet, то есть в {{aircraft_identity}}."
        )
        judge = _FakeSemanticJudge(verdict=SemanticConformanceVerdict.CONFORMANT)
        with pytest.raises(AircraftIdentityShellValidationError):
            await AircraftIdentityRealtimeCandidateService(
                query=_StaticQuery(_known_result())
            ).execute(
                presenter=presenter,  # type: ignore[arg-type]
                semantic_validator=judge,
                interaction_id=INTERACTION_ID,
                language="ru-RU",
            )
        assert judge.requests == []
        assert "core_fact_binding_completed" not in presenter.events

    asyncio.run(run())


def test_semantic_candidate_rejects_wrong_unavailable_claim_before_downstream() -> None:
    async def run() -> None:
        presenter = _FakePresenter(
            "Вы находитесь в самолёте, но {{aircraft_unavailable}}."
        )
        judge = _FakeSemanticJudge(
            verdict=SemanticConformanceVerdict.NONCONFORMANT,
            categories=(SemanticClaimCategory.WRONG_FACT_STATE,),
        )
        with pytest.raises(SemanticValidationError) as caught:
            await AircraftIdentityRealtimeCandidateService(
                query=_StaticQuery(_unavailable_result())
            ).execute(
                presenter=presenter,  # type: ignore[arg-type]
                semantic_validator=judge,
                interaction_id=INTERACTION_ID,
                language="ru-RU",
            )
        assert caught.value.code is SemanticValidationErrorCode.JUDGE_REJECTED
        assert "core_fact_binding_completed" not in presenter.events

    asyncio.run(run())


def test_request_requires_a_natural_language_shell_for_unavailable_fact() -> None:
    request = _request().model_copy(
        update={
            "required_marker": "{{aircraft_unavailable}}",
            "fact_status": "unavailable",
        }
    )
    instructions = request.response_instructions()
    assert "ordinary Cyrillic Russian words around the marker" in instructions
    assert "marker alone is not a sentence" in instructions
    assert "authoritative aircraft information is unavailable" in instructions


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
