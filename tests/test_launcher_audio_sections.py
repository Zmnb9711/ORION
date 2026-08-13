from orion.desktop_app import OrionDesktopLauncher
from orion.launcher_audio_sections import LauncherAudioSectionsMixin


def test_launcher_audio_sections_extend_existing_navigation_without_hiding_pages() -> None:
    existing = tuple(OrionDesktopLauncher.NAV_KEYS)
    extended = tuple(LauncherAudioSectionsMixin.NAV_KEYS)

    for key in existing:
        assert key in extended

    assert "modules" in extended
    assert "test" in extended
    assert extended.index("home") == 0
    assert extended.index("settings") < extended.index("logs")


def test_audio_device_display_map_keeps_windows_default_and_stable_ids() -> None:
    mapping = LauncherAudioSectionsMixin._device_display_map(
        [
            {"device_id": "SWD\\MMDEVAPI\\{0.0.1.00000000}.{mic-id}", "name": "Dream Air Microphone"},
            {"device_id": "SWD\\MMDEVAPI\\{0.0.1.00000000}.{usb-id}", "name": "USB Microphone"},
        ],
        "Windows Default",
    )
    assert mapping["Windows Default"] == "default"
    assert "SWD\\MMDEVAPI\\{0.0.1.00000000}.{mic-id}" in mapping.values()
    assert "SWD\\MMDEVAPI\\{0.0.1.00000000}.{usb-id}" in mapping.values()


def test_selection_text_reports_core_resolution() -> None:
    assert LauncherAudioSectionsMixin._selection_text("mic", {"device_id": "mic", "name": "Microphone"}).startswith("PASS")
    assert LauncherAudioSectionsMixin._selection_text("missing", None).startswith("FAIL")
    assert LauncherAudioSectionsMixin._selection_text("default", None).startswith("WARNING")
