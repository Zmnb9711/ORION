from orion.voice_core import CommandPriority, VoiceAgent, VoiceCommand
from orion.voice_policy import DuckingPolicy, InterruptPolicy, SpeechLane, resolve_voice_policy


def _command(agent: VoiceAgent, priority: CommandPriority) -> VoiceCommand:
    return VoiceCommand(
        transcript="test",
        intent="test",
        agent=agent,
        priority=priority,
    )


def test_awacs_uses_radio_lane_and_radio_effect():
    policy = resolve_voice_policy(_command(VoiceAgent.AWACS, CommandPriority.NORMAL))
    assert policy.lane is SpeechLane.RADIO
    assert policy.radio_effect is True
    assert policy.interrupt is InterruptPolicy.NEVER


def test_mission_control_uses_intercom_lane():
    policy = resolve_voice_policy(_command(VoiceAgent.MISSION_CONTROL, CommandPriority.NORMAL))
    assert policy.lane is SpeechLane.INTERCOM
    assert policy.radio_effect is False


def test_high_priority_radio_interrupts_lower_priority_and_ducks_non_radio():
    policy = resolve_voice_policy(_command(VoiceAgent.ATC, CommandPriority.HIGH))
    assert policy.interrupt is InterruptPolicy.LOWER_PRIORITY
    assert policy.ducking is DuckingPolicy.NON_RADIO


def test_critical_command_always_interrupts_and_ducks_all():
    policy = resolve_voice_policy(_command(VoiceAgent.THREAT_ANALYZER, CommandPriority.CRITICAL))
    assert policy.interrupt is InterruptPolicy.ALWAYS
    assert policy.ducking is DuckingPolicy.ALL


def test_system_agent_uses_system_lane():
    policy = resolve_voice_policy(_command(VoiceAgent.SYSTEM, CommandPriority.NORMAL))
    assert policy.lane is SpeechLane.SYSTEM
