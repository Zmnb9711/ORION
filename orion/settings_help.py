from __future__ import annotations

from pydantic import BaseModel

from orion.orion_settings import CommunicationMode


class CommunicationModeHelp(BaseModel):
    mode: CommunicationMode
    title: str
    description: str


class MissionPackHelp(BaseModel):
    title: str
    summary: str
    workflow: list[str]
    benefits: list[str]
    safety_notice: str


class SettingsHelpCatalog(BaseModel):
    communication_modes: list[CommunicationModeHelp]
    mission_pack: MissionPackHelp


SETTINGS_HELP = SettingsHelpCatalog(
    communication_modes=[
        CommunicationModeHelp(
            mode=CommunicationMode.AVIATION_ENGLISH,
            title="Авиационный английский",
            description=(
                "Общение на английском языке с использованием авиационной "
                "фразеологии. Свободные команды распознаются, но рабочие ответы "
                "формируются в профессиональном радиообменном стиле."
            ),
        ),
        CommunicationModeHelp(
            mode=CommunicationMode.AVIATION_RUSSIAN,
            title="Авиационный русский",
            description=(
                "Общение на русском языке с использованием русской авиационной "
                "терминологии и фразеологии. Свободные команды распознаются, но "
                "рабочие ответы сохраняют профессиональный авиационный стиль."
            ),
        ),
        CommunicationModeHelp(
            mode=CommunicationMode.FREE_COMMUNICATION,
            title="Свободное общение",
            description=(
                "Общение естественным языком без обязательного соблюдения "
                "фразеологии. ORION самостоятельно определяет, когда требуется "
                "рабочий авиационный формат ответа."
            ),
        ),
    ],
    mission_pack=MissionPackHelp(
        title="Что такое Mission Pack?",
        summary=(
            "Mission Pack — компонент ORION, который подготавливает отдельную "
            "копию миссии DCS для работы расширенных функций ассистента."
        ),
        workflow=[
            "ORION проверяет выбранную миссию .miz.",
            "Создаёт отдельную подготовленную копию.",
            "Добавляет в копию служебные компоненты ORION.",
            "Запускает подготовленную копию вместо изменения оригинала.",
        ],
        benefits=[
            "взаимодействие ORION с объектами и событиями миссии",
            "доступ к дополнительным данным о ходе миссии",
            "поддержка расширенных команд Mission Control",
        ],
        safety_notice=(
            "Оригинальный файл миссии не изменяется. Все изменения выполняются "
            "только в автоматически созданной копии."
        ),
    ),
)
