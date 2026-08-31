from __future__ import annotations

import asyncio
import io
import json
import queue
import threading
import wave
import zipfile
from collections.abc import Callable
from typing import cast

import pytest

from orion.realtime_audio_transport import (
    FinalizedUserUtterance,
    RealtimeInputTransmissionCompleted,
    RealtimeInputTransmissionStarted,
    RealtimePcmFormat,
)
from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
from orion.yandex_live_diagnostics import YandexLiveDiagnostics
from orion.yandex_speechkit_stt import (
    SPEECHKIT_STT_LANGUAGE,
    SPEECHKIT_STT_MODEL,
    SpeechKitProviderEvent,
    SpeechKitSttProtocolError,
    SpeechKitV3RadioSttAdapter,
    speechkit_session_options,
)


class FakeEndpoint:
    transport_id = "srs"
    pcm_format = RealtimePcmFormat(sample_rate=16_000)

    def __init__(self) -> None:
        self.items: queue.Queue[object] = queue.Queue(maxsize=32)
        self.started = False
        self.stopped = False
        self.error: BaseException | None = None

    def start(self) -> None:
        self.started = True

    def read_input(self, timeout: float = 0.1):  # noqa: ANN202
        try:
            return self.items.get(timeout=timeout)
        except queue.Empty:
            return None

    def failure(self) -> BaseException | None:
        return self.error

    def stop(self) -> None:
        self.stopped = True

    def add_turn(self, transmission_id: str, pcm: bytes = bytes(640)) -> None:
        self.items.put_nowait(RealtimeInputTransmissionStarted(transmission_id))
        self.items.put_nowait(pcm)
        self.items.put_nowait(RealtimeInputTransmissionCompleted(transmission_id))


class FakeDiagnostics:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def record(self, event: str, **fields: object) -> None:
        self.events.append((event, fields))


def provider_turn(index: int, text: str) -> list[SpeechKitProviderEvent]:
    cursor = (index + 1) * 1_000
    common = {
        "session_uuid": "provider-session-1",
        "final_index": index,
        "received_data_ms": cursor,
        "final_time_ms": cursor,
        "eou_time_ms": cursor,
    }
    return [
        SpeechKitProviderEvent(kind="partial", transcript=text[:3], **common),
        SpeechKitProviderEvent(kind="final", transcript=text, **common),
        SpeechKitProviderEvent(kind="eou_update", **common),
    ]


def empty_provider_turn(
    index: int,
    *,
    eou_update_first: bool = False,
) -> list[SpeechKitProviderEvent]:
    cursor = (index + 1) * 1_000
    common = {
        "session_uuid": "provider-session-1",
        "final_index": index,
        "received_data_ms": cursor,
        "final_time_ms": cursor,
        "eou_time_ms": cursor,
    }
    final = SpeechKitProviderEvent(kind="final", transcript="", **common)
    eou_update = SpeechKitProviderEvent(kind="eou_update", **common)
    return [eou_update, final] if eou_update_first else [final, eou_update]


class FakePort:
    def __init__(
        self,
        turn_events: list[list[SpeechKitProviderEvent] | BaseException],
        *,
        closing_events: list[SpeechKitProviderEvent] | None = None,
    ) -> None:
        self.turn_events = list(turn_events)
        self.closing_events = closing_events or []
        self.responses: asyncio.Queue[SpeechKitProviderEvent | BaseException | None] = (
            asyncio.Queue()
        )
        self.open_count = 0
        self.session_options_count = 0
        self.audio: list[bytes] = []
        self.writes: list[tuple[str, bytes | None]] = []
        self.eou_count = 0
        self.done_writing_count = 0
        self.closed = False
        self.opened_credential = ""

    async def open(self, api_key: str) -> None:
        self.open_count += 1
        self.session_options_count += 1
        self.opened_credential = api_key

    async def send_audio(self, pcm16le: bytes) -> None:
        self.audio.append(pcm16le)
        self.writes.append(("audio", pcm16le))

    async def send_eou(self) -> None:
        self.eou_count += 1
        self.writes.append(("eou", None))
        if not self.turn_events:
            return
        events = self.turn_events.pop(0)
        if isinstance(events, BaseException):
            await self.responses.put(events)
            return
        for event in events:
            await self.responses.put(event)

    async def receive(self) -> SpeechKitProviderEvent | None:
        response = await self.responses.get()
        if isinstance(response, BaseException):
            raise response
        return response

    async def done_writing(self) -> None:
        self.done_writing_count += 1
        for event in self.closing_events:
            await self.responses.put(event)
        await self.responses.put(None)

    async def close(self) -> None:
        self.closed = True
        self.opened_credential = ""


def run_adapter(
    endpoint: FakeEndpoint,
    port: FakePort,
    stop: threading.Event,
    diagnostics: FakeDiagnostics,
    callback: Callable[[FinalizedUserUtterance], None],
) -> None:
    asyncio.run(
        SpeechKitV3RadioSttAdapter(
            "unit-secret",
            endpoint,
            stop,
            diagnostics,
            port_factory=lambda: port,
            on_finalized_utterance=callback,
        ).run()
    )


def test_proven_external_eou_session_options_are_exact() -> None:
    options = speechkit_session_options()
    model = options.recognition_model
    raw = model.audio_format.raw_audio

    assert model.model == SPEECHKIT_STT_MODEL
    assert raw.audio_encoding == raw.LINEAR16_PCM
    assert raw.sample_rate_hertz == 16_000 and raw.audio_channel_count == 1
    assert model.language_restriction.language_code == [SPEECHKIT_STT_LANGUAGE]
    assert model.audio_processing_type == model.REAL_TIME
    assert options.eou_classifier.WhichOneof("Classifier") == "external_classifier"


def test_one_physical_ptt_emits_exactly_one_native_final_after_eou_barrier() -> None:
    endpoint, diagnostics, stop = FakeEndpoint(), FakeDiagnostics(), threading.Event()
    port = FakePort([provider_turn(0, "добрый день")])
    utterances: list[FinalizedUserUtterance] = []
    endpoint.add_turn("ptt-1")

    def accepted(utterance: FinalizedUserUtterance) -> None:
        utterances.append(utterance)
        stop.set()

    run_adapter(endpoint, port, stop, diagnostics, accepted)

    assert [item.transcript for item in utterances] == ["добрый день"]
    assert utterances[0].transmission_id == "ptt-1"
    assert port.eou_count == 1
    assert port.open_count == port.session_options_count == 1
    assert endpoint.started and endpoint.stopped and port.closed


def test_opt_in_captures_exact_successfully_written_pcm_and_eou_accounting(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(
        provider="yandex",
        transport="srs",
        radio_stt_provider="speechkit_v3_external_eou",
        capture_speechkit_stt_input_audio=True,
    )
    monkeypatch.setattr(
        "orion.yandex_speechkit_stt.realtime_test_evidence",
        recorder,
    )
    monkeypatch.setattr(
        "orion.yandex_live_diagnostics.realtime_test_evidence",
        recorder,
    )
    endpoint, stop = FakeEndpoint(), threading.Event()
    diagnostics = YandexLiveDiagnostics("test-session", "unit-secret", tmp_path)
    blocks = (b"\x01\x00" * 320, b"\x02\x00" * 320)
    endpoint.items.put_nowait(RealtimeInputTransmissionStarted("srs-ptt-000001"))
    for block in blocks:
        endpoint.items.put_nowait(block)
    endpoint.items.put_nowait(
        RealtimeInputTransmissionCompleted(
            "srs-ptt-000001",
            boundary="srs_tx_state_end",
            first_accepted_packet_timestamp="2026-08-31T10:00:00.000+00:00",
            last_accepted_packet_timestamp="2026-08-31T10:00:01.000+00:00",
            accepted_packet_count=2,
            first_packet_id=10,
            last_packet_id=11,
            sequence_gap_count=0,
            decode_error_count=0,
            decoded_pcm_bytes=1_200,
            padding_bytes=80,
            framed_pcm_bytes=1_280,
            packet_quiescence_completed_timestamp=None,
            boundary_gap_ms=None,
            srs_tx_started_timestamp="2026-08-31T10:00:00.100+00:00",
            srs_tx_ended_timestamp="2026-08-31T10:00:01.200+00:00",
            srs_tx_sending_on=1,
            srs_tx_state_authoritative=True,
        )
    )
    port = FakePort([provider_turn(0, "добрый день")])

    def accepted(_utterance: FinalizedUserUtterance) -> None:
        stop.set()

    run_adapter(endpoint, port, stop, diagnostics, accepted)
    assert port.audio == list(blocks)
    assert port.writes == [("audio", blocks[0]), ("audio", blocks[1]), ("eou", None)]
    eou = next(
        event
        for event in diagnostics.snapshot()
        if event["event"] == "speechkit_stt_eou_sent"
    )
    assert eou["speechkit_pcm_bytes_before_eou"] == 1_280
    assert eou["decoded_pcm_bytes"] == 1_200
    assert eou["padding_bytes"] == 80
    assert eou["framed_pcm_bytes"] == 1_280
    assert eou["decoded_plus_padding_matches_framed"] is True
    assert eou["framed_matches_speechkit"] is True
    assert eou["artifact_included"] is True
    assert eou["boundary"] == "srs_tx_state_end"
    assert eou["eou_triggered_by_7082"] is True
    assert eou["srs_tx_sending_on"] == 1
    assert eou["eou_sent_timestamp"]
    assert eou["last_input_write_timestamp"]
    assert eou["eou_sent_monotonic_ns"] > eou["last_input_write_monotonic_ns"]

    output = recorder.stop_and_export()
    with zipfile.ZipFile(output) as archive:
        wav_bytes = archive.read(
            "speechkit-stt-input/srs-ptt-000001.wav"
        )
        evidence_events = [
            json.loads(line)
            for line in archive.read("events.jsonl").decode("utf-8").splitlines()
        ]
    evidence_eou = next(
        event
        for event in evidence_events
        if event["event"] == "speechkit_stt_eou_sent"
    )
    assert evidence_eou["accepted_packet_count"] == 2
    assert evidence_eou["speechkit_pcm_bytes_before_eou"] == 1_280
    assert evidence_eou["framed_matches_speechkit"] is True
    assert evidence_eou["eou_triggered_by_7082"] is True
    assert evidence_eou["srs_tx_state_authoritative"] is True
    assert evidence_eou["srs_tx_sending_on"] == 1
    assert "unit-secret" not in json.dumps(evidence_events)
    with wave.open(io.BytesIO(wav_bytes), "rb") as captured:
        assert (captured.getframerate(), captured.getnchannels(), captured.getsampwidth()) == (
            16_000,
            1,
            2,
        )
        assert captured.readframes(captured.getnframes()) == b"".join(blocks)


def test_three_sequential_ptts_share_one_rpc_and_remain_independent() -> None:
    endpoint, diagnostics, stop = FakeEndpoint(), FakeDiagnostics(), threading.Event()
    texts = ["фраза один", "курс сто тридцать семь", "так он недоступен"]
    port = FakePort([provider_turn(index, text) for index, text in enumerate(texts)])
    utterances: list[FinalizedUserUtterance] = []
    endpoint.add_turn("ptt-1")

    def accepted(utterance: FinalizedUserUtterance) -> None:
        utterances.append(utterance)
        if len(utterances) < 3:
            endpoint.add_turn(f"ptt-{len(utterances) + 1}")
        else:
            stop.set()

    run_adapter(endpoint, port, stop, diagnostics, accepted)

    assert [item.transcript for item in utterances] == texts
    assert [item.provider_final_index for item in utterances] == [0, 1, 2]
    assert {item.provider_session_id for item in utterances} == {"provider-session-1"}
    assert port.open_count == port.session_options_count == 1
    assert port.eou_count == 3


@pytest.mark.parametrize("eou_update_first", [False, True])
def test_empty_terminal_final_completes_barrier_in_either_provider_order(
    eou_update_first: bool,
) -> None:
    async def scenario() -> None:
        endpoint, diagnostics, stop = FakeEndpoint(), FakeDiagnostics(), threading.Event()
        port = FakePort(
            [empty_provider_turn(0, eou_update_first=eou_update_first)]
        )
        utterances: list[FinalizedUserUtterance] = []
        endpoint.add_turn("ptt-empty")
        adapter = SpeechKitV3RadioSttAdapter(
            "unit-secret",
            endpoint,
            stop,
            diagnostics,
            port_factory=lambda: port,
            on_finalized_utterance=utterances.append,
        )
        task = asyncio.create_task(adapter.run())
        deadline = asyncio.get_running_loop().time() + 1.0
        while not any(
            event == "speechkit_stt_barrier_completed"
            for event, _fields in diagnostics.events
        ):
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.001)

        assert adapter.state.value == "ready"
        assert adapter._last_final_index == 0
        assert utterances == []
        barrier = next(
            fields
            for event, fields in diagnostics.events
            if event == "speechkit_stt_barrier_completed"
        )
        assert barrier["barrier_completed"] is True
        assert barrier["final_text_empty"] is True
        assert barrier["utterance_emitted"] is False
        stop.set()
        await task

    asyncio.run(scenario())


def test_empty_terminal_turn_does_not_block_next_meaningful_ptt() -> None:
    async def scenario() -> None:
        endpoint, diagnostics, stop = FakeEndpoint(), FakeDiagnostics(), threading.Event()
        port = FakePort(
            [empty_provider_turn(0), provider_turn(1, "добрый день")]
        )
        utterances: list[FinalizedUserUtterance] = []
        endpoint.add_turn("ptt-empty")
        adapter = SpeechKitV3RadioSttAdapter(
            "unit-secret",
            endpoint,
            stop,
            diagnostics,
            port_factory=lambda: port,
            on_finalized_utterance=utterances.append,
        )
        task = asyncio.create_task(adapter.run())
        deadline = asyncio.get_running_loop().time() + 1.0
        while sum(
            event == "speechkit_stt_barrier_completed"
            for event, _fields in diagnostics.events
        ) < 1:
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.001)

        endpoint.add_turn("ptt-real")
        while not utterances:
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.001)
        stop.set()
        await task

        assert [(item.transmission_id, item.transcript) for item in utterances] == [
            ("ptt-real", "добрый день")
        ]
        assert utterances[0].provider_final_index == 1
        assert port.eou_count == 2
        barriers = [
            fields
            for event, fields in diagnostics.events
            if event == "speechkit_stt_barrier_completed"
        ]
        assert [item["final_text_empty"] for item in barriers] == [True, False]
        assert [item["utterance_emitted"] for item in barriers] == [False, True]

    asyncio.run(scenario())


def test_internal_silence_and_partial_do_not_finalize_before_physical_completion() -> None:
    async def scenario() -> None:
        endpoint, diagnostics, stop = FakeEndpoint(), FakeDiagnostics(), threading.Event()
        port = FakePort([provider_turn(0, "полная фраза")])
        utterances: list[FinalizedUserUtterance] = []
        endpoint.items.put_nowait(RealtimeInputTransmissionStarted("ptt-1"))
        endpoint.items.put_nowait(bytes(640))
        adapter = SpeechKitV3RadioSttAdapter(
            "unit-secret",
            endpoint,
            stop,
            diagnostics,
            port_factory=lambda: port,
            on_finalized_utterance=utterances.append,
        )
        task = asyncio.create_task(adapter.run())
        while not port.audio:
            await asyncio.sleep(0.001)
        await port.responses.put(
            SpeechKitProviderEvent(
                kind="partial",
                session_uuid="provider-session-1",
                transcript="пол",
            )
        )
        await asyncio.sleep(0.01)
        assert utterances == [] and port.eou_count == 0
        endpoint.items.put_nowait(RealtimeInputTransmissionCompleted("ptt-1"))
        while not utterances:
            await asyncio.sleep(0.001)
        stop.set()
        await task

    asyncio.run(scenario())


def test_empty_closing_final_is_diagnostic_only() -> None:
    endpoint, diagnostics, stop = FakeEndpoint(), FakeDiagnostics(), threading.Event()
    stop.set()
    closing = [
        SpeechKitProviderEvent(
            kind="final",
            session_uuid="provider-session-1",
            transcript="",
            final_index=3,
        ),
        SpeechKitProviderEvent(
            kind="eou_update",
            session_uuid="provider-session-1",
            final_index=3,
        ),
    ]
    port = FakePort([], closing_events=closing)
    utterances: list[FinalizedUserUtterance] = []

    run_adapter(endpoint, port, stop, diagnostics, utterances.append)

    assert utterances == []
    assert "speechkit_stt_empty_final_ignored" in [event for event, _ in diagnostics.events]
    assert port.done_writing_count == 1


def test_raw_provider_text_is_not_corrected() -> None:
    endpoint, diagnostics, stop = FakeEndpoint(), FakeDiagnostics(), threading.Event()
    port = FakePort([provider_turn(0, "так он недоступен")])
    utterances: list[FinalizedUserUtterance] = []
    endpoint.add_turn("ptt-1")

    def accepted(utterance: FinalizedUserUtterance) -> None:
        utterances.append(utterance)
        stop.set()

    run_adapter(endpoint, port, stop, diagnostics, accepted)
    assert utterances[0].transcript == "так он недоступен"


def test_next_ptt_before_previous_barrier_fails_closed_without_contamination() -> None:
    endpoint, diagnostics, stop = FakeEndpoint(), FakeDiagnostics(), threading.Event()
    port = FakePort([[]])
    endpoint.add_turn("ptt-1")
    endpoint.add_turn("ptt-2")
    utterances: list[FinalizedUserUtterance] = []

    with pytest.raises(SpeechKitSttProtocolError, match="provider barrier is pending"):
        run_adapter(endpoint, port, stop, diagnostics, utterances.append)

    assert utterances == [] and port.eou_count == 1


def test_provider_error_before_final_fails_closed() -> None:
    endpoint, diagnostics, stop = FakeEndpoint(), FakeDiagnostics(), threading.Event()
    port = FakePort([ConnectionError("provider failed")])
    endpoint.add_turn("ptt-1")
    utterances: list[FinalizedUserUtterance] = []

    with pytest.raises(ConnectionError, match="provider failed"):
        run_adapter(endpoint, port, stop, diagnostics, utterances.append)

    assert utterances == []
    assert diagnostics.events[-1][0] == "speechkit_stt_provider_error"


def test_endpoint_fail_closed_stop_is_reported_as_provider_error() -> None:
    endpoint, diagnostics, stop = FakeEndpoint(), FakeDiagnostics(), threading.Event()
    endpoint.error = RuntimeError("authoritative SRS TX-state became stale")
    stop.set()
    port = FakePort([])

    with pytest.raises(RuntimeError, match="TX-state became stale"):
        run_adapter(endpoint, port, stop, diagnostics, lambda _item: None)

    assert diagnostics.events[-1][0] == "speechkit_stt_provider_error"


def test_operator_stop_while_pending_prevents_late_ghost_dispatch() -> None:
    async def scenario() -> None:
        endpoint, diagnostics, stop = FakeEndpoint(), FakeDiagnostics(), threading.Event()
        late = provider_turn(0, "поздняя фраза")
        port = FakePort([[]], closing_events=late)
        utterances: list[FinalizedUserUtterance] = []
        endpoint.add_turn("ptt-1")
        adapter = SpeechKitV3RadioSttAdapter(
            "unit-secret",
            endpoint,
            stop,
            diagnostics,
            port_factory=lambda: port,
            on_finalized_utterance=utterances.append,
        )
        task = asyncio.create_task(adapter.run())
        while port.eou_count == 0:
            await asyncio.sleep(0.001)
        stop.set()
        await task
        assert utterances == []

    asyncio.run(scenario())


def test_secret_is_used_only_to_open_port_and_never_enters_diagnostics() -> None:
    endpoint, diagnostics, stop = FakeEndpoint(), FakeDiagnostics(), threading.Event()
    stop.set()
    port = FakePort([])
    run_adapter(endpoint, port, stop, diagnostics, cast(Callable, lambda _item: None))

    rendered = repr(diagnostics.events)
    assert "unit-secret" not in rendered
    assert port.opened_credential == ""


def test_test_evidence_correlates_physical_ptt_provider_barrier_and_raw_final(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.start(provider="yandex", transport="srs")
    monkeypatch.setattr(
        "orion.yandex_speechkit_stt.realtime_test_evidence",
        recorder,
    )
    monkeypatch.setattr(
        "orion.yandex_live_diagnostics.realtime_test_evidence",
        recorder,
    )
    endpoint, stop = FakeEndpoint(), threading.Event()
    diagnostics = YandexLiveDiagnostics("test-session", "unit-secret", tmp_path)
    port = FakePort([provider_turn(0, "так он недоступен")])
    endpoint.add_turn("ptt-evidence")

    def accepted(_utterance: FinalizedUserUtterance) -> None:
        stop.set()

    run_adapter(endpoint, port, stop, diagnostics, accepted)
    archive_path = recorder.stop_and_export()
    with zipfile.ZipFile(archive_path) as archive:
        raw = archive.read("events.jsonl").decode("utf-8")
    events = [json.loads(line) for line in raw.splitlines()]

    assert "unit-secret" not in raw
    assert {event["event"] for event in events} >= {
        "speechkit_stt_ptt_started",
        "speechkit_stt_eou_sent",
        "speechkit_stt_final",
        "speechkit_stt_eou_update",
        "speechkit_stt_utterance_finalized",
        "user_transcript",
    }
    final = next(event for event in events if event["event"] == "speechkit_stt_final")
    assert final["physical_transmission_id"] == "ptt-evidence"
    assert final["final_index"] == 0
    assert final["received_data_ms"] == final["final_time_ms"] == 1_000
    transcript = next(event for event in events if event["event"] == "user_transcript")
    assert transcript["transcript"] == "так он недоступен"
