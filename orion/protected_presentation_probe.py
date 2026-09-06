"""Explicit Stage 7C synthetic runner; no Realtime session or normal voice workflow."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import tempfile
import threading
from uuid import UUID, uuid4, uuid5
import wave

from orion.communication_contracts import (
    FinalizedCommunicationText,
    OperationalSemanticUnit,
    ProtectedValue,
    ResponseCompositionPlan,
)
from orion.phraseology_probe import synthetic_probe_cases
from orion.phraseology_renderer import PhraseologyRenderer, synthetic_pilot_ruleset
from orion.protected_presentation import ProtectedPresentationService, tx_correlation
from orion.radio_contracts import RadioContext, RadioEntityRef, RadioModulation
from orion.response_composer import ResponseComposer
from orion.speechkit_tts_adapter import (
    SpeechKitAttemptObserver,
    SpeechKitTtsAdapter,
    TtsAdapterError,
    normalize_speechkit_pcm,
)


EXPECTED = (
    "Fly heading zero three seven deg.",
    "Frequency 264.500 MHz.",
    "TACAN 44X.",
    "Laser code zero one five seven.",
    "Altitude correction -850 ft.",
    "Heading unavailable.",
)


@dataclass(frozen=True, slots=True)
class ProtectedProbeCase:
    case_id: str
    finalized: FinalizedCommunicationText


def protected_probe_cases(run_id: UUID) -> tuple[ProtectedProbeCase, ...]:
    renderer = PhraseologyRenderer(synthetic_pilot_ruleset())
    source = synthetic_probe_cases()
    result = []
    for index, expected in zip((0, 3, 4, 5, 8, 9), EXPECTED, strict=True):
        case = source[index]
        unit = case.unit
        if index == 0:
            value = ProtectedValue.model_validate(
                {**unit.protected_values[0].model_dump(), "value": 37}
            )
            unit = OperationalSemanticUnit.model_validate(
                {**unit.model_dump(), "protected_values": (value,)}
            )
        fragment = renderer.render(unit, case.context)
        finalized = ResponseComposer().compose(
            ResponseCompositionPlan(
                interaction_id=uuid5(run_id, case.case_id),
                communication=case.context,
                priority=unit.priority,
                protected_fragments=(fragment,),
            )
        )
        if fragment.text != expected or finalized.text != expected:
            raise ValueError("Synthetic Core wording gate failed")
        result.append(ProtectedProbeCase(case.case_id, finalized))
    return tuple(result)


def write_wav(path: Path, pcm: bytes, rate: int) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(pcm)


class _EvidenceTts:
    """Explicit synthetic evidence only, never a normal-logging text sink."""

    def __init__(
        self, adapter: SpeechKitTtsAdapter, output: Path, capture: bool
    ) -> None:
        self.adapter, self.output, self.capture = adapter, output, capture
        self.results: dict[str, dict[str, object]] = {}

    async def synthesize(
        self,
        text: str,
        language: str,
        tx_id: str,
        observer: SpeechKitAttemptObserver | None = None,
    ) -> bytes:
        pcm = await self.adapter.synthesize(text, language, tx_id, observer)
        self.results[tx_id] = {
            "request_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "language": language,
            "voice": "john",
            "pcm48_bytes": len(pcm),
        }
        if self.capture:
            write_wav(self.output / f"{tx_id}.wav", normalize_speechkit_pcm(pcm), 44100)
        return pcm

    async def aclose(self) -> None:
        await self.adapter.aclose()


async def run_cases(
    service: ProtectedPresentationService,
    cases: tuple[ProtectedProbeCase, ...],
    entity: RadioEntityRef,
    frequency_hz: float,
) -> list[dict[str, object]]:
    results = []
    for case in cases:
        final = case.finalized
        tx = tx_correlation(final.interaction_id)
        context = RadioContext(
            tx_correlation_id=tx,
            source_domain=final.context.domain,
            radio_entity=entity,
            target_frequency_hz=frequency_hz,
            modulation=RadioModulation.AM,
            communication_priority=final.priority,
            interaction_id=final.interaction_id,
        )
        result = await service.present(final, context)
        results.append(
            {
                "case_id": case.case_id,
                "expected_text": final.text,
                "renderer_composer_exact": True,
                **asdict(result),
            }
        )
        if not result.terminal or result.state != "completed":
            break
        await asyncio.sleep(0.25)
    return results


async def _direct(output: Path, key: str) -> dict[str, object]:
    adapter = SpeechKitTtsAdapter(key)
    rows = []
    try:
        for index, text in enumerate(
            ("Fly heading zero three seven.", "Laser code zero one five seven."), 1
        ):
            pcm = await adapter.synthesize(text, "en-US", f"p7c-direct-{index}")
            path = output / f"direct-{index}.wav"
            write_wav(path, pcm, 48000)
            rows.append(
                {
                    "text": text,
                    "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "language": "en-US",
                    "voice": "john",
                    "http_status": 200,
                    "format": "pcm_s16le",
                    "rate": 48000,
                    "channels": 1,
                    "pcm_bytes": len(pcm),
                    "wav": str(path),
                }
            )
        return {
            "stage": "7C-direct",
            "machine_pass": True,
            "cases": rows,
            "human_review": "REQUIRED",
        }
    finally:
        await adapter.aclose()


async def _field(
    args: argparse.Namespace, output: Path, key: str, password: str
) -> dict[str, object]:
    # Existing transport hosting only. Never instantiate YandexRealtimeSession.
    from orion.srs_diagnostics import SrsTransportDiagnostics
    from orion.srs_protocol import AM
    from orion.srs_radio_transport import SrsRadioConfig
    from orion.yandex_srs_live_core import SrsYandexPcmEndpoint

    class SafeDiagnostics(SrsTransportDiagnostics):
        def record(self, event: str, **fields: object) -> None:
            if event not in {
                "srs_tx_started",
                "tx_completed",
                "srs_adapter_tx_started",
                "srs_adapter_tx_completed",
                "srs_adapter_tx_failed",
                "endpoint_error",
            }:
                return
            safe: dict[str, object] = {"event": event}
            for name, value in fields.items():
                if (
                    name in {"response_id", "tx_correlation_id"}
                    and isinstance(value, str)
                    and re.fullmatch(r"p7c-[0-9a-f]{32}", value)
                ):
                    safe[name] = value
                elif name in {"frames", "duration_ms", "sent_frames"} and isinstance(
                    value, (int, float)
                ):
                    safe[name] = value
            with self._lock:
                self._events.append(safe)

    run_id = uuid4()
    cases = protected_probe_cases(run_id)
    diagnostics = SafeDiagnostics(run_id.hex, runtime_dir=output)
    stopped = threading.Event()
    endpoint = SrsYandexPcmEndpoint(
        SrsRadioConfig(
            host=args.host,
            port=args.port,
            bot_name=args.callsign,
            eam_password=password,
            frequency_hz=args.frequency_hz,
            modulation=AM,
        ),
        stopped,
        diagnostics,
        lambda **_fields: None,
    )
    service = None
    drain_task = None
    report: dict[str, object] = {
        "stage": "7C",
        "run_id": run_id.hex,
        "human_review": "REQUIRED",
    }

    async def drain_rx() -> None:
        while not stopped.is_set():
            await asyncio.to_thread(
                endpoint.read_input, 0.1
            )  # discard, never record/send to provider

    try:
        await asyncio.to_thread(endpoint.connect_radio)
        endpoint.start()
        drain_task = asyncio.create_task(drain_rx())
        router = endpoint.radio_router
        if router is None:
            raise ValueError("Radio runtime unavailable")
        runtime = endpoint.srs_adapter_runtime()
        entity = RadioEntityRef(
            entity_id="orion.stage7c.synthetic",
            operational_callsign=runtime.bot_name,
            coalition={1: "red", 2: "blue"}.get(runtime.coalition),
        )
        tts = _EvidenceTts(
            SpeechKitTtsAdapter(key), output, args.capture_synthetic_audio
        )
        service = ProtectedPresentationService(tts, router, transport_id="srs")
        rows = await run_cases(service, cases, entity, runtime.frequency_hz)
        radio_events = [
            event.model_dump(mode="json") for event in router.diagnostic_snapshot()
        ]
        report.update(
            cases=rows,
            tts=tts.results,
            presentation_events=service.diagnostics(),
            radio_events=radio_events,
            transport_events=diagnostics.snapshot(),
        )
        report["machine_pass"] = field_machine_gate(report)
    finally:
        if service is not None:
            report["presentation_shutdown_clean"] = await service.shutdown()
            if not report["presentation_shutdown_clean"]:
                report["machine_pass"] = False
        await asyncio.to_thread(endpoint.stop)
        if drain_task is not None:
            await drain_task
    return report


def field_machine_gate(report: dict[str, object]) -> bool:
    """Require every correlated boundary; transport completion is not acoustic PASS."""
    rows = report.get("cases")
    tts = report.get("tts")
    radio = report.get("radio_events")
    transport = report.get("transport_events")
    presentation = report.get("presentation_events")
    if not isinstance(rows, list) or len(rows) != 6 or not isinstance(tts, dict):
        return False
    if (
        not isinstance(radio, list)
        or not isinstance(transport, (list, tuple))
        or not isinstance(presentation, (list, tuple))
    ):
        return False
    if any(not isinstance(e, dict) for e in [*rows, *radio, *transport, *presentation]):
        return False
    if any(
        e.get("event") in {"endpoint_error", "srs_adapter_tx_failed"} for e in transport
    ):
        return False
    ids = [row.get("tx_id") for row in rows]
    if any(
        not isinstance(tx, str) or not re.fullmatch(r"p7c-[0-9a-f]{32}", tx)
        for tx in ids
    ):
        return False
    if len(set(ids)) != 6 or set(tts) != set(ids):
        return False
    if [(e.get("tx_correlation_id"), e.get("stage")) for e in radio] != [
        (tx, stage) for tx in ids for stage in ("enqueued", "started", "completed")
    ]:
        return False
    boundaries = [
        (e.get("tx_id"), e.get("event"))
        for e in presentation
        if e.get("event") in {"presentation_started", "presentation_completed"}
    ]
    if boundaries != [
        (tx, stage)
        for tx in ids
        for stage in ("presentation_started", "presentation_completed")
    ]:
        return False
    for row, expected in zip(rows, EXPECTED, strict=True):
        if (
            row.get("state") != "completed"
            or not row.get("terminal")
            or row.get("expected_text") != expected
            or row.get("renderer_composer_exact") is not True
            or row.get("failure") is not None
        ):
            return False
        tx = row["tx_id"]
        evidence = tts.get(tx, {})
        if not isinstance(evidence, dict):
            return False
        if (
            evidence.get("request_text_sha256")
            != hashlib.sha256(expected.encode()).hexdigest()
            or evidence.get("language") != "en-US"
            or evidence.get("voice") != "john"
            or not isinstance(evidence.get("pcm48_bytes"), int)
        ):
            return False
        pcm_size = evidence["pcm48_bytes"]
        if not 0 < pcm_size <= 2880000 or pcm_size % 2:
            return False
        stages = [e.get("stage") for e in radio if e.get("tx_correlation_id") == tx]
        if stages != ["enqueued", "started", "completed"]:
            return False
        transport_order = [
            e.get("event")
            for e in transport
            if e.get("tx_correlation_id") == tx or e.get("response_id") == tx
        ]
        if transport_order != [
            "srs_adapter_tx_started",
            "srs_tx_started",
            "tx_completed",
            "srs_adapter_tx_completed",
        ]:
            return False
        for event in (
            "srs_tx_started",
            "tx_completed",
            "srs_adapter_tx_started",
            "srs_adapter_tx_completed",
        ):
            if (
                sum(
                    e.get("event") == event
                    and (e.get("tx_correlation_id") == tx or e.get("response_id") == tx)
                    for e in transport
                )
                != 1
            ):
                return False
        events = [e.get("event") for e in presentation if e.get("tx_id") == tx]
        for name in (
            "tts_completed",
            "radio_submit_started",
            "radio_submit_completed",
            "presentation_completed",
        ):
            if events.count(name) != 1:
                return False
        if events.count("speechkit_attempt_succeeded") != 1:
            return False
        if not all(isinstance(name, str) for name in events):
            return False
        ordered = [
            events.index(name)
            for name in (
                "tts_completed",
                "radio_submit_started",
                "radio_submit_completed",
                "presentation_completed",
            )
        ]
        if ordered != sorted(ordered):
            return False
        submit_index = events.index("radio_submit_started")
        if any(name.startswith("speechkit_") for name in events[submit_index:]):
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list-cases", action="store_true")
    mode.add_argument("--direct-tts", action="store_true")
    mode.add_argument("--field", action="store_true")
    parser.add_argument("--confirm-transmit-six", action="store_true")
    parser.add_argument("--capture-synthetic-audio", action="store_true")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int, default=5002)
    parser.add_argument("--frequency-hz", type=float)
    parser.add_argument("--callsign")
    args = parser.parse_args()
    if args.list_cases:
        for case in protected_probe_cases(UUID(int=7)):
            print(f"{case.case_id}: {case.finalized.text}")
        return 0
    if args.field and not (
        args.confirm_transmit_six and args.host and args.frequency_hz and args.callsign
    ):
        parser.error(
            "Field requires explicit confirmation, host, frequency-hz and callsign"
        )
    from orion.windows_credentials import (
        VoiceCredential,
        default_voice_credential_store,
    )

    output = Path(tempfile.mkdtemp(prefix="orion-stage7c-"))
    try:
        store = default_voice_credential_store()
        key = store.load(VoiceCredential.YANDEX_API_KEY)
        if not key:
            raise ValueError("Credential unavailable")
        report = asyncio.run(
            _field(args, output, key, store.load(VoiceCredential.SRS_EAM_PASSWORD))
            if args.field
            else _direct(output, key)
        )
    except TtsAdapterError as exc:
        report = {
            "stage": "7C",
            "machine_pass": False,
            "failure": exc.code.value,
            "human_review": "REQUIRED",
        }
    except Exception:
        report = {
            "stage": "7C",
            "machine_pass": False,
            "failure": "probe_failed",
            "human_review": "REQUIRED",
        }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "machine_pass": report.get("machine_pass", False),
                "evidence": str(output),
                "human_review": "REQUIRED",
            }
        )
    )
    return 0 if report.get("machine_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
