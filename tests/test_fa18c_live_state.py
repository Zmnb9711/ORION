from orion.fa18c_live_state import advise_hornet_live_state


def test_tacan_advice_uses_current_and_mission_state() -> None:
    result = advise_hornet_live_state("Как настроить TACAN?", {"cockpit_state": {"tacan_enabled": False, "tacan_channel": 1, "mission_tacan_channel": 31, "mission_tacan_band": "X"}})
    assert result is not None
    assert result.topic == "tacan"
    assert "выключен" in result.spoken_text
    assert "31 X" in result.spoken_text
    assert result.next_actions[0] == "включи TACAN"


def test_comm1_advice_compares_live_frequency_with_requested_value() -> None:
    result = advise_hornet_live_state("Что с COMM1?", {"cockpit_state": {"comm1_preset": 1, "comm1_frequency": 305.0, "requested_comm1_preset": 4, "requested_comm1_frequency": 251.0}})
    assert result is not None
    assert result.topic == "comm1"
    assert "preset 4" in result.spoken_text
    assert "251.0" in result.spoken_text


def test_live_advisor_does_not_invent_state_when_context_missing() -> None:
    assert advise_hornet_live_state("Как настроить TACAN?", {}) is None
