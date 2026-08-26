from __future__ import annotations

import asyncio
import hashlib
import threading
import time
import zipfile
from urllib.parse import parse_qs

import pytest

import orion.yandex_hybrid_probe as hybrid_module
from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
from orion.yandex_hybrid_probe import (
    AcousticReview,
    HybridProbeRunner,
    HybridRuntimeContext,
    RealtimePresentationClient,
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
        "voice": ["julia"],
        "emotion": ["strict"],
        "speed": ["1.0"],
        "format": ["lpcm"],
        "sampleRateHertz": ["48000"],
    }
    assert b"folder" not in body.lower()
    assert b"top-secret" not in body


def test_all_hybrid_cases_are_one_concept_and_semantically_corruption_sensitive() -> None:
    cases = hybrid_probe_cases()
    assert len(cases) == 10
    assert len({case.case_id for case in cases}) == len(cases)
    assert [case.voice for case in cases[:3]] == ["dasha", "alexander", "dasha"]
    assert [(case.voice, case.role) for case in cases[3:6]] == [
        ("julia", "neutral"),
        ("julia", "strict"),
        ("julia", "neutral"),
    ]
    for case in cases:
        assert evaluate_semantics(case, case.finalized_text)["status"] == "PASS"
        assert evaluate_semantics(case, "Факт намеренно поврежден.")["status"] == "FAIL"


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
        self.isolation: dict[str, object] = {}

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
    async def synthesize(self, case: SemanticCase, _api_key: str) -> tuple[bytes, str]:
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
