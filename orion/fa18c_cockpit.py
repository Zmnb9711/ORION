from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from orion.fa18c_systems import ManualReference


class HornetCockpitControlId(StrEnum):
    UFC = "ufc"
    LEFT_DDI = "left_ddi"
    RIGHT_DDI = "right_ddi"
    MPCD = "mpcd"
    COMM1_CHANNEL = "comm1_channel"
    COMM2_CHANNEL = "comm2_channel"
    SENSOR_CONTROL_SWITCH = "sensor_control_switch"


class HornetCockpitControl(BaseModel):
    control_id: HornetCockpitControlId
    title: str
    aliases: set[str] = Field(default_factory=set)
    location: str
    purpose: str
    interaction: str
    live_data_preferred: list[str] = Field(default_factory=list)
    references: list[ManualReference] = Field(default_factory=list)


CONTROLS: tuple[HornetCockpitControl, ...] = (
    HornetCockpitControl(
        control_id=HornetCockpitControlId.UFC,
        title="Up Front Control (UFC)",
        aliases={"ufc", "up front control", "up-front control", "панель ufc", "уфк"},
        location="Upper center instrument panel, directly below the HUD.",
        purpose="Primary keypad/display interface for many communications, navigation and avionics data-entry tasks.",
        interaction="Use the option-select controls and keypad according to the selected UFC function; verify entered data before accepting it.",
        live_data_preferred=["ufc_mode", "ufc_scratchpad", "selected_comm_radio"],
        references=[ManualReference(section="COCKPIT / UP FRONT CONTROL (UFC)")],
    ),
    HornetCockpitControl(
        control_id=HornetCockpitControlId.LEFT_DDI,
        title="Left Digital Display Indicator (LDDI)",
        aliases={"left ddi", "lddi", "левый ddi", "левый дисплей"},
        location="Left side of the main instrument panel.",
        purpose="Multifunction tactical/avionics display; available pages depend on current avionics and sensor state.",
        interaction="Use the surrounding option-select buttons to select displayed functions and pages.",
        live_data_preferred=["left_ddi_page", "sensor_of_interest"],
        references=[ManualReference(section="COCKPIT / DIGITAL DISPLAY INDICATORS")],
    ),
    HornetCockpitControl(
        control_id=HornetCockpitControlId.RIGHT_DDI,
        title="Right Digital Display Indicator (RDDI)",
        aliases={"right ddi", "rddi", "правый ddi", "правый дисплей"},
        location="Right side of the main instrument panel.",
        purpose="Multifunction tactical/avionics display; commonly used for sensor, tactical and stores pages.",
        interaction="Use the surrounding option-select buttons to select displayed functions and pages.",
        live_data_preferred=["right_ddi_page", "sensor_of_interest"],
        references=[ManualReference(section="COCKPIT / DIGITAL DISPLAY INDICATORS")],
    ),
    HornetCockpitControl(
        control_id=HornetCockpitControlId.MPCD,
        title="Multipurpose Color Display (MPCD)",
        aliases={"mpcd", "amcd", "center display", "центральный дисплей", "цветной дисплей"},
        location="Lower center instrument panel.",
        purpose="Multifunction color display used for navigation and tactical pages, including HSI-related presentation.",
        interaction="Use the bezel option-select buttons to select and control the displayed page.",
        live_data_preferred=["mpcd_page", "selected_waypoint"],
        references=[ManualReference(section="COCKPIT / MULTIPURPOSE COLOR DISPLAY / HSI")],
    ),
    HornetCockpitControl(
        control_id=HornetCockpitControlId.COMM1_CHANNEL,
        title="COMM1 channel selector",
        aliases={"comm1 channel", "comm 1 channel", "radio 1 preset", "comm1 preset", "канал comm1", "канал радио 1"},
        location="Left console communications controls, with COMM1 selection also represented through UFC radio functions.",
        purpose="Select the COMM1 preset/channel used for the current radio task.",
        interaction="Select the mission-assigned preset/channel; ORION must resolve the actual channel-to-frequency mapping from mission/aircraft data when available.",
        live_data_preferred=["comm1_preset", "comm1_frequency", "mission_radio_presets"],
        references=[ManualReference(section="COMMUNICATIONS SYSTEM / COMM1")],
    ),
    HornetCockpitControl(
        control_id=HornetCockpitControlId.COMM2_CHANNEL,
        title="COMM2 channel selector",
        aliases={"comm2 channel", "comm 2 channel", "radio 2 preset", "comm2 preset", "канал comm2", "канал радио 2"},
        location="Left console communications controls, with COMM2 selection also represented through UFC radio functions.",
        purpose="Select the COMM2 preset/channel used for the current radio task.",
        interaction="Select the mission-assigned preset/channel; ORION must resolve the actual channel-to-frequency mapping from mission/aircraft data when available.",
        live_data_preferred=["comm2_preset", "comm2_frequency", "mission_radio_presets"],
        references=[ManualReference(section="COMMUNICATIONS SYSTEM / COMM2")],
    ),
    HornetCockpitControl(
        control_id=HornetCockpitControlId.SENSOR_CONTROL_SWITCH,
        title="Sensor Control Switch (SCS)",
        aliases={"sensor control switch", "scs", "sensor switch", "переключатель sensor control", "soi"},
        location="HOTAS control on the flight stick.",
        purpose="Assign/control sensor and display functions according to the active master mode and avionics page.",
        interaction="Direction-specific actions are context dependent; ORION should use the current display/sensor state before giving the next action.",
        live_data_preferred=["sensor_of_interest", "left_ddi_page", "right_ddi_page", "mpcd_page", "master_mode"],
        references=[ManualReference(section="COCKPIT CONTROLS / SENSOR CONTROL SWITCH")],
    ),
)


class HornetCockpitKnowledge:
    def __init__(self) -> None:
        self._controls = {item.control_id: item for item in CONTROLS}

    def list_controls(self) -> list[HornetCockpitControl]:
        return [item.model_copy(deep=True) for item in self._controls.values()]

    def get(self, control_id: HornetCockpitControlId) -> HornetCockpitControl | None:
        item = self._controls.get(control_id)
        return item.model_copy(deep=True) if item else None

    def find(self, text: str) -> list[HornetCockpitControl]:
        needle = text.strip().casefold()
        if not needle:
            return []
        matches: list[HornetCockpitControl] = []
        for item in self._controls.values():
            values = {item.control_id.value.casefold(), item.title.casefold(), *(alias.casefold() for alias in item.aliases)}
            if any(needle == value or needle in value or value in needle for value in values):
                matches.append(item.model_copy(deep=True))
        return matches


fa18c_cockpit = HornetCockpitKnowledge()
