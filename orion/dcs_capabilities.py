from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class DcsCommandChannel(StrEnum):
    NATIVE_RADIO_MENU = "native_radio_menu"
    MISSION_BRIDGE = "mission_bridge"
    INFORMATION_ONLY = "information_only"


class DcsRecipientType(StrEnum):
    WINGMAN = "wingman"
    FLIGHT = "flight"
    COALITION_AIRCRAFT = "coalition_aircraft"
    COALITION_HELICOPTER = "coalition_helicopter"
    COALITION_GROUND = "coalition_ground"
    COALITION_NAVAL = "coalition_naval"
    JTAC = "jtac"
    AWACS = "awacs"
    TANKER = "tanker"


class DcsCapability(BaseModel):
    capability_id: str
    recipient_types: set[DcsRecipientType]
    intents: set[str]
    channel: DcsCommandChannel
    dcs_command: str | None = None
    requires_confirmation: bool = False
    requires_target: bool = False
    description: str


class CapabilityQuery(BaseModel):
    recipient_type: DcsRecipientType
    intent: str
    mission_bridge_available: bool = False
    target_available: bool = False


class CapabilityDecision(BaseModel):
    supported: bool
    capability_id: str | None = None
    channel: DcsCommandChannel | None = None
    dcs_command: str | None = None
    requires_confirmation: bool = False
    reason: str
    alternatives: list[str] = Field(default_factory=list)


CAPABILITIES: tuple[DcsCapability, ...] = (
    DcsCapability(
        capability_id="wingman-cover-me",
        recipient_types={DcsRecipientType.WINGMAN, DcsRecipientType.FLIGHT},
        intents={"cover_me", "command_cover"},
        channel=DcsCommandChannel.NATIVE_RADIO_MENU,
        dcs_command="Cover Me",
        description="Order a wingman or the flight to cover the player aircraft.",
    ),
    DcsCapability(
        capability_id="wingman-engage-my-target",
        recipient_types={DcsRecipientType.WINGMAN, DcsRecipientType.FLIGHT},
        intents={"engage_my_target", "attack_my_target"},
        channel=DcsCommandChannel.NATIVE_RADIO_MENU,
        dcs_command="Engage My Target",
        requires_target=True,
        description="Order a wingman or the flight to engage the player's designated target.",
    ),
    DcsCapability(
        capability_id="flight-engage-air",
        recipient_types={DcsRecipientType.WINGMAN, DcsRecipientType.FLIGHT},
        intents={"engage_air_targets", "attack_air_targets"},
        channel=DcsCommandChannel.NATIVE_RADIO_MENU,
        dcs_command="Engage Bandits",
        description="Order a wingman or the flight to engage airborne threats.",
    ),
    DcsCapability(
        capability_id="flight-engage-ground",
        recipient_types={DcsRecipientType.WINGMAN, DcsRecipientType.FLIGHT},
        intents={"engage_ground_targets", "attack_ground_targets"},
        channel=DcsCommandChannel.NATIVE_RADIO_MENU,
        dcs_command="Engage Ground Targets",
        description="Order a wingman or the flight to engage suitable ground targets.",
    ),
    DcsCapability(
        capability_id="flight-rejoin",
        recipient_types={DcsRecipientType.WINGMAN, DcsRecipientType.FLIGHT},
        intents={"rejoin", "return_to_formation"},
        channel=DcsCommandChannel.NATIVE_RADIO_MENU,
        dcs_command="Rejoin Formation",
        description="Order a wingman or the flight to return to formation.",
    ),
    DcsCapability(
        capability_id="flight-return-base",
        recipient_types={DcsRecipientType.WINGMAN, DcsRecipientType.FLIGHT},
        intents={"return_to_base", "rtb"},
        channel=DcsCommandChannel.NATIVE_RADIO_MENU,
        dcs_command="Return to Base",
        requires_confirmation=True,
        description="Order a wingman or the flight to return to base.",
    ),
    DcsCapability(
        capability_id="coalition-attack-group",
        recipient_types={
            DcsRecipientType.COALITION_AIRCRAFT,
            DcsRecipientType.COALITION_HELICOPTER,
            DcsRecipientType.COALITION_GROUND,
            DcsRecipientType.COALITION_NAVAL,
        },
        intents={"attack_group", "attack_designated_group"},
        channel=DcsCommandChannel.MISSION_BRIDGE,
        dcs_command="AttackGroup",
        requires_confirmation=True,
        requires_target=True,
        description="Assign a coalition AI group to attack a specific mission group through Mission Bridge.",
    ),
    DcsCapability(
        capability_id="coalition-move-to-point",
        recipient_types={
            DcsRecipientType.COALITION_HELICOPTER,
            DcsRecipientType.COALITION_GROUND,
            DcsRecipientType.COALITION_NAVAL,
        },
        intents={"move_to_point", "hold_position", "change_route"},
        channel=DcsCommandChannel.MISSION_BRIDGE,
        dcs_command="SetTask/SetRoute",
        requires_confirmation=True,
        description="Change a coalition group's route or position through Mission Bridge.",
    ),
    DcsCapability(
        capability_id="jtac-mark-target",
        recipient_types={DcsRecipientType.JTAC, DcsRecipientType.COALITION_GROUND},
        intents={"request_target_designation", "mark_with_smoke", "mark_with_laser"},
        channel=DcsCommandChannel.MISSION_BRIDGE,
        dcs_command="JTAC Mark Target",
        requires_target=True,
        description="Request laser or smoke target designation from a capable friendly unit.",
    ),
    DcsCapability(
        capability_id="unit-radio-information",
        recipient_types=set(DcsRecipientType),
        intents={"find_unit_frequency", "request_frequency", "contact_unit"},
        channel=DcsCommandChannel.INFORMATION_ONLY,
        description="Return the callsign, frequency and modulation assigned to a coalition unit in the mission.",
    ),
)


class DcsCapabilityDatabase:
    def list(self) -> list[DcsCapability]:
        return [item.model_copy(deep=True) for item in CAPABILITIES]

    def decide(self, query: CapabilityQuery) -> CapabilityDecision:
        matches = [
            item
            for item in CAPABILITIES
            if query.recipient_type in item.recipient_types and query.intent in item.intents
        ]
        if not matches:
            alternatives = sorted(
                {
                    intent
                    for item in CAPABILITIES
                    if query.recipient_type in item.recipient_types
                    for intent in item.intents
                }
            )
            return CapabilityDecision(
                supported=False,
                reason="No matching DCS capability is registered for this recipient and intent",
                alternatives=alternatives,
            )

        capability = matches[0]
        if capability.channel is DcsCommandChannel.MISSION_BRIDGE and not query.mission_bridge_available:
            return CapabilityDecision(
                supported=False,
                capability_id=capability.capability_id,
                channel=capability.channel,
                dcs_command=capability.dcs_command,
                requires_confirmation=capability.requires_confirmation,
                reason="This command requires an active Mission Bridge",
            )
        if capability.requires_target and not query.target_available:
            return CapabilityDecision(
                supported=False,
                capability_id=capability.capability_id,
                channel=capability.channel,
                dcs_command=capability.dcs_command,
                requires_confirmation=capability.requires_confirmation,
                reason="This command requires a resolved target",
            )
        return CapabilityDecision(
            supported=True,
            capability_id=capability.capability_id,
            channel=capability.channel,
            dcs_command=capability.dcs_command,
            requires_confirmation=capability.requires_confirmation,
            reason="A compatible DCS action is available",
        )


dcs_capabilities = DcsCapabilityDatabase()
