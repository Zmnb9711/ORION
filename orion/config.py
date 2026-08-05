from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    telemetry_host: str = "127.0.0.1"
    telemetry_port: int = 45100
    command_host: str = "127.0.0.1"
    command_port: int = 45101
    event_log_path: str = "data/events.jsonl"

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        return cls(
            telemetry_host=os.getenv("ORION_TELEMETRY_HOST", defaults.telemetry_host),
            telemetry_port=int(
                os.getenv("ORION_TELEMETRY_PORT", str(defaults.telemetry_port))
            ),
            command_host=os.getenv("ORION_COMMAND_HOST", defaults.command_host),
            command_port=int(
                os.getenv("ORION_COMMAND_PORT", str(defaults.command_port))
            ),
            event_log_path=os.getenv("ORION_EVENT_LOG_PATH", defaults.event_log_path),
        )


settings = Settings.from_env()
