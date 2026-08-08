from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from orion.first_run_actions import FirstRunAction
from orion.first_run_session import FirstRunSessionState, FirstRunSessionStep, get_first_run_session


class UiLanguage(StrEnum):
    EN = "en"
    RU = "ru"


class WizardButton(BaseModel):
    action: FirstRunAction
    label: str
    primary: bool = False


class WizardPresentation(BaseModel):
    language: UiLanguage
    step: FirstRunSessionStep
    progress_percent: int = Field(ge=0, le=100)
    title: str
    description: str
    status_text: str
    warning: str | None = None
    buttons: list[WizardButton] = Field(default_factory=list)
    session: FirstRunSessionState


_TEXT = {
    UiLanguage.EN: {
        FirstRunSessionStep.DETECT: (
            "Find DCS World",
            "Choose Steam, Standalone, Auto-detect, or provide the path manually.",
            "ORION needs to locate the DCS installation before setup can continue.",
        ),
        FirstRunSessionStep.SELECT_ACTIVE: (
            "Choose DCS installation",
            "Select the DCS installation that ORION should use.",
            "Multiple installations can coexist; only the selected one becomes active.",
        ),
        FirstRunSessionStep.INSTALL_INTEGRATION: (
            "Install DCS integration",
            "Connect ORION to DCS through Saved Games and Export.lua.",
            "The integration must be installed before live telemetry is available.",
        ),
        FirstRunSessionStep.TEST_CONNECTION: (
            "Test live connection",
            "Start DCS, enter an aircraft, and let ORION verify telemetry.",
            "Waiting for a live DCS telemetry handshake.",
        ),
        FirstRunSessionStep.READY: (
            "Ready to fly",
            "ORION is connected and ready for flight.",
            "Setup is complete.",
        ),
    },
    UiLanguage.RU: {
        FirstRunSessionStep.DETECT: (
            "Найти DCS World",
            "Выберите Steam, Standalone, автоопределение или укажите путь вручную.",
            "ORION должен найти установку DCS, прежде чем продолжить настройку.",
        ),
        FirstRunSessionStep.SELECT_ACTIVE: (
            "Выберите установку DCS",
            "Укажите установку DCS, которую должен использовать ORION.",
            "Можно иметь несколько установок; активной станет только выбранная.",
        ),
        FirstRunSessionStep.INSTALL_INTEGRATION: (
            "Установить интеграцию DCS",
            "Подключите ORION к DCS через Saved Games и Export.lua.",
            "Интеграция должна быть установлена до получения живой телеметрии.",
        ),
        FirstRunSessionStep.TEST_CONNECTION: (
            "Проверить соединение",
            "Запустите DCS, зайдите в любой поддерживаемый ЛА и позвольте ORION проверить телеметрию.",
            "Ожидается live telemetry handshake от DCS.",
        ),
        FirstRunSessionStep.READY: (
            "Готов к полёту",
            "ORION подключён и готов к работе.",
            "Первичная настройка завершена.",
        ),
    },
}

_BUTTON_LABELS = {
    UiLanguage.EN: {
        FirstRunAction.DETECT: "Detect",
        FirstRunAction.SELECT_ACTIVE: "Use this installation",
        FirstRunAction.INSTALL_INTEGRATION: "Install integration",
        FirstRunAction.TEST_CONNECTION: "Test connection",
    },
    UiLanguage.RU: {
        FirstRunAction.DETECT: "Найти",
        FirstRunAction.SELECT_ACTIVE: "Использовать эту установку",
        FirstRunAction.INSTALL_INTEGRATION: "Установить интеграцию",
        FirstRunAction.TEST_CONNECTION: "Проверить соединение",
    },
}


def get_first_run_presentation(language: UiLanguage = UiLanguage.EN) -> WizardPresentation:
    session = get_first_run_session()
    title, description, status_text = _TEXT[language][session.step]
    buttons: list[WizardButton] = []
    if session.next_action is not None:
        buttons.append(
            WizardButton(
                action=session.next_action,
                label=_BUTTON_LABELS[language][session.next_action],
                primary=True,
            )
        )

    warning = None
    if session.step == FirstRunSessionStep.SELECT_ACTIVE and len(session.candidates) > 1:
        warning = (
            "Несколько установок DCS найдено. Убедитесь, что выбрана нужная версия."
            if language == UiLanguage.RU
            else "Multiple DCS installations were found. Make sure you select the intended one."
        )

    return WizardPresentation(
        language=language,
        step=session.step,
        progress_percent=session.progress_percent,
        title=title,
        description=description,
        status_text=status_text,
        warning=warning,
        buttons=buttons,
        session=session,
    )
