from __future__ import annotations

from pydantic import BaseModel, Field

from orion.voice_context import VoiceConversationContext, voice_contexts
from orion.voice_core import VoiceCommand, voice_commands
from orion.voice_execution import ExecutionOutcome, ExecutionState, voice_execution
from orion.voice_understanding import ParsedVoiceRequest, parse_transcript


class ProcessedVoiceCommand(BaseModel):
    command: VoiceCommand
    outcome: ExecutionOutcome
    spoken_text: str | None = None


class VoicePipelineResult(BaseModel):
    parsed: ParsedVoiceRequest
    executions: list[ProcessedVoiceCommand] = Field(default_factory=list)
    context: VoiceConversationContext


def process_transcript(transcript: str, session_id: str = "default") -> VoicePipelineResult:
    """Understand, execute and finalize one transcript without external queue choreography."""
    context = voice_contexts.get(session_id)
    parsed = parse_transcript(transcript, context)
    executions: list[ProcessedVoiceCommand] = []

    for command_create in parsed.commands:
        submitted = voice_commands.submit(command_create)
        running = voice_commands.start(submitted.command_id)
        outcome = voice_execution.execute(running)
        spoken_text = _spoken_text(outcome)

        if outcome.state is ExecutionState.COMPLETED:
            final = voice_commands.complete(running.command_id, spoken_text or outcome.message)
        elif outcome.state is ExecutionState.REJECTED:
            final = voice_commands.fail(running.command_id, spoken_text or outcome.message)
        else:
            final = voice_commands.get(running.command_id) or running

        context = _update_context(session_id, final, outcome)
        executions.append(
            ProcessedVoiceCommand(
                command=final,
                outcome=outcome,
                spoken_text=spoken_text,
            )
        )

    return VoicePipelineResult(parsed=parsed, executions=executions, context=context)


def _spoken_text(outcome: ExecutionOutcome) -> str | None:
    value = outcome.payload.get("spoken_text")
    return value if isinstance(value, str) and value.strip() else None


def _unit_payload(outcome: ExecutionOutcome) -> dict[str, object] | None:
    unit = outcome.payload.get("unit")
    if isinstance(unit, dict):
        return unit
    units = outcome.payload.get("units")
    if isinstance(units, list) and units:
        first = units[0]
        if isinstance(first, dict):
            nested = first.get("unit")
            return nested if isinstance(nested, dict) else first
    return None


def _update_context(
    session_id: str,
    command: VoiceCommand,
    outcome: ExecutionOutcome,
) -> VoiceConversationContext:
    entities: dict[str, str] = {}
    unit = _unit_payload(outcome)
    if unit is not None:
        callsign = unit.get("callsign")
        unit_id = unit.get("unit_id")
        unit_type = unit.get("unit_type")
        if isinstance(callsign, str):
            entities["callsign"] = callsign
            entities["last_unit_callsign"] = callsign
        if isinstance(unit_id, str):
            entities["unit_id"] = unit_id
            entities["last_unit_id"] = unit_id
        if isinstance(unit_type, str):
            entities["unit_type"] = unit_type
            entities["last_unit_type"] = unit_type

    landmark = outcome.payload.get("landmark")
    if isinstance(landmark, dict):
        name = landmark.get("name")
        landmark_id = landmark.get("landmark_id")
        if isinstance(name, str):
            entities["landmark_name"] = name
            entities["last_landmark"] = name
        if isinstance(landmark_id, str):
            entities["landmark_id"] = landmark_id
            entities["last_landmark_id"] = landmark_id

    subject = entities.get("callsign") or entities.get("landmark_name")
    if subject is None and command.agent.value not in {"system", "general_conversation"}:
        subject = command.agent.value

    return voice_contexts.update(
        session_id,
        agent=command.agent,
        subject=subject,
        intent=command.intent,
        entities=entities,
    )
