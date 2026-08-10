from __future__ import annotations

from collections.abc import Mapping

SUPPORTED_LANGUAGES = ("en", "ru")

_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "nav.home": "Home",
        "nav.fly": "Fly with ORION",
        "nav.mission": "Mission Studio",
        "nav.diagnostics": "Diagnostics",
        "nav.providers": "AI Providers",
        "nav.updates": "Updates",
        "nav.settings": "Settings",
        "nav.logs": "Logs",
        "nav.about": "About",
        "action.refresh": "Refresh",
        "action.launch_dcs": "Launch DCS",
        "action.run_setup": "Run DCS setup / repair",
        "action.check_updates": "Check for updates",
        "action.install_update": "Download and install",
        "status.checking": "Checking…",
        "status.ready": "Ready",
        "status.core_starting": "ORION Core starting…",
        "status.core_running": "ORION Core running",
        "settings.language": "Language",
        "settings.theme": "Theme",
        "settings.update_channel": "Update channel",
        "settings.start_windows": "Start ORION with Windows",
        "settings.minimize_tray": "Minimize to tray",
        "settings.saved": "Launcher settings saved.",
        "setup.title": "ORION DCS Setup",
        "setup.detect": "Detect DCS",
        "setup.install": "Install / repair integration",
        "setup.test": "Test telemetry",
        "setup.ready": "Ready to fly",
        "updates.current": "Current functionality",
        "updates.installed": "Installed version",
        "updates.notes": "Changes in this version",
        "diagnostics.title": "ORION Diagnostics",
        "diagnostics.created": "Diagnostic bundle created",
        "diagnostics.open_folder": "Open folder",
        "diagnostics.save_as": "Save as…",
        "diagnostics.close": "Close",
        "diagnostics.all_files": "All files",
        "diagnostics.saved": "Diagnostic bundle saved to:\n{path}",
    },
    "ru": {
        "nav.home": "Главная",
        "nav.fly": "Полет с ORION",
        "nav.mission": "Mission Studio",
        "nav.diagnostics": "Диагностика",
        "nav.providers": "AI-провайдеры",
        "nav.updates": "Обновления",
        "nav.settings": "Настройки",
        "nav.logs": "Журнал",
        "nav.about": "О программе",
        "action.refresh": "Обновить",
        "action.launch_dcs": "Запустить DCS",
        "action.run_setup": "Настроить / восстановить DCS",
        "action.check_updates": "Проверить обновления",
        "action.install_update": "Скачать и установить",
        "status.checking": "Проверка…",
        "status.ready": "Готово",
        "status.core_starting": "ORION Core запускается…",
        "status.core_running": "ORION Core работает",
        "settings.language": "Язык",
        "settings.theme": "Тема",
        "settings.update_channel": "Канал обновлений",
        "settings.start_windows": "Запускать ORION вместе с Windows",
        "settings.minimize_tray": "Сворачивать в системный трей",
        "settings.saved": "Настройки лаунчера сохранены.",
        "setup.title": "Настройка ORION для DCS",
        "setup.detect": "Найти DCS",
        "setup.install": "Установить / восстановить интеграцию",
        "setup.test": "Проверить телеметрию",
        "setup.ready": "Готово к полету",
        "updates.current": "Функциональность текущей версии",
        "updates.installed": "Установленная версия",
        "updates.notes": "Изменения в этой версии",
        "diagnostics.title": "Диагностика ORION",
        "diagnostics.created": "Диагностический пакет создан",
        "diagnostics.open_folder": "Открыть папку",
        "diagnostics.save_as": "Сохранить как…",
        "diagnostics.close": "Закрыть",
        "diagnostics.all_files": "Все файлы",
        "diagnostics.saved": "Диагностический пакет сохранён:\n{path}",
    },
}


def normalize_language(language: str | None) -> str:
    value = (language or "en").lower().replace("_", "-")
    if value.startswith("ru"):
        return "ru"
    return "en"


def translate(key: str, language: str = "en", values: Mapping[str, object] | None = None) -> str:
    lang = normalize_language(language)
    text = _MESSAGES.get(lang, _MESSAGES["en"]).get(key)
    if text is None:
        text = _MESSAGES["en"].get(key, key)
    if values:
        return text.format(**values)
    return text
