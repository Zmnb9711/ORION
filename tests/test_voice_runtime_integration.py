from orion.voice_core import CommandPriority, CommandState, VoiceAgent, VoiceCommandCreate, VoiceCommandQueue


def test_submit_enriches_runtime_policy_context():
    queue = VoiceCommandQueue()
    command = queue.submit(
        VoiceCommandCreate(
            transcript="BRAA 040 for 20",
            intent="awacs_callout",
            agent=VoiceAgent.AWACS,
            priority=CommandPriority.HIGH,
        )
    )
    assert command.context["speech_lane"] == "radio"
    assert command.context["interrupt_policy"] == "lower_priority"
    assert command.context["ducking_policy"] == "non_radio"
    assert command.context["radio_effect"] is True


def test_high_priority_radio_preempts_running_normal_intercom():
    queue = VoiceCommandQueue()
    chat = queue.submit(
        VoiceCommandCreate(
            transcript="weather looks good",
            intent="chat",
            agent=VoiceAgent.GENERAL_CONVERSATION,
            priority=CommandPriority.NORMAL,
        )
    )
    queue.start(chat.command_id)

    urgent = queue.submit(
        VoiceCommandCreate(
            transcript="bandit hot",
            intent="awacs_callout",
            agent=VoiceAgent.AWACS,
            priority=CommandPriority.HIGH,
        )
    )
    interrupted = queue.get(chat.command_id)
    assert interrupted is not None
    assert interrupted.state is CommandState.CANCELLED
    assert "Preempted" in (interrupted.error or "")
    assert urgent.context["speech_lane"] == "radio"


def test_normal_command_cannot_overlap_running_command():
    queue = VoiceCommandQueue()
    first = queue.submit(
        VoiceCommandCreate(transcript="first", intent="chat", agent=VoiceAgent.GENERAL_CONVERSATION)
    )
    second = queue.submit(
        VoiceCommandCreate(transcript="second", intent="nav", agent=VoiceAgent.NAVIGATION)
    )
    queue.start(first.command_id)
    try:
        queue.start(second.command_id)
    except ValueError as exc:
        assert "already running" in str(exc)
    else:
        raise AssertionError("overlap should be blocked")


def test_critical_command_preempts_even_high_priority_running_command():
    queue = VoiceCommandQueue()
    high = queue.submit(
        VoiceCommandCreate(
            transcript="traffic",
            intent="traffic",
            agent=VoiceAgent.ATC,
            priority=CommandPriority.HIGH,
        )
    )
    queue.start(high.command_id)
    critical = queue.submit(
        VoiceCommandCreate(
            transcript="pull up",
            intent="terrain_warning",
            agent=VoiceAgent.THREAT_ANALYZER,
            priority=CommandPriority.CRITICAL,
        )
    )
    assert queue.get(high.command_id).state is CommandState.CANCELLED
    assert critical.context["ducking_policy"] == "all"
