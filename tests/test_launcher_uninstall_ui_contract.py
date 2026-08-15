from orion.launcher_i18n import translate
from orion.launcher_shell import OrionLauncher
from orion.launcher_uninstall import LauncherUninstallMixin


def test_production_launcher_has_first_class_uninstall_navigation() -> None:
    assert "uninstall" in OrionLauncher.NAV_KEYS
    assert translate("nav.uninstall", "en") == "Uninstall"
    assert translate("nav.uninstall", "ru") == "Удаление"


def test_uninstall_page_and_dialog_are_part_of_production_mro() -> None:
    assert issubclass(OrionLauncher, LauncherUninstallMixin)
    assert callable(getattr(OrionLauncher, "_page_uninstall", None))
    assert callable(getattr(OrionLauncher, "_open_uninstall_components", None))
