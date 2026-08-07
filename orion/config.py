from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    flight_bridge_host: str = "127.0.0.1"
    flight_bridge_telemetry_port: int = 45100
    flight_bridge_command_port: int = 45101
    mission_bridge_host: str = "127.0.0.1"
    mission_bridge_port: int = 45200
    event_log_path: str = "data/events.jsonl"

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        return cls(
            flight_bridge_host=os.getenv(
                "ORION_FLIGHT_BRIDGE_HOST", defaults.flight_bridge_host
            ),
            flight_bridge_telemetry_port=int(
                os.getenv(
                    "ORION_FLIGHT_BRIDGE_TELEMETRY_PORT",
                    str(defaults.flight_bridge_telemetry_port),
                )
            ),
            flight_bridge_command_port=int(
                os.getenv(
                    "ORION_FLIGHT_BRIDGE_COMMAND_PORT",
                    str(defaults.flight_bridge_command_port),
                )
            ),
            mission_bridge_host=os.getenv(
                "ORION_MISSION_BRIDGE_HOST", defaults.mission_bridge_host
            ),
            mission_bridge_port=int(
                os.getenv(
                    "ORION_MISSION_BRIDGE_PORT", str(defaults.mission_bridge_port)
                )
            ),
            event_log_path=os.getenv("ORION_EVENT_LOG_PATH", defaults.event_log_path),
        )

    @property
    def telemetry_host(self) -> str:
        return self.flight_bridge_host

    @property
    def telemetry_port(self) -> int:
        return self.flight_bridge_telemetry_port

    @property
    def command_host(self) -> str:
        return self.flight_bridge_host

    @property
    def command_port(self) -> int:
        return self.flight_bridge_command_port


settings = Settings.from_env()
