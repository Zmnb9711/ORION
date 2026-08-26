"""Bounded IA-1 SemanticResponse presentation probe for Yandex Realtime.

Provider JSON is intentionally built here, at the Yandex boundary.  IA-0
contracts remain provider- and transport-neutral.
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from orion.interaction_contracts import (
    CapabilityId,
    PresentationMode,
    SemanticFact,
    SemanticFactKind,
    SemanticInputIssue,
    SemanticInputStatus,
    SemanticResponse,
)
from orion.realtime_test_evidence import realtime_test_evidence


BASELINE_VOICE = "dasha"
BASELINE_ROLE = "neutral"
VOICE_B = "alexander"
STYLE_VOICE = "julia"
URGENT_ROLE = "strict"
FACT_ORIGIN = "synthetic_probe"
PROBE_TIMEOUT_S = 20.0

_NATURALIZE_INSTRUCTIONS = (
    "Present the supplied ORION semantic result briefly as natural spoken aviation "
    "language. Treat it as already decided: do not calculate, infer, add, omit, or "
    "change facts, identifiers, units, unavailable status, or recommendation direction. "
    "Return only the spoken presentation."
)
_VERBATIM_INSTRUCTIONS = (
    "Render only the exact ORION verbatim_text supplied by the client. Do not answer, "
    "explain, translate, reason, paraphrase, add, omit, or change any character-level "
    "content. Return only that sentence as speech."
)


class ProbeSelection(StrEnum):
    NATURALIZE = "naturalize"
    VERBATIM = "verbatim"
    VOICE = "voice"
    STYLE = "style"
    FULL = "full"


class ProbeState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class YandexPresentationStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    compatible_session: bool = False
    state: ProbeState = ProbeState.IDLE
    message: str = "Presentation probe is idle"
    probe_run_id: str | None = None
    probe_case_id: str | None = None
    yandex_session_id: str | None = None
    selection: ProbeSelection | None = None


@dataclass(frozen=True, slots=True)
class PresentationCase:
    case_id: str
    semantic_response: SemanticResponse
    requested_voice: str | None = None
    requested_role: str | None = None
    speech_style_id: str | None = None


@dataclass(frozen=True, slots=True)
class PresentationRun:
    probe_run_id: str
    selection: ProbeSelection
    cases: tuple[PresentationCase, ...]


@dataclass(slots=True)
class _ActiveCase:
    case: PresentationCase
    response_created: asyncio.Future[str]
    response_done: asyncio.Future[tuple[str, str]]
    item_event_id: str
    response_event_id: str
    response_id: str | None = None
    interrupted: bool = False


def _fact(
    key: str,
    value: str | int | float | bool,
    *,
    unit: str | None = None,
    derived: bool = False,
) -> SemanticFact:
    return SemanticFact(
        key=key,
        value=value,
        unit=unit,
        kind=SemanticFactKind.DERIVED if derived else SemanticFactKind.AUTHORITATIVE,
    )


def _semantic_response(
    case_id: str,
    *,
    facts: tuple[SemanticFact, ...] = (),
    derived: tuple[SemanticFact, ...] = (),
    recommendation: str | None = None,
    unavailable: tuple[SemanticInputIssue, ...] = (),
    verbatim: str | None = None,
) -> SemanticResponse:
    interaction_id = UUID(bytes=case_id.encode("ascii")[:16].ljust(16, b"_"))
    if verbatim is not None:
        return SemanticResponse(
            interaction_id=interaction_id,
            capability=CapabilityId("probe.presentation"),
            presentation_mode=PresentationMode.VERBATIM,
            verbatim_text=verbatim,
        )
    return SemanticResponse(
        interaction_id=interaction_id,
        capability=CapabilityId("probe.presentation"),
        authoritative_facts=facts,
        derived_results=derived,
        recommendation=recommendation,
        unavailable_inputs=unavailable,
    )


def synthetic_probe_cases() -> tuple[PresentationCase, ...]:
    """Return deterministic corruption-sensitive IA-1 cases."""

    return (
        PresentationCase(
            "case-a-heading-speed",
            _semantic_response(
                "case-a-heading-speed",
                facts=(
                    _fact("flight.heading", 256, unit="degrees"),
                    _fact("flight.true_airspeed", 241, unit="knots"),
                ),
            ),
        ),
        PresentationCase(
            "case-b-callsign",
            _semantic_response(
                "case-b-callsign",
                facts=(_fact("radio.callsign", "Colt 1-1"),),
            ),
        ),
        PresentationCase(
            "case-c-radio",
            _semantic_response(
                "case-c-radio",
                facts=(
                    _fact("radio.frequency", "251.000", unit="MHz"),
                    _fact("radio.modulation", "AM"),
                ),
            ),
        ),
        PresentationCase(
            "case-d-tacan",
            _semantic_response(
                "case-d-tacan",
                facts=(_fact("navigation.tacan", "31Y"),),
            ),
        ),
        PresentationCase(
            "case-e-laser",
            _semantic_response(
                "case-e-laser",
                facts=(_fact("target.laser_code", 1688),),
            ),
        ),
        PresentationCase(
            "case-f-recommendation",
            _semantic_response(
                "case-f-recommendation",
                facts=(
                    _fact("tanker.callsign", "Texaco 1-1"),
                    _fact("tanker.distance", 47, unit="NM"),
                    _fact("divert.distance", 72, unit="NM"),
                ),
                recommendation="Proceed to Texaco 1-1.",
            ),
        ),
        PresentationCase(
            "case-g-unavailable",
            _semantic_response(
                "case-g-unavailable",
                unavailable=(
                    SemanticInputIssue(
                        key="navigation.tacan",
                        status=SemanticInputStatus.UNAVAILABLE,
                        reason="synthetic_probe_unavailable",
                    ),
                ),
            ),
        ),
        PresentationCase(
            "case-h-verbatim",
            _semantic_response(
                "case-h-verbatim",
                verbatim=(
                    "Colt 1-1, heading 256, true airspeed 241 knots, "
                    "laser code 1688."
                ),
            ),
        ),
    )


def voice_probe_cases() -> tuple[PresentationCase, ...]:
    return (
        PresentationCase(
            "voice-a-first",
            _semantic_response("voice-a-first", verbatim="Voice A, first response."),
            requested_voice=BASELINE_VOICE,
            requested_role=BASELINE_ROLE,
        ),
        PresentationCase(
            "voice-b",
            _semantic_response("voice-b", verbatim="Voice B, second response."),
            requested_voice=VOICE_B,
            requested_role=BASELINE_ROLE,
        ),
        PresentationCase(
            "voice-a-restored",
            _semantic_response("voice-a-restored", verbatim="Voice A, restored response."),
            requested_voice=BASELINE_VOICE,
            requested_role=BASELINE_ROLE,
        ),
    )


def style_probe_cases() -> tuple[PresentationCase, ...]:
    return (
        PresentationCase(
            "style-normal-first",
            _semantic_response(
                "style-normal-first", verbatim="Colt 1-1, continue approach."
            ),
            requested_voice=STYLE_VOICE,
            requested_role=BASELINE_ROLE,
            speech_style_id="normal",
        ),
        PresentationCase(
            "style-urgent",
            _semantic_response("style-urgent", verbatim="Colt 1-1, go around."),
            requested_voice=STYLE_VOICE,
            requested_role=URGENT_ROLE,
            speech_style_id="urgent",
        ),
        PresentationCase(
            "style-normal-restored",
            _semantic_response(
                "style-normal-restored", verbatim="Colt 1-1, contact tower."
            ),
            requested_voice=STYLE_VOICE,
            requested_role=BASELINE_ROLE,
            speech_style_id="normal",
        ),
    )


def cases_for(selection: ProbeSelection) -> tuple[PresentationCase, ...]:
    semantic = synthetic_probe_cases()
    if selection is ProbeSelection.NATURALIZE:
        return semantic[:7]
    if selection is ProbeSelection.VERBATIM:
        return semantic[7:]
    if selection is ProbeSelection.VOICE:
        return voice_probe_cases()
    if selection is ProbeSelection.STYLE:
        return style_probe_cases()
    return (*semantic, *voice_probe_cases(), *style_probe_cases())


def semantic_presentation_text(response: SemanticResponse) -> str:
    """Serialize only bounded SemanticResponse semantics, never ambient context."""

    lines = [
        "ORION_PRESENTATION_REQUEST_V1",
        f"mode={response.presentation_mode.value}",
        f"interaction_id={response.interaction_id}",
        f"response_id={response.response_id}",
        f"fact_origin={FACT_ORIGIN}",
    ]
    if response.capability is not None:
        lines.append(f"capability={response.capability}")
    for fact in response.authoritative_facts:
        unit = f" {fact.unit}" if fact.unit else ""
        lines.append(f"authoritative:{fact.key}={fact.value}{unit}")
    for fact in response.derived_results:
        unit = f" {fact.unit}" if fact.unit else ""
        lines.append(f"derived:{fact.key}={fact.value}{unit}")
    if response.recommendation:
        lines.append(f"recommendation={response.recommendation}")
    for issue in response.unavailable_inputs:
        lines.append(f"input:{issue.key}={issue.status.value}")
    if response.verbatim_text:
        lines.append(f"verbatim_text={response.verbatim_text}")
    return "\n".join(lines)


def presentation_events(
    case: PresentationCase,
    *,
    item_event_id: str,
    response_event_id: str,
) -> tuple[dict[str, object], dict[str, object]]:
    """Build provider events without mutating the IA-0 object."""

    instructions = (
        _VERBATIM_INSTRUCTIONS
        if case.semantic_response.presentation_mode is PresentationMode.VERBATIM
        else _NATURALIZE_INSTRUCTIONS
    )
    item = {
        "type": "conversation.item.create",
        "event_id": item_event_id,
        "item": {
            "type": "message",
            "object": "realtime.item",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": semantic_presentation_text(case.semantic_response),
                }
            ],
        },
    }
    create = {
        "type": "response.create",
        "event_id": response_event_id,
        "response": {
            "instructions": instructions,
            "output_modalities": ["audio"],
        },
    }
    return item, create


def normalized_verbatim(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s.-]", " ", value.casefold())).strip()


def verbatim_fidelity(expected: str, observed: str) -> tuple[bool, bool]:
    return expected == observed, normalized_verbatim(expected) == normalized_verbatim(observed)


def naturalize_fidelity(response: SemanticResponse, observed: str) -> dict[str, bool | str]:
    """Conservative token check; ambiguity is REVIEW_REQUIRED, never manufactured PASS."""

    normalized = observed.casefold()
    value_checks: list[bool] = []
    for fact in response.authoritative_facts:
        value_checks.append(str(fact.value).casefold() in normalized)
    for issue in response.unavailable_inputs:
        unavailable_words = ("unavailable", "unknown", "недоступ", "неизвест")
        if not any(word in normalized for word in unavailable_words):
            invented_channel = re.search(r"\b\d{1,3}\s*[xy]\b", normalized)
            if invented_channel:
                return {"status": "FAIL", "tokens_preserved": False}
    if response.recommendation:
        significant = [
            token.casefold()
            for token in re.findall(r"[A-Za-zА-Яа-я0-9-]+", response.recommendation)
            if len(token) > 2 or any(character.isdigit() for character in token)
        ]
        identifier_tokens = [token for token in significant if any(char.isdigit() for char in token)]
        value_checks.extend(token in normalized for token in identifier_tokens)
    if value_checks and all(value_checks):
        return {"status": "REVIEW_REQUIRED", "tokens_preserved": True}
    if not value_checks and response.unavailable_inputs:
        return {"status": "REVIEW_REQUIRED", "tokens_preserved": True}
    return {"status": "FAIL", "tokens_preserved": False}


class YandexPresentationAdapter:
    """Thread-safe registry for the one existing active Yandex session."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._submit: Callable[[PresentationRun], None] | None = None
        self._status = YandexPresentationStatus()

    def attach(
        self,
        *,
        yandex_session_id: str,
        submit: Callable[[PresentationRun], None],
    ) -> None:
        with self._lock:
            self._submit = submit
            self._status = YandexPresentationStatus(
                compatible_session=True,
                yandex_session_id=yandex_session_id,
                message="Compatible active Yandex Realtime session is ready",
            )

    def detach(self, yandex_session_id: str) -> None:
        with self._lock:
            if self._status.yandex_session_id != yandex_session_id:
                return
            self._submit = None
            if self._status.state is ProbeState.RUNNING:
                self._status = self._status.model_copy(
                    update={
                        "compatible_session": False,
                        "state": ProbeState.FAILED,
                        "message": "Yandex session closed during presentation probe",
                    }
                )
            else:
                self._status = YandexPresentationStatus(
                    state=self._status.state,
                    message=self._status.message,
                    probe_run_id=self._status.probe_run_id,
                    selection=self._status.selection,
                )

    def start(self, selection: ProbeSelection) -> YandexPresentationStatus:
        with self._lock:
            if self._submit is None or not self._status.compatible_session:
                raise ValueError("Presentation probe requires a compatible active Yandex session")
            if self._status.state is ProbeState.RUNNING:
                raise ValueError("A presentation probe is already running")
            run = PresentationRun(uuid4().hex, selection, cases_for(selection))
            self._status = self._status.model_copy(
                update={
                    "state": ProbeState.RUNNING,
                    "message": "Presentation probe is running",
                    "probe_run_id": run.probe_run_id,
                    "probe_case_id": None,
                    "selection": selection,
                }
            )
            submit = self._submit
        try:
            submit(run)
        except Exception:
            self.failed(run.probe_run_id, "Presentation probe submission failed")
            raise
        return self.status()

    def case_started(self, probe_run_id: str, case_id: str) -> None:
        with self._lock:
            if self._status.probe_run_id == probe_run_id:
                self._status = self._status.model_copy(update={"probe_case_id": case_id})

    def complete(self, probe_run_id: str) -> None:
        with self._lock:
            if self._status.probe_run_id == probe_run_id:
                self._status = self._status.model_copy(
                    update={
                        "state": ProbeState.COMPLETE,
                        "message": "Presentation probe completed; review Test Evidence",
                        "probe_case_id": None,
                    }
                )

    def failed(self, probe_run_id: str, message: str) -> None:
        with self._lock:
            if self._status.probe_run_id == probe_run_id:
                self._status = self._status.model_copy(
                    update={
                        "state": ProbeState.FAILED,
                        "message": message[:200],
                        "probe_case_id": None,
                    }
                )

    def status(self) -> YandexPresentationStatus:
        with self._lock:
            return self._status.model_copy(deep=True)


class YandexPresentationSessionDriver:
    """Async executor attached to one existing Yandex WebSocket."""

    def __init__(
        self,
        adapter: YandexPresentationAdapter,
        *,
        yandex_session_id: str,
        diagnostics: Any,
        interaction_idle: Callable[[], bool],
    ) -> None:
        self._adapter = adapter
        self._session_id = yandex_session_id
        self._diagnostics = diagnostics
        self._interaction_idle = interaction_idle
        self._queue: asyncio.Queue[PresentationRun] = asyncio.Queue(maxsize=1)
        self._loop = asyncio.get_running_loop()
        self._active: _ActiveCase | None = None
        self._session_update: asyncio.Future[dict[str, Any]] | None = None
        self._running = False
        self._closed = False
        adapter.attach(yandex_session_id=yandex_session_id, submit=self.submit)

    @property
    def active(self) -> bool:
        return self._running

    def submit(self, run: PresentationRun) -> None:
        if self._closed:
            raise RuntimeError("Yandex presentation session is closed")

        def enqueue() -> None:
            if self._queue.full():
                self._adapter.failed(run.probe_run_id, "Presentation probe queue is busy")
                return
            self._queue.put_nowait(run)

        self._loop.call_soon_threadsafe(enqueue)

    async def run(self, websocket: Any, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                run = await asyncio.wait_for(self._queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            await self._execute(websocket, run)

    async def _execute(self, websocket: Any, run: PresentationRun) -> None:
        self._running = True
        realtime_test_evidence.record(
            "ia1_probe_started",
            probe_run_id=run.probe_run_id,
            probe_selection=run.selection.value,
            yandex_session_id=self._session_id,
        )
        self._diagnostics.record("ia1_probe_started", probe_run_id=run.probe_run_id)
        failure: str | None = None
        try:
            if not self._interaction_idle():
                raise RuntimeError("Presentation probe requires an idle Realtime interaction")
            for case in run.cases:
                if not self._interaction_idle():
                    raise RuntimeError("Ordinary Realtime interaction became active between probe cases")
                self._adapter.case_started(run.probe_run_id, case.case_id)
                await self._execute_case(websocket, run, case)
        except Exception as exc:
            failure = f"{type(exc).__name__}: {str(exc)[:160]}"
        finally:
            if any(case.requested_voice is not None for case in run.cases):
                try:
                    await self._apply_voice(
                        websocket,
                        BASELINE_VOICE,
                        BASELINE_ROLE,
                        run,
                        restore=True,
                    )
                except Exception as exc:
                    restore_failure = f"voice/style restoration failed: {type(exc).__name__}"
                    failure = f"{failure}; {restore_failure}" if failure else restore_failure
            self._active = None
            self._running = False
        if failure:
            realtime_test_evidence.record(
                "ia1_probe_failed",
                probe_run_id=run.probe_run_id,
                error_type=failure.split(":", 1)[0],
            )
            self._diagnostics.record("ia1_probe_failed", error_type=failure.split(":", 1)[0])
            self._adapter.failed(run.probe_run_id, failure)
            return
        realtime_test_evidence.record(
            "ia1_probe_completed",
            probe_run_id=run.probe_run_id,
            yandex_session_id=self._session_id,
        )
        self._diagnostics.record("ia1_probe_completed", probe_run_id=run.probe_run_id)
        self._adapter.complete(run.probe_run_id)

    async def _execute_case(
        self,
        websocket: Any,
        run: PresentationRun,
        case: PresentationCase,
    ) -> None:
        if case.requested_voice is not None:
            await self._apply_voice(
                websocket,
                case.requested_voice,
                case.requested_role or BASELINE_ROLE,
                run,
            )
        loop = asyncio.get_running_loop()
        item_event_id = f"ia1-item-{uuid4().hex}"
        response_event_id = f"ia1-response-{uuid4().hex}"
        active = _ActiveCase(
            case=case,
            response_created=loop.create_future(),
            response_done=loop.create_future(),
            item_event_id=item_event_id,
            response_event_id=response_event_id,
        )
        self._active = active
        expected = semantic_presentation_text(case.semantic_response)
        realtime_test_evidence.record_probe_request(
            probe_run_id=run.probe_run_id,
            probe_case_id=case.case_id,
            response=case.semantic_response,
            expected_presentation=expected,
            requested_voice=case.requested_voice,
            requested_style=case.speech_style_id,
            client_item_event_id=item_event_id,
            client_response_event_id=response_event_id,
        )
        item, create = presentation_events(
            case,
            item_event_id=item_event_id,
            response_event_id=response_event_id,
        )
        started = time.monotonic()
        await websocket.send_json(item)
        await websocket.send_json(create)
        response_id = await asyncio.wait_for(active.response_created, PROBE_TIMEOUT_S)
        _done_id, status = await asyncio.wait_for(active.response_done, PROBE_TIMEOUT_S)
        elapsed_ms = (time.monotonic() - started) * 1000
        realtime_test_evidence.record_probe_completion(
            probe_run_id=run.probe_run_id,
            probe_case_id=case.case_id,
            response_id=response_id,
            status=status,
            interrupted=active.interrupted,
            completion_latency_ms=elapsed_ms,
        )
        self._active = None

    async def _apply_voice(
        self,
        websocket: Any,
        voice: str,
        role: str,
        run: PresentationRun,
        *,
        restore: bool = False,
    ) -> None:
        loop = asyncio.get_running_loop()
        if self._session_update is not None and not self._session_update.done():
            raise RuntimeError("A Yandex session update is already pending")
        acknowledgement = loop.create_future()
        self._session_update = acknowledgement
        client_event_id = f"ia1-session-{uuid4().hex}"
        started = time.monotonic()
        realtime_test_evidence.record(
            "ia1_session_update_requested",
            probe_run_id=run.probe_run_id,
            client_event_id=client_event_id,
            requested_voice=voice,
            requested_style=role,
            session_id_before=self._session_id,
            restoration=restore,
        )
        await websocket.send_json(
            {
                "type": "session.update",
                "event_id": client_event_id,
                "session": {"audio": {"output": {"voice": voice, "role": role}}},
            }
        )
        session = await asyncio.wait_for(acknowledgement, PROBE_TIMEOUT_S)
        session_id_after = str(session.get("id") or self._session_id)
        output = ((session.get("audio") or {}).get("output") or {})
        effective_voice = str(output.get("voice") or session.get("voice") or "")
        effective_role = str(output.get("role") or "")
        realtime_test_evidence.record(
            "ia1_session_update_acknowledged",
            probe_run_id=run.probe_run_id,
            provider_event_id=str(session.get("_event_id") or ""),
            requested_voice=voice,
            requested_style=role,
            effective_voice=effective_voice,
            effective_style=effective_role,
            session_id_before=self._session_id,
            session_id_after=session_id_after,
            session_identity_unchanged=session_id_after == self._session_id,
            session_update_latency_ms=(time.monotonic() - started) * 1000,
            restoration=restore,
        )
        if session_id_after != self._session_id:
            raise RuntimeError("Yandex session identity changed after session.update")
        if effective_voice != voice:
            raise RuntimeError("Yandex session.update did not confirm the requested voice")
        if effective_role != role:
            raise RuntimeError("Yandex session.update did not confirm the requested role")
        self._session_update = None

    def handle_event(self, event: dict[str, Any]) -> bool:
        """Observe provider events; return True only for a consumed probe error."""

        kind = str(event.get("type") or "")
        if kind == "session.updated" and self._session_update is not None:
            if not self._session_update.done():
                session = dict(event.get("session") or {})
                session["_event_id"] = str(event.get("event_id") or "")
                self._session_update.set_result(session)
            return False
        if kind == "error" and self._session_update is not None:
            if not self._session_update.done():
                self._session_update.set_exception(
                    RuntimeError("Yandex rejected the active IA-1 session update")
                )
            return True
        active = self._active
        if active is None:
            return False
        if kind == "input_audio_buffer.speech_started":
            active.interrupted = True
        elif kind == "response.created" and active.response_id is None:
            response = event.get("response") or {}
            response_id = str(response.get("id") or event.get("response_id") or "unknown")
            active.response_id = response_id
            if not active.response_created.done():
                active.response_created.set_result(response_id)
            realtime_test_evidence.record_probe_response_created(
                probe_case_id=active.case.case_id,
                response_id=response_id,
                provider_event_id=str(event.get("event_id") or ""),
            )
        elif kind == "conversation.item.created":
            realtime_test_evidence.record(
                "ia1_conversation_item_created",
                probe_case_id=active.case.case_id,
                provider_event_id=str(event.get("event_id") or ""),
                provider_item_id=str((event.get("item") or {}).get("id") or ""),
            )
        elif kind in {"response.output_audio_transcript.done", "response.output_text.done"}:
            response_id = str(event.get("response_id") or active.response_id or "")
            if response_id == active.response_id:
                realtime_test_evidence.record_probe_transcript(
                    probe_case_id=active.case.case_id,
                    response_id=response_id,
                    transcript=str(event.get("transcript") or event.get("text") or ""),
                    response=active.case.semantic_response,
                )
        elif kind == "response.done":
            response = event.get("response") or {}
            response_id = str(response.get("id") or event.get("response_id") or "")
            if response_id == active.response_id and not active.response_done.done():
                active.response_done.set_result(
                    (response_id, str(response.get("status") or "unknown"))
                )
        elif kind == "error":
            error = RuntimeError("Yandex rejected the active IA-1 presentation request")
            for future in (active.response_created, active.response_done, self._session_update):
                if future is not None and not future.done():
                    future.set_exception(error)
            return True
        return False

    def close(self) -> None:
        self._closed = True
        self._adapter.detach(self._session_id)


yandex_presentation = YandexPresentationAdapter()
