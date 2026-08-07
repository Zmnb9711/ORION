from __future__ import annotations

from dataclasses import dataclass

from orion.fa18c_calibration_wizard import CalibrationSession, CalibrationStatus, hornet_calibration_wizard


@dataclass(frozen=True)
class CalibrationVoiceResult:
    completed: bool
    spoken_text: str
    data: dict[str, object]


def _instruction(session: CalibrationSession, language: str) -> str:
    step = session.active_step
    if step is None:
        return "Настройка распознавания кабины завершена." if language == "ru" else "Cockpit mapping setup complete."
    return step.instruction_ru if language == "ru" else step.instruction_en


def _language(transcript: str) -> str:
    return "ru" if any("а" <= char.casefold() <= "я" or char.casefold() == "ё" for char in transcript) else "en"


def execute_calibration_voice(intent: str, transcript: str) -> CalibrationVoiceResult:
    language = _language(transcript)
    try:
        if intent == "calibration_start":
            session = hornet_calibration_wizard.start()
            prefix = "Начинаю настройку распознавания кабины F/A-18C. " if language == "ru" else "Starting F/A-18C cockpit mapping setup. "
            return _result(session, prefix + _instruction(session, language))

        session = hornet_calibration_wizard.current()

        if intent == "calibration_status":
            return _result(session, _status_text(session, language))

        if intent == "calibration_repeat_instruction":
            return _result(session, _instruction(session, language))

        if intent == "calibration_retry":
            session = hornet_calibration_wizard.retry()
            prefix = "Повторяем этот шаг настройки. " if language == "ru" else "Retrying this mapping step. "
            return _result(session, prefix + _instruction(session, language))

        if intent == "calibration_confirm_step":
            session = hornet_calibration_wizard.evaluate_step()
            if session.status == CalibrationStatus.NEEDS_RETRY:
                text = "Шаг не подтверждён уверенно. Повторите действие. " if language == "ru" else "I could not confirm this step confidently. Repeat the action. "
                return _result(session, text + _instruction(session, language), completed=False)
            if session.status == CalibrationStatus.COMPLETE:
                text = "Настройка распознавания кабины завершена. Профиль сохранён и синхронизирован." if language == "ru" else "Cockpit mapping setup complete. The profile was saved and synchronized."
                return _result(session, text)
            text = "Шаг подтверждён. Следующий шаг. " if language == "ru" else "Step confirmed. Next step. "
            return _result(session, text + _instruction(session, language))

        return CalibrationVoiceResult(False, "Неизвестная команда настройки кабины." if language == "ru" else "Unknown cockpit mapping command.", {})
    except RuntimeError as exc:
        return CalibrationVoiceResult(False, str(exc), {"error": str(exc)})


def _status_text(session: CalibrationSession, language: str) -> str:
    if session.status == CalibrationStatus.COMPLETE:
        return "Настройка распознавания кабины завершена." if language == "ru" else "Cockpit mapping setup complete."
    step_number = min(session.current_step + 1, len(session.steps))
    prefix = f"Настройка распознавания кабины: шаг {step_number} из {len(session.steps)}. " if language == "ru" else f"Cockpit mapping setup: step {step_number} of {len(session.steps)}. "
    if session.status == CalibrationStatus.NEEDS_RETRY:
        prefix += "Требуется повтор. " if language == "ru" else "A retry is required. "
    return prefix + _instruction(session, language)


def _result(session: CalibrationSession, spoken_text: str, completed: bool = True) -> CalibrationVoiceResult:
    step = session.active_step
    return CalibrationVoiceResult(
        completed=completed,
        spoken_text=spoken_text,
        data={
            "session_id": session.session_id,
            "status": session.status.value,
            "current_step": session.current_step,
            "total_steps": len(session.steps),
            "active_step": step.key if step else None,
            "mapping_version": session.mapping_version,
            "value_profile_version": session.value_profile_version,
            "mapping_sync_sent": session.mapping_sync_sent,
        },
    )
