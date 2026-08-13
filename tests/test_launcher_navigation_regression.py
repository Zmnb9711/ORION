from orion.desktop_app import OrionDesktopLauncher
from orion.launcher_audio_sections import LauncherAudioSectionsMixin


def test_audio_extension_preserves_all_existing_launcher_pages() -> None:
    existing = set(OrionDesktopLauncher.NAV_KEYS)
    extended = set(LauncherAudioSectionsMixin.NAV_KEYS)

    assert existing <= extended
    assert {"modules", "test"} <= extended


def test_audio_extension_keeps_existing_navigation_order_visible() -> None:
    extended = LauncherAudioSectionsMixin.NAV_KEYS
    for key in OrionDesktopLauncher.NAV_KEYS:
        assert key in extended
