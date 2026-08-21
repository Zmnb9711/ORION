from typing import Any, cast

from orion.controller_input import ControllerBinding, ControllerDevice, ControllerDeviceIdentity
from orion.desktop_app import OrionDesktopLauncher
from orion.launcher_audio_sections import LauncherAudioSectionsMixin
from orion.launcher_cloud_voice_sections import (
    LauncherCloudVoiceSectionsMixin,
    QwenControlsViewLifecycle,
)


class _FakeTkRoot:
    def __init__(self) -> None:
        self.pending = {}
        self.cancelled: list[str] = []
        self._sequence = 0

    def after(self, _delay: int, callback):  # noqa: ANN001, ANN202
        self._sequence += 1
        callback_id = f"after#{self._sequence}"
        self.pending[callback_id] = callback
        return callback_id

    def after_cancel(self, callback_id: str) -> None:
        self.cancelled.append(callback_id)
        self.pending.pop(callback_id, None)

    def run_next(self) -> None:
        callback_id = next(iter(self.pending))
        callback = self.pending.pop(callback_id)
        callback()

    def run_all(self, limit: int = 20) -> None:
        for _ in range(limit):
            if not self.pending:
                return
            self.run_next()
        raise AssertionError("callback loop did not become idle")


class _FakeOwner:
    def __init__(self) -> None:
        self.exists = True

    def winfo_exists(self) -> bool:
        return self.exists


class _FakeVariable:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


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


def test_audio_device_display_map_disambiguates_host_api_without_index_noise() -> None:
    mapping = LauncherAudioSectionsMixin._device_display_map(
        [
            {
                "device_id": "sounddevice:portaudio:input:0:1",
                "name": "Microphone (Pimax Dream Air)",
                "host_api_name": "MME",
                "device_index": 1,
            },
            {
                "device_id": "sounddevice:portaudio:input:1:8",
                "name": "Microphone (Pimax Dream Air)",
                "host_api_name": "Windows WASAPI",
                "device_index": 8,
            },
        ],
        "Windows Default",
    )

    assert "Microphone (Pimax Dream Air) — MME" in mapping
    assert "Microphone (Pimax Dream Air) — Windows WASAPI" in mapping


def test_selection_text_reports_core_resolution() -> None:
    assert LauncherAudioSectionsMixin._selection_text("mic", {"device_id": "mic", "name": "Microphone"}).startswith("PASS")
    assert LauncherAudioSectionsMixin._selection_text("missing", None).startswith("FAIL")
    assert LauncherAudioSectionsMixin._selection_text("default", None).startswith("WARNING")


def test_qwen_voice_layer_cannot_shadow_canonical_audio_core_json_helper() -> None:
    # Build #317 audio settings depend on LauncherAudioSectionsMixin._core_json
    # accepting JSON arrays for WASAPI input/output discovery. Qwen Live must use
    # a separately named helper so its stricter realtime response validation can
    # never intercept those requests through Python MRO.
    assert "_core_json" not in LauncherCloudVoiceSectionsMixin.__dict__
    assert "_realtime_core_json" in LauncherCloudVoiceSectionsMixin.__dict__

    class CombinedLauncher(LauncherCloudVoiceSectionsMixin, LauncherAudioSectionsMixin):
        pass

    assert CombinedLauncher._core_json is LauncherAudioSectionsMixin._core_json


def test_qwen_api_key_survives_settings_page_rebuild_inside_launcher_session(monkeypatch) -> None:
    launcher = object.__new__(LauncherCloudVoiceSectionsMixin)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "env-key")

    assert launcher._current_qwen_api_key() == "env-key"

    launcher._remember_qwen_api_key("  live-session-key  ")
    assert launcher._current_qwen_api_key() == "live-session-key"

    # Rebuilding/navigating away from Settings must not fall back to the
    # environment key once the user has edited the secret in this Launcher.
    launcher._remember_qwen_api_key("next-key")
    assert launcher._current_qwen_api_key() == "next-key"


def test_qwen_view_teardown_cancels_refresh_and_dead_owner_cannot_reschedule() -> None:
    root = _FakeTkRoot()
    owner = _FakeOwner()
    lifecycle = QwenControlsViewLifecycle(root)
    generation = lifecycle.activate(owner)
    calls: list[str] = []

    def refresh() -> None:
        calls.append("refresh")
        lifecycle.schedule(750, refresh, generation)

    lifecycle.schedule(0, refresh, generation)
    root.run_next()
    assert calls == ["refresh"]
    assert lifecycle.pending_count == 1

    owner.exists = False
    lifecycle.deactivate()
    root.run_all()

    assert calls == ["refresh"]
    assert lifecycle.pending_count == 0
    assert root.pending == {}


def test_launcher_clear_tears_down_qwen_view_before_destroying_page_widgets() -> None:
    events: list[str] = []

    class Base:
        def _clear(self) -> None:
            events.append("destroy_widgets")

    class Launcher(LauncherCloudVoiceSectionsMixin, Base):
        pass

    root = _FakeTkRoot()
    owner = _FakeOwner()
    launcher = cast(Any, object.__new__(Launcher))
    launcher._qwen_view_lifecycle = QwenControlsViewLifecycle(root)
    generation = launcher._qwen_view_lifecycle.activate(owner)
    launcher._qwen_view_generation = generation
    launcher._qwen_control_devices = {}
    launcher._qwen_view_lifecycle.schedule(750, lambda: events.append("stale_refresh"), generation)

    launcher._clear()
    owner.exists = False
    root.run_all()

    assert events == ["destroy_widgets"]
    assert launcher._qwen_view_lifecycle.pending_count == 0


def test_repeated_settings_modules_navigation_has_exactly_one_qwen_refresh_loop() -> None:
    root = _FakeTkRoot()
    lifecycle = QwenControlsViewLifecycle(root)
    refreshes: list[int] = []

    for _ in range(5):
        owner = _FakeOwner()
        generation = lifecycle.activate(owner)

        def refresh(token: int = generation) -> None:
            refreshes.append(token)
            lifecycle.schedule(750, lambda: refresh(token), token)

        lifecycle.schedule(0, refresh, generation)
        root.run_next()
        assert lifecycle.pending_count == 1
        assert len(root.pending) == 1

        # Navigating to Modules invalidates the owner before Tk destroys it.
        lifecycle.deactivate()
        owner.exists = False
        root.run_all()
        assert lifecycle.pending_count == 0
        assert root.pending == {}

    assert len(refreshes) == 5


def test_binding_and_selected_device_diagnostics_update_immediately() -> None:
    identity = ControllerDeviceIdentity(
        backend="sdl2",
        device_type="joystick",
        guid="guid-throttle",
        name="VPC Throttle",
        axes=4,
        buttons=32,
        hats=1,
    )
    device = ControllerDevice(identity=identity, runtime_id=7)
    binding = ControllerBinding(identity, "button", 26, "Button 27")

    class Monitor:
        @property
        def binding(self) -> ControllerBinding:
            return binding

        @staticmethod
        def binding_availability() -> tuple[bool, str]:
            return True, "READY"

        @staticmethod
        def diagnostic_status() -> dict[str, object]:
            return {
                "initialized": True,
                "device_count": 1,
                "error": None,
            }

    launcher = cast(Any, object.__new__(LauncherCloudVoiceSectionsMixin))
    launcher._qwen_controller_monitor = Monitor()
    launcher._qwen_control_binding_var = _FakeVariable()
    launcher._qwen_control_diagnostic_var = _FakeVariable()
    launcher._qwen_control_device_var = _FakeVariable(device.display_name)
    launcher._qwen_control_devices = {device.display_name: device}

    launcher._refresh_qwen_control_status()

    assert launcher._qwen_control_binding_var.get() == "VPC Throttle — Button 27 — READY"
    assert "SDL READY — 1 device(s) visible" in launcher._qwen_control_diagnostic_var.get()
    assert "(resolved)" in launcher._qwen_control_diagnostic_var.get()


def test_assignment_race_reports_selected_device_unavailable() -> None:
    identity = ControllerDeviceIdentity(
        backend="sdl2",
        device_type="joystick",
        guid="guid-stick",
        name="VPC Stick",
        axes=4,
        buttons=32,
        hats=1,
    )
    device = ControllerDevice(identity=identity, runtime_id=7)

    class Monitor:
        @staticmethod
        def begin_assignment(_stable_key: str, _callback: Any) -> bool:
            return False

    class Button:
        @staticmethod
        def cget(_name: str) -> str:
            return "ASSIGN / CHANGE"

    launcher = cast(Any, object.__new__(LauncherCloudVoiceSectionsMixin))
    launcher._qwen_controller_monitor = Monitor()
    launcher._qwen_view_generation = 1
    launcher._qwen_control_device_var = _FakeVariable(device.display_name)
    launcher._qwen_control_binding_var = _FakeVariable()
    launcher._qwen_control_devices = {device.display_name: device}

    launcher._assign_qwen_control(Button())

    assert launcher._qwen_control_binding_var.get() == (
        "Selected controller is no longer available; press Refresh"
    )
