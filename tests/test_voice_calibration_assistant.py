from __future__ import annotations

import pytest

from orion.fa18c_calibration_wizard import CalibrationStatus, hornet_calibration_wizard
from orion.voice_calibration_assistant import execute_calibration_voice
from orion.voice_understanding import parse_transcript


@pytest.fixture(autouse=True)
def reset_calibration() -> None:
    hornet_calibration_wizard.cancel()
    yield
    hornet_calibration_wizard.cancel()


def test_russian_start_is_recognized() -> None:
    command = parse_transcript("Начни калибровку").commands[0]
    assert command.intent == "calibration_start"
    assert command.context["parser"] == "rules-v8"


def test_english_status_is_recognized() -> None:
    command = parse_transcript("Calibration status").commands[0]
    assert command.intent == "calibration_status"


def test_start_speaks_first_instruction_in_russian() -> None:
    result = execute_calibration_voice("calibration_start", "Начни калибровку")
    assert result.completed is True
    assert result.data["status"] == CalibrationStatus.RUNNING.value
    assert result.data["active_step"] == "tacan_power"
    assert "TACAN OFF" in result.spoken_text


def test_repeat_instruction_uses_active_step() -> None:
    execute_calibration_voice("calibration_start", "Start calibration")
    result = execute_calibration_voice("calibration_repeat_instruction", "Repeat instruction")
    assert result.completed is True
    assert "TACAN OFF" in result.spoken_text


def test_status_reports_step_number() -> None:
    execute_calibration_voice("calibration_start", "Начни калибровку")
    result = execute_calibration_voice("calibration_status", "Статус калибровки")
    assert "Шаг 1 из 6" in result.spoken_text


def test_confirm_without_evidence_requests_retry() -> None:
    execute_calibration_voice("calibration_start", "Start calibration")
    result = execute_calibration_voice("calibration_confirm_step", "Step complete")
    assert result.completed is False
    assert result.data["status"] == CalibrationStatus.NEEDS_RETRY.value
    assert "Repeat" in result.spoken_text


def test_retry_returns_to_running() -> None:
    execute_calibration_voice("calibration_start", "Start calibration")
    execute_calibration_voice("calibration_confirm_step", "Step complete")
    result = execute_calibration_voice("calibration_retry", "Retry calibration step")
    assert result.completed is True
    assert result.data["status"] == CalibrationStatus.RUNNING.value
