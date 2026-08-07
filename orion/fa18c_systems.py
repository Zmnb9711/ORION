from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


OFFICIAL_GUIDE_SOURCE_ID = "ed-fa18c-early-access-guide-en"
OFFICIAL_GUIDE_URL = (
    "https://www.digitalcombatsimulator.com/en/downloads/documentation/"
    "dcs-hornet_early_access_guide_en/"
)
OFFICIAL_GUIDE_PDF_URL = (
    "https://www.digitalcombatsimulator.com/upload/iblock/8d7/"
    "2s3e89jqknz7xmti8hrhe1bjt2uw1s3e/DCS%20FA-18C%20Early%20Access%20Guide%20EN.pdf"
)
OFFICIAL_GUIDE_RU_URL = (
    "https://www.digitalcombatsimulator.com/en/downloads/documentation/"
    "DCS_FA-18C_Early_Access_Guide_RU/"
)


class HornetSystemId(StrEnum):
    COMMUNICATIONS = "communications"
    TACAN = "tacan"
    INS_NAVIGATION = "ins_navigation"
    AIR_TO_AIR_RADAR = "air_to_air_radar"
    SENSOR_CONTROL = "sensor_control"
    STORES_MANAGEMENT = "stores_management"
    AUTOPILOT = "autopilot"
    CARRIER_OPERATIONS = "carrier_operations"


class HornetProcedureId(StrEnum):
    COLD_START = "cold_start"
    TACAN_NAVIGATION = "tacan_navigation"
    RADIO_PRESET_USE = "radio_preset_use"
    WAYPOINT_NAVIGATION = "waypoint_navigation"
    CARRIER_RECOVERY_SETUP = "carrier_recovery_setup"


class ManualReference(BaseModel):
    source_id: str = OFFICIAL_GUIDE_SOURCE_ID
    section: str = Field(min_length=1, max_length=240)
    locator: str = OFFICIAL_GUIDE_URL
    pdf_locator: str = OFFICIAL_GUIDE_PDF_URL
    note: str | None = Field(default=None, max_length=500)


class HornetSystemTopic(BaseModel):
    system_id: HornetSystemId
    title: str
    aliases: set[str] = Field(default_factory=set)
    summary: str
    references: list[ManualReference] = Field(default_factory=list)
    live_data_preferred: list[str] = Field(default_factory=list)
    related_procedures: list[HornetProcedureId] = Field(default_factory=list)


class HornetProcedure(BaseModel):
    procedure_id: HornetProcedureId
    title: str
    aliases: set[str] = Field(default_factory=set)
    purpose: str
    prerequisites: list[str] = Field(default_factory=list)
    ordered_phases: list[str] = Field(default_factory=list)
    references: list[ManualReference] = Field(default_factory=list)
    state_aware: bool = True


SYSTEM_TOPICS: tuple[HornetSystemTopic, ...] = (
    HornetSystemTopic(
        system_id=HornetSystemId.COMMUNICATIONS,
        title="COMM1 / COMM2 communications",
        aliases={"comm1", "comm2", "radio", "radios", "uhf", "vhf", "preset", "presets", "frequency"},
        summary=(
            "The Hornet communications layer covers both cockpit radios, preset-channel operation, manual tuning, "
            "radio selection and mission-provided frequencies. ORION should use live mission/unit data for current "
            "frequencies and channel assignments, while the manual provides the aircraft operating method."
        ),
        references=[ManualReference(section="COMMUNICATIONS SYSTEM")],
        live_data_preferred=["current_frequency", "preset_channel", "unit_frequency", "airfield_frequency"],
        related_procedures=[HornetProcedureId.RADIO_PRESET_USE],
    ),
    HornetSystemTopic(
        system_id=HornetSystemId.TACAN,
        title="TACAN navigation",
        aliases={"tacan", "tcn", "tacan channel", "tacan station", "bearing", "range"},
        summary=(
            "TACAN provides bearing/range navigation to a selected station. The Hornet can tune TACAN channels and "
            "also maintains an onboard TACAN database; in DCS that database is populated for the current theater. "
            "ORION must obtain the current tanker/airfield TACAN channel from mission data when answering a live request."
        ),
        references=[ManualReference(section="HSI / DATA / TCN TACAN database and TACAN operation")],
        live_data_preferred=["tacan_channel", "tacan_band", "tanker_tacan", "airfield_tacan"],
        related_procedures=[HornetProcedureId.TACAN_NAVIGATION],
    ),
    HornetSystemTopic(
        system_id=HornetSystemId.INS_NAVIGATION,
        title="INS, HSI and waypoint navigation",
        aliases={"ins", "hsi", "waypoint", "waypoints", "navigation", "nav", "gps", "alignment"},
        summary=(
            "The navigation layer covers INS/GPS-related operation, HSI navigation presentation, waypoint selection "
            "and aircraft navigation data. ORION should combine stable operating knowledge with the current aircraft "
            "position, selected waypoint and mission route when answering state-dependent questions."
        ),
        references=[ManualReference(section="NAVIGATION / HSI / waypoint and INS operation")],
        live_data_preferred=["ownship_position", "selected_waypoint", "waypoint_range", "waypoint_bearing"],
        related_procedures=[HornetProcedureId.WAYPOINT_NAVIGATION, HornetProcedureId.COLD_START],
    ),
    HornetSystemTopic(
        system_id=HornetSystemId.AIR_TO_AIR_RADAR,
        title="Air-to-air radar",
        aliases={"radar", "a/a radar", "air to air radar", "rws", "tws", "stt", "ltws"},
        summary=(
            "The air-to-air radar topic covers search and track presentation, acquisition/track concepts and the "
            "Hornet-specific radar workflow. ORION should distinguish documented aircraft capability from the current "
            "radar mode and contacts reported by telemetry or mission sensors."
        ),
        references=[ManualReference(section="AIR-TO-AIR RADAR")],
        live_data_preferred=["radar_mode", "radar_contacts", "sensor_of_interest"],
    ),
    HornetSystemTopic(
        system_id=HornetSystemId.SENSOR_CONTROL,
        title="Sensor Control Switch and display assignment",
        aliases={"sensor control", "sensor control switch", "scs", "soi", "ddi", "mpcd", "hud sensor"},
        summary=(
            "Hornet sensor control is organized around display/sensor assignment and the Sensor Control Switch. ORION "
            "uses this topic when explaining which display or sensor is being controlled and should prefer live cockpit "
            "state when determining the current sensor of interest."
        ),
        references=[ManualReference(section="COCKPIT CONTROLS / SENSOR CONTROL SWITCH / DDI and MPCD operation")],
        live_data_preferred=["sensor_of_interest", "left_ddi_page", "right_ddi_page", "mpcd_page"],
    ),
    HornetSystemTopic(
        system_id=HornetSystemId.STORES_MANAGEMENT,
        title="Stores Management System",
        aliases={"sms", "stores", "stores management", "weapon page", "loadout", "inventory"},
        summary=(
            "Stores Management System knowledge describes how the Hornet represents and configures carried stores. "
            "ORION must use the actual mission loadout or aircraft state before claiming that a store is available."
        ),
        references=[ManualReference(section="STORES MANAGEMENT SET / SMS")],
        live_data_preferred=["loadout", "station_inventory", "selected_store"],
    ),
    HornetSystemTopic(
        system_id=HornetSystemId.AUTOPILOT,
        title="Automatic Flight Control / autopilot",
        aliases={"autopilot", "ap", "afcs", "attitude hold", "heading select", "coupled"},
        summary=(
            "The autopilot topic covers Hornet automatic flight-control modes and their operating conditions. ORION "
            "should check current flight state before recommending a mode or explaining why engagement is unavailable."
        ),
        references=[ManualReference(section="AUTOMATIC FLIGHT CONTROL SYSTEM / AUTOPILOT")],
        live_data_preferred=["autopilot_mode", "airspeed", "attitude", "flight_control_state"],
    ),
    HornetSystemTopic(
        system_id=HornetSystemId.CARRIER_OPERATIONS,
        title="Carrier operations",
        aliases={"carrier", "case i", "case ii", "case iii", "boat", "recovery", "carrier landing"},
        summary=(
            "Carrier-operation knowledge covers aircraft setup and DCS Hornet carrier procedures. ORION should combine "
            "manual procedure knowledge with the active mission, carrier position, weather, marshal/recovery data and "
            "current aircraft state rather than treating recovery parameters as fixed values."
        ),
        references=[ManualReference(section="CARRIER OPERATIONS")],
        live_data_preferred=["carrier_position", "carrier_course", "weather", "recovery_case", "marshal_data"],
        related_procedures=[HornetProcedureId.CARRIER_RECOVERY_SETUP],
    ),
)


PROCEDURES: tuple[HornetProcedure, ...] = (
    HornetProcedure(
        procedure_id=HornetProcedureId.COLD_START,
        title="Cold-start workflow",
        aliases={"cold start", "startup", "start up", "engine start", "cold and dark"},
        purpose="Guide a cold-and-dark Hornet from initial cockpit state toward a flight-ready configuration.",
        prerequisites=["aircraft is on the ground", "current cockpit state is available when possible"],
        ordered_phases=[
            "pre-start safety and power configuration",
            "engine start sequence",
            "navigation/INS initialization and alignment",
            "avionics and flight-control checks",
            "mission/radio/navigation setup",
            "before-taxi readiness check",
        ],
        references=[ManualReference(section="STARTUP PROCEDURE / NORMAL PROCEDURES")],
    ),
    HornetProcedure(
        procedure_id=HornetProcedureId.TACAN_NAVIGATION,
        title="TACAN navigation setup",
        aliases={"set tacan", "tune tacan", "tacan navigation", "navigate tacan"},
        purpose="Configure the Hornet to navigate using a requested TACAN station/channel.",
        prerequisites=["TACAN channel/band is known or can be obtained from mission data"],
        ordered_phases=[
            "resolve requested station and live TACAN channel/band",
            "enter/select TACAN channel and band",
            "enable the required TACAN navigation presentation",
            "verify station identification and navigation indications",
        ],
        references=[ManualReference(section="TACAN / HSI navigation")],
    ),
    HornetProcedure(
        procedure_id=HornetProcedureId.RADIO_PRESET_USE,
        title="Use a radio preset channel",
        aliases={"radio preset", "preset channel", "select channel", "comm channel"},
        purpose="Select a mission-defined COMM1/COMM2 preset without requiring manual frequency entry.",
        prerequisites=["radio and preset channel are known from aircraft/mission data"],
        ordered_phases=[
            "resolve intended recipient and required frequency",
            "map frequency to the Hornet radio/preset when mission data exposes that mapping",
            "select the appropriate COMM radio and preset channel",
            "verify the selected channel/frequency before transmission",
        ],
        references=[ManualReference(section="COMMUNICATIONS SYSTEM / COMM1 and COMM2")],
    ),
    HornetProcedure(
        procedure_id=HornetProcedureId.WAYPOINT_NAVIGATION,
        title="Waypoint navigation",
        aliases={"waypoint navigation", "select waypoint", "navigate waypoint", "steerpoint"},
        purpose="Use Hornet navigation displays and waypoint data to navigate to a selected mission point.",
        prerequisites=["waypoint exists in the aircraft or mission route"],
        ordered_phases=[
            "identify/select the required waypoint",
            "display navigation steering information",
            "cross-check range, bearing and route context",
            "monitor progress using live ownship and waypoint data",
        ],
        references=[ManualReference(section="HSI / WAYPOINT navigation")],
    ),
    HornetProcedure(
        procedure_id=HornetProcedureId.CARRIER_RECOVERY_SETUP,
        title="Carrier recovery setup",
        aliases={"carrier recovery", "recovery setup", "case i setup", "case iii setup", "landing on carrier"},
        purpose="Prepare the aircraft navigation/communications and cockpit state for the active carrier recovery.",
        prerequisites=["active carrier/recovery information is available from the mission or controller"],
        ordered_phases=[
            "resolve carrier, recovery case and current recovery data",
            "configure required communications and navigation references",
            "prepare aircraft systems for approach/recovery",
            "verify state before entering the applicable recovery procedure",
        ],
        references=[ManualReference(section="CARRIER OPERATIONS / RECOVERY")],
    ),
)


class HornetKnowledgePack:
    def __init__(self) -> None:
        self._systems = {item.system_id: item for item in SYSTEM_TOPICS}
        self._procedures = {item.procedure_id: item for item in PROCEDURES}

    def list_systems(self) -> list[HornetSystemTopic]:
        return [item.model_copy(deep=True) for item in self._systems.values()]

    def list_procedures(self) -> list[HornetProcedure]:
        return [item.model_copy(deep=True) for item in self._procedures.values()]

    def get_system(self, system_id: HornetSystemId) -> HornetSystemTopic | None:
        item = self._systems.get(system_id)
        return item.model_copy(deep=True) if item else None

    def get_procedure(self, procedure_id: HornetProcedureId) -> HornetProcedure | None:
        item = self._procedures.get(procedure_id)
        return item.model_copy(deep=True) if item else None

    def find(self, text: str) -> dict[str, list[HornetSystemTopic | HornetProcedure]]:
        needle = text.strip().casefold()
        if not needle:
            return {"systems": [], "procedures": []}

        systems = []
        for item in self._systems.values():
            haystack = {item.system_id.value.casefold(), item.title.casefold()}
            haystack.update(alias.casefold() for alias in item.aliases)
            if any(needle == value or needle in value for value in haystack):
                systems.append(item.model_copy(deep=True))

        procedures = []
        for item in self._procedures.values():
            haystack = {item.procedure_id.value.casefold(), item.title.casefold()}
            haystack.update(alias.casefold() for alias in item.aliases)
            if any(needle == value or needle in value for value in haystack):
                procedures.append(item.model_copy(deep=True))

        return {"systems": systems, "procedures": procedures}


fa18c_knowledge_pack = HornetKnowledgePack()
