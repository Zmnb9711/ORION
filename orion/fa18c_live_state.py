from __future__ import annotations

from pydantic import BaseModel, Field

from orion.fa18c_cockpit_adapter import cockpit_state_for_voice


class HornetLiveAdvice(BaseModel):
    spoken_text: str
    topic: str
    observed: dict[str, object] = Field(default_factory=dict)
    next_actions: list[str] = Field(default_factory=list)


def advise_hornet_live_state(text: str, context: dict[str, object]) -> HornetLiveAdvice | None:
    state = cockpit_state_for_voice(context.get("cockpit_state"))
    if state is None:
        return None

    normalized = text.casefold()
    if "tacan" in normalized:
        return _advise_tacan(state)
    if any(token in normalized for token in ("comm1", "comm 1", "radio 1", "радио 1")):
        return _advise_radio(state, 1)
    if any(token in normalized for token in ("comm2", "comm 2", "radio 2", "радио 2")):
        return _advise_radio(state, 2)
    if any(token in normalized for token in ("ddi", "mpcd", "диспле")):
        return _advise_displays(state)
    return None


def _advise_tacan(state: dict[str, object]) -> HornetLiveAdvice:
    enabled = _bool(state.get("tacan_enabled"))
    channel = state.get("tacan_channel")
    band = state.get("tacan_band")
    target = state.get("requested_tacan_channel") or state.get("mission_tacan_channel")
    target_band = state.get("requested_tacan_band") or state.get("mission_tacan_band")

    actions: list[str] = []
    if enabled is False:
        actions.append("включи TACAN")
    if target is not None and channel != target:
        suffix = f" {target_band}" if target_band else ""
        actions.append(f"установи канал {target}{suffix}".strip())
    elif channel is None:
        actions.append("введи требуемый канал TACAN на UFC")
    if enabled is not True or channel is None:
        actions.append("проверь индикацию и навигационный источник после ввода")

    mapping_validated = state.get("mapping_validated") is True
    raw = state.get("raw_arguments") if isinstance(state.get("raw_arguments"), dict) else {}
    current = "TACAN"
    if enabled is False:
        current += " сейчас выключен"
    elif enabled is True:
        current += " включён"
    elif raw and not mapping_validated:
        current += ": сырые данные DCS получены, но карта аргументов ещё не подтверждена"
    if channel is not None:
        current += f", текущий канал {channel}{(' ' + str(band)) if band else ''}"
    spoken = current + "."
    if actions and (enabled is not None or channel is not None or target is not None):
        spoken += " Следующее действие: " + "; затем ".join(actions) + "."
    return HornetLiveAdvice(spoken_text=spoken, topic="tacan", observed={"enabled": enabled, "channel": channel, "band": band, "target_channel": target, "target_band": target_band, "mapping_validated": mapping_validated, "raw_arguments": raw}, next_actions=actions)


def _advise_radio(state: dict[str, object], radio: int) -> HornetLiveAdvice:
    prefix = f"comm{radio}"
    preset = state.get(f"{prefix}_preset")
    frequency = state.get(f"{prefix}_frequency")
    target_preset = state.get(f"requested_{prefix}_preset") or state.get(f"mission_{prefix}_preset")
    target_frequency = state.get(f"requested_{prefix}_frequency") or state.get(f"mission_{prefix}_frequency")
    actions: list[str] = []
    if target_preset is not None and preset != target_preset:
        actions.append(f"выбери preset {target_preset} на COMM{radio}")
    if target_frequency is not None and frequency != target_frequency:
        actions.append(f"настрой COMM{radio} на {target_frequency}")
    if preset is None and frequency is None:
        actions.append(f"проверь текущий preset/frequency COMM{radio} через данные DCS")
    mapping_validated = state.get("mapping_validated") is True
    raw = state.get("raw_arguments") if isinstance(state.get("raw_arguments"), dict) else {}
    if preset is None and frequency is None and raw and not mapping_validated:
        spoken = f"COMM{radio}: сырые данные DCS получены, но карта аргументов ещё не подтверждена."
    else:
        spoken = f"COMM{radio}: preset {preset if preset is not None else 'не определён'}, частота {frequency if frequency is not None else 'не определена'}."
    if actions and (preset is not None or frequency is not None or target_preset is not None or target_frequency is not None):
        spoken += " Следующее действие: " + "; затем ".join(actions) + "."
    return HornetLiveAdvice(spoken_text=spoken, topic=prefix, observed={"preset": preset, "frequency": frequency, "target_preset": target_preset, "target_frequency": target_frequency, "mapping_validated": mapping_validated, "raw_arguments": raw}, next_actions=actions)


def _advise_displays(state: dict[str, object]) -> HornetLiveAdvice:
    observed = {
        "left_ddi_page": state.get("left_ddi_page"),
        "right_ddi_page": state.get("right_ddi_page"),
        "mpcd_page": state.get("mpcd_page"),
        "sensor_of_interest": state.get("sensor_of_interest"),
        "master_mode": state.get("master_mode"),
        "left_ddi_brightness_raw": state.get("left_ddi_brightness_raw"),
        "right_ddi_brightness_raw": state.get("right_ddi_brightness_raw"),
        "mpcd_brightness_raw": state.get("mpcd_brightness_raw"),
        "mapping_validated": state.get("mapping_validated"),
    }
    parts = [f"{key}={value}" for key, value in observed.items() if value is not None and key != "mapping_validated"]
    spoken = "Текущее состояние дисплеев Hornet: " + (", ".join(parts) if parts else "данные страниц пока не получены") + "."
    return HornetLiveAdvice(spoken_text=spoken, topic="displays", observed=observed)


def _bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"on", "true", "1", "enabled"}:
            return True
        if lowered in {"off", "false", "0", "disabled"}:
            return False
    return None
