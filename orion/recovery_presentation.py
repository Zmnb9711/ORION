from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel

from orion.recovery_launch import RecoveryLaunchState, RecoveryLaunchStatus, recovery_launch_status, start_dcs_for_recovery
from orion.startup_health import RecoveryAction, StartupHealthReport, inspect_startup_health


class RecoveryUiState(StrEnum):
    ACTION_REQUIRED = "action_required"
    STARTING = "starting"
    WAITING_FOR_TELEMETRY = "waiting_for_telemetry"
    READY = "ready"
    FAILED = "failed"


class RecoveryPresentation(BaseModel):
    state: RecoveryUiState
    title: str
    message: str
    primary_action: str | None = None
    primary_label: str | None = None
    launch: RecoveryLaunchStatus | None = None
    health: StartupHealthReport


def get_recovery_presentation(launch_id: UUID | None = None, language: str = "ru") -> RecoveryPresentation:
    health = inspect_startup_health()
    if launch_id is not None:
        launch = recovery_launch_status(launch_id)
        return _from_launch(launch, health, language)

    if health.telemetry_connected:
        return RecoveryPresentation(
            state=RecoveryUiState.READY,
            title=_t(language, "Готов к полёту", "Ready to fly"),
            message=_t(language, "ORION подключён к DCS", "ORION is connected to DCS"),
            health=health,
        )

    if RecoveryAction.START_DCS in health.recovery_actions:
        return RecoveryPresentation(
            state=RecoveryUiState.ACTION_REQUIRED,
            title=_t(language, "DCS не подключён", "DCS is not connected"),
            message=_t(language, "Запустите DCS и дождитесь подключения телеметрии", "Start DCS and wait for telemetry to connect"),
            primary_action="start_dcs",
            primary_label=_t(language, "Запустить DCS", "Start DCS"),
            health=health,
        )

    return RecoveryPresentation(
        state=RecoveryUiState.ACTION_REQUIRED,
        title=_t(language, "Требуется восстановление", "Recovery required"),
        message=_t(language, "Исправьте отмеченные проблемы запуска ORION", "Resolve the reported ORION startup issues"),
        health=health,
    )


def start_dcs_from_presentation(language: str = "ru") -> RecoveryPresentation:
    launch = start_dcs_for_recovery()
    health = inspect_startup_health()
    return _from_launch(launch, health, language)


def _from_launch(launch: RecoveryLaunchStatus, health: StartupHealthReport, language: str) -> RecoveryPresentation:
    if launch.state is RecoveryLaunchState.CONNECTED:
        return RecoveryPresentation(
            state=RecoveryUiState.READY,
            title=_t(language, "Готов к полёту", "Ready to fly"),
            message=_t(language, "DCS запущен, телеметрия подключена", "DCS is running and telemetry is connected"),
            launch=launch,
            health=health,
        )
    if launch.state is RecoveryLaunchState.WAITING_FOR_TELEMETRY:
        return RecoveryPresentation(
            state=RecoveryUiState.WAITING_FOR_TELEMETRY,
            title=_t(language, "Подключение к DCS", "Connecting to DCS"),
            message=_t(language, "DCS запущен. ORION ожидает телеметрию", "DCS is running. ORION is waiting for telemetry"),
            primary_action="refresh",
            primary_label=_t(language, "Проверить подключение", "Check connection"),
            launch=launch,
            health=health,
        )
    if launch.state is RecoveryLaunchState.STARTING:
        return RecoveryPresentation(
            state=RecoveryUiState.STARTING,
            title=_t(language, "Запуск DCS", "Starting DCS"),
            message=_t(language, "ORION запускает DCS", "ORION is starting DCS"),
            launch=launch,
            health=health,
        )
    if launch.state is RecoveryLaunchState.SELECTION_REQUIRED:
        return RecoveryPresentation(
            state=RecoveryUiState.ACTION_REQUIRED,
            title=_t(language, "Выберите профиль запуска", "Select a launch profile"),
            message=launch.message,
            primary_action="select_launch_profile",
            primary_label=_t(language, "Выбрать профиль", "Select profile"),
            launch=launch,
            health=health,
        )
    return RecoveryPresentation(
        state=RecoveryUiState.FAILED,
        title=_t(language, "Не удалось запустить DCS", "Failed to start DCS"),
        message=launch.message,
        primary_action="retry",
        primary_label=_t(language, "Повторить", "Retry"),
        launch=launch,
        health=health,
    )


def _t(language: str, ru: str, en: str) -> str:
    return ru if language.casefold().startswith("ru") else en
