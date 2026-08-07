from __future__ import annotations

from pydantic import BaseModel, Field

from orion.fa18c_cockpit_adapter import normalize_hornet_cockpit_state
from orion.fa18c_live_validation import HornetLiveValidationSnapshot, hornet_live_validator
from orion.fa18c_mapping_registry import hornet_mapping_registry
from orion.fa18c_value_profiles import hornet_value_profile_registry
from orion.models import TelemetryEnvelope


class CockpitVoiceResult(BaseModel):
    completed: bool
    spoken_text: str
    data: dict[str, object] = Field(default_factory=dict)


def execute_cockpit_query(intent: str, telemetry: TelemetryEnvelope | None) -> CockpitVoiceResult:
    if telemetry is None:
        return CockpitVoiceResult(completed=False, spoken_text="Нет живой телеметрии DCS. Запустите DCS и войдите в кабину.")
    if telemetry.state.aircraft_type.strip().lower() not in {"fa-18c", "fa-18c_hornet", "fa-18c lot 20", "fa-18c_hornet lot 20"}:
        return CockpitVoiceResult(completed=False, spoken_text=f"Живые запросы кабины пока поддерживаются для F/A-18C. Сейчас обнаружен {telemetry.state.aircraft_type}.")

    validation = hornet_live_validator.snapshot()
    if intent == "cockpit_readiness_query":
        return _readiness(validation)

    mapping = hornet_mapping_registry.current()
    profiles = hornet_value_profile_registry.current()
    state = normalize_hornet_cockpit_state(telemetry.state.cockpit_state, mapping=mapping, profiles=profiles)
    if state is None:
        return CockpitVoiceResult(completed=False, spoken_text="Не удалось прочитать состояние кабины Hornet.")

    if intent == "cockpit_tacan_query":
        if state.tacan_channel is None or state.tacan_band not in {"X", "Y"}:
            return CockpitVoiceResult(completed=False, spoken_text="TACAN пока не декодирован из живой телеметрии.")
        power = "включён" if state.tacan_enabled else "выключен" if state.tacan_enabled is False else "состояние питания неизвестно"
        return CockpitVoiceResult(completed=True, spoken_text=f"TACAN {state.tacan_channel} {state.tacan_band}, {power}.", data={"tacan_channel": state.tacan_channel, "tacan_band": state.tacan_band, "tacan_enabled": state.tacan_enabled})

    if intent in {"cockpit_comm1_query", "cockpit_comm2_query"}:
        radio = 1 if intent == "cockpit_comm1_query" else 2
        preset = state.comm1_preset if radio == 1 else state.comm2_preset
        frequency = state.comm1_frequency if radio == 1 else state.comm2_frequency
        if preset is None:
            return CockpitVoiceResult(completed=False, spoken_text=f"COMM{radio} пока не декодирован из живой телеметрии.")
        text = f"COMM{radio}, preset {preset}"
        if frequency is not None:
            text += f", {frequency:.3f} мегагерц"
        return CockpitVoiceResult(completed=True, spoken_text=text + ".", data={f"comm{radio}_preset": preset, f"comm{radio}_frequency": frequency})

    return CockpitVoiceResult(completed=False, spoken_text="Этот запрос состояния кабины пока не поддерживается.")


def _readiness(validation: HornetLiveValidationSnapshot) -> CockpitVoiceResult:
    if validation.validated:
        return CockpitVoiceResult(completed=True, spoken_text="ORION готов к полёту. Живая проверка TACAN и обоих COMM завершена.", data=validation.model_dump())
    missing: list[str] = []
    if not validation.tacan_valid:
        missing.append("TACAN")
    if not validation.comm1_valid:
        missing.append("COMM1")
    if not validation.comm2_valid:
        missing.append("COMM2")
    detail = ", ".join(missing) if missing else validation.last_issue or "нужны дополнительные живые samples"
    return CockpitVoiceResult(completed=True, spoken_text=f"Ещё не Ready to Fly. Живая проверка: {validation.consecutive_valid_samples} из {validation.required_samples}. Не подтверждено: {detail}.", data=validation.model_dump())
