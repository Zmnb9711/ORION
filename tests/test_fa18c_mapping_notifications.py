from orion.assistant_messages import AssistantMessageQueue, AssistantMessageState
from orion.fa18c_calibration_wizard import hornet_calibration_wizard
from orion.fa18c_mapping_notifications import HornetMappingNotifier


def setup_function() -> None:
    hornet_calibration_wizard.cancel()


def teardown_function() -> None:
    hornet_calibration_wizard.cancel()


def test_notifier_queues_spoken_next_step_instruction() -> None:
    queue = AssistantMessageQueue()
    notifier = HornetMappingNotifier(queue=queue, language="ru")
    session = hornet_calibration_wizard.start()
    session.current_step = 1

    notification = notifier.step_advanced(session, "tacan_power")
    queued = queue.list(state=AssistantMessageState.QUEUED)

    assert len(queued) == 1
    assert queued[0].speak is True
    assert queued[0].show_in_console is True
    assert queued[0].source == "fa18c-cockpit-mapping"
    assert queued[0].metadata["previous_step"] == "tacan_power"
    assert queued[0].metadata["next_step"] == "tacan_channel_tens"
    assert "Шаг подтверждён автоматически" in queued[0].text
    assert notification.correlation_id == queued[0].correlation_id


def test_notifier_is_idempotent_for_same_transition() -> None:
    queue = AssistantMessageQueue()
    notifier = HornetMappingNotifier(queue=queue, language="en")
    session = hornet_calibration_wizard.start()
    session.current_step = 1

    first = notifier.step_advanced(session, "tacan_power")
    second = notifier.step_advanced(session, "tacan_power")

    assert first.correlation_id == second.correlation_id
    assert len(queue.list()) == 1


def test_notifier_announces_mapping_completion() -> None:
    queue = AssistantMessageQueue()
    notifier = HornetMappingNotifier(queue=queue, language="ru")
    session = hornet_calibration_wizard.start()
    session.current_step = len(session.steps)

    notifier.step_advanced(session, "comm2_preset")
    queued = queue.list()

    assert len(queued) == 1
    assert queued[0].metadata["next_step"] == "complete"
    assert "завершена" in queued[0].text
    assert "живой проверке" in queued[0].text
