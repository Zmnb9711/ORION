"""Canonical provider-neutral instructions for ORION realtime voice sessions."""

from __future__ import annotations

import re


ORION_REALTIME_BASE_INSTRUCTIONS = (
    "You are ORION, the user's realtime conversational voice assistant. "
    "Your name is ORION; when naturally asked your name or identity, identify yourself as ORION. "
    "Talk naturally and concisely in the language used by the user. "
    "ORION Core is authoritative for current DCS flight facts. Never invent an aircraft, location, "
    "airfield, runway, heading, altitude, speed, telemetry value, frequency, traffic, clearance, "
    "or active mission. If authoritative context is unavailable, say so plainly."
)

FLIGHT_CONTEXT_START = "<ORION_CURRENT_FLIGHT_CONTEXT>"
FLIGHT_CONTEXT_END = "</ORION_CURRENT_FLIGHT_CONTEXT>"
_FLIGHT_CONTEXT_PATTERN = re.compile(
    rf"\n*{re.escape(FLIGHT_CONTEXT_START)}.*?{re.escape(FLIGHT_CONTEXT_END)}",
    re.DOTALL,
)


def compose_realtime_instructions(base_instructions: str, flight_context: str) -> str:
    """Return one complete instruction snapshot with exactly one context block."""
    base = _FLIGHT_CONTEXT_PATTERN.sub("", base_instructions).strip()
    context = flight_context.strip()
    return (
        f"{base}\n\n{FLIGHT_CONTEXT_START}\n"
        f"{context}\n"
        f"{FLIGHT_CONTEXT_END}"
    )
