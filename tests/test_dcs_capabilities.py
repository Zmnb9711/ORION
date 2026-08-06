from orion.dcs_capabilities import (
    CapabilityQuery,
    DcsCommandChannel,
    DcsRecipientType,
    dcs_capabilities,
)


def test_native_wingman_command_is_available_without_mission_bridge() -> None:
    decision = dcs_capabilities.decide(
        CapabilityQuery(recipient_type=DcsRecipientType.WINGMAN, intent="cover_me")
    )
    assert decision.supported is True
    assert decision.channel is DcsCommandChannel.NATIVE_RADIO_MENU
    assert decision.dcs_command == "Cover Me"


def test_extended_coalition_command_requires_mission_bridge() -> None:
    decision = dcs_capabilities.decide(
        CapabilityQuery(
            recipient_type=DcsRecipientType.COALITION_GROUND,
            intent="attack_group",
            target_available=True,
        )
    )
    assert decision.supported is False
    assert decision.channel is DcsCommandChannel.MISSION_BRIDGE


def test_extended_coalition_command_is_available_with_bridge_and_target() -> None:
    decision = dcs_capabilities.decide(
        CapabilityQuery(
            recipient_type=DcsRecipientType.COALITION_GROUND,
            intent="attack_group",
            mission_bridge_available=True,
            target_available=True,
        )
    )
    assert decision.supported is True
    assert decision.requires_confirmation is True


def test_frequency_lookup_is_information_only() -> None:
    decision = dcs_capabilities.decide(
        CapabilityQuery(
            recipient_type=DcsRecipientType.COALITION_AIRCRAFT,
            intent="find_unit_frequency",
        )
    )
    assert decision.supported is True
    assert decision.channel is DcsCommandChannel.INFORMATION_ONLY
