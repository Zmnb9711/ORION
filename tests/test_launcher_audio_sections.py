from orion.launcher_audio_sections import LauncherAudioSectionsMixin


def test_launcher_audio_sections_use_approved_top_level_navigation() -> None:
    assert LauncherAudioSectionsMixin.NAV_KEYS == ("home", "modules", "test", "settings")


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
