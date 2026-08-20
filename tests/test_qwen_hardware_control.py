from __future__ import annotations

import threading
import time
from pathlib import Path

from orion.controller_input import (
    ControllerBindingStore,
    ControllerDevice,
    ControllerDeviceIdentity,
    QwenControllerMonitor,
)
from orion.qwen_session_control import QwenSessionController


def _identity(name: str, guid: str) -> ControllerDeviceIdentity:
    return ControllerDeviceIdentity(
        backend="sdl2",
        device_type="joystick",
        guid=guid,
        name=name,
        axes=4,
        buttons=32,
        hats=1,
    )


class _Backend:
    def __init__(self, devices: list[ControllerDevice]) -> None:
        self.devices = devices
        self.states = {item.runtime_id: frozenset() for item in devices}
        self.closed = False

    def refresh(self) -> list[ControllerDevice]:
        return list(self.devices)

    def pressed_buttons(self, runtime_id: int) -> frozenset[int]:
        return self.states[runtime_id]

    def close(self) -> None:
        self.closed = True


def _wait(predicate, timeout: float = 1.0) -> None:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached")


def _monitor(tmp_path: Path, backend: _Backend, toggles: list[str]) -> QwenControllerMonitor:
    return QwenControllerMonitor(
        backend=backend,
        store=ControllerBindingStore(tmp_path),
        on_toggle=lambda: toggles.append("toggle"),
        poll_interval_s=0.005,
        refresh_interval_s=0.02,
        debounce_s=0.05,
    )


def test_device_enumeration_abstraction_and_missing_binding_are_safe(tmp_path: Path) -> None:
    device = ControllerDevice(_identity("Throttle", "guid-a"), runtime_id=11)
    backend = _Backend([device])
    monitor = _monitor(tmp_path, backend, [])
    monitor.start()
    _wait(lambda: monitor.devices() == [device])
    assert monitor.binding_availability() == (False, "UNASSIGNED")
    backend.devices = []
    monitor.refresh()
    _wait(lambda: monitor.devices() == [])
    backend.states = {}
    monitor.stop()
    assert backend.closed is True


def test_binding_round_trip_uses_device_identity_and_button(tmp_path: Path) -> None:
    store = ControllerBindingStore(tmp_path)
    identity = _identity("HOTAS", "guid-unique")
    from orion.controller_input import ControllerBinding

    binding = ControllerBinding(identity, "button", 26, "Button 27")
    store.save(binding)
    assert store.load() == binding
    raw = store.path.read_text(encoding="utf-8")
    assert "guid-unique" in raw
    assert '"index": 26' in raw
    store.clear()
    assert store.load() is None


def test_configured_missing_device_is_unavailable_without_rebinding(tmp_path: Path) -> None:
    store = ControllerBindingStore(tmp_path)
    from orion.controller_input import ControllerBinding

    binding = ControllerBinding(_identity("HOTAS", "guid-missing"), "button", 26, "Button 27")
    store.save(binding)
    backend = _Backend([])
    monitor = _monitor(tmp_path, backend, [])
    monitor.start()
    _wait(lambda: monitor.binding_availability() == (False, "DEVICE UNAVAILABLE"))
    assert monitor.binding == binding
    assert monitor.devices() == []
    monitor.stop()


def test_assignment_listens_only_to_selected_device_and_does_not_toggle(tmp_path: Path) -> None:
    selected = ControllerDevice(_identity("Stick", "guid-stick"), runtime_id=1)
    other = ControllerDevice(_identity("Throttle", "guid-throttle"), runtime_id=2)
    backend = _Backend([selected, other])
    toggles: list[str] = []
    captures = []
    monitor = _monitor(tmp_path, backend, toggles)
    monitor.start()
    _wait(lambda: len(monitor.devices()) == 2)
    assert monitor.begin_assignment(selected.identity.stable_key, lambda binding, error: captures.append((binding, error)))
    backend.states[2] = frozenset({26})
    time.sleep(0.03)
    assert captures == []
    backend.states[1] = frozenset({7})
    _wait(lambda: len(captures) == 1)
    assert captures[0][0].button_index == 7
    assert toggles == []
    time.sleep(0.03)
    assert toggles == []
    monitor.stop()


def test_bound_button_is_edge_based_and_release_does_not_toggle(tmp_path: Path) -> None:
    device = ControllerDevice(_identity("Throttle", "guid-a"), runtime_id=11)
    backend = _Backend([device])
    toggles: list[str] = []
    monitor = _monitor(tmp_path, backend, toggles)
    monitor.start()
    _wait(lambda: bool(monitor.devices()))
    captured = []
    monitor.begin_assignment(device.identity.stable_key, lambda binding, error: captured.append(binding))
    backend.states[11] = frozenset({3})
    _wait(lambda: bool(captured))
    time.sleep(0.03)
    assert toggles == []
    backend.states[11] = frozenset()
    time.sleep(0.02)
    assert toggles == []
    backend.states[11] = frozenset({3})
    _wait(lambda: len(toggles) == 1)
    time.sleep(0.03)
    assert toggles == ["toggle"]
    backend.states[11] = frozenset()
    time.sleep(0.02)
    assert toggles == ["toggle"]
    monitor.clear_binding()
    assert monitor.binding is None
    assert not ControllerBindingStore(tmp_path).path.exists()
    monitor.stop()


def test_different_device_same_button_and_rapid_double_input_do_not_collide(tmp_path: Path) -> None:
    one = ControllerDevice(_identity("One", "guid-one"), runtime_id=1)
    two = ControllerDevice(_identity("Two", "guid-two"), runtime_id=2)
    backend = _Backend([one, two])
    toggles: list[str] = []
    monitor = _monitor(tmp_path, backend, toggles)
    monitor.start()
    _wait(lambda: len(monitor.devices()) == 2)
    monitor.begin_assignment(one.identity.stable_key, lambda *_: None)
    backend.states[1] = frozenset({5})
    time.sleep(0.03)
    backend.states[1] = frozenset()
    time.sleep(0.02)
    backend.states[2] = frozenset({5})
    time.sleep(0.03)
    assert toggles == []
    backend.states[1] = frozenset({5})
    _wait(lambda: len(toggles) == 1)
    backend.states[1] = frozenset()
    time.sleep(0.01)
    backend.states[1] = frozenset({5})
    time.sleep(0.02)
    assert toggles == ["toggle"]
    monitor.stop()


def test_identical_sdl_devices_are_ambiguous_not_silently_resolved(tmp_path: Path) -> None:
    identity = _identity("Twin Throttle", "same-guid")
    devices = [
        ControllerDevice(identity, runtime_id=1, ambiguous=True),
        ControllerDevice(identity, runtime_id=2, ambiguous=True),
    ]
    backend = _Backend(devices)
    monitor = _monitor(tmp_path, backend, [])
    monitor.start()
    _wait(lambda: len(monitor.devices()) == 2)
    errors = []
    assert not monitor.begin_assignment(identity.stable_key, lambda binding, error: errors.append(error))
    assert errors == ["Selected controller is unavailable or ambiguous"]
    monitor.stop()


class _Core:
    def __init__(self) -> None:
        self.state = "stopped"
        self.calls: list[tuple[str, str]] = []

    def request(self, path: str, *, method: str = "GET", payload=None):  # noqa: ANN001, ANN202
        self.calls.append((method, path))
        if path.endswith("/start"):
            assert payload is not None
            assert payload["api_key"] == "secret"
            self.state = "starting"
        elif path.endswith("/stop"):
            self.state = "stopped"
        return {"state": self.state, "message": self.state}


def _payload() -> dict[str, object]:
    return {"api_key": "secret"}


def test_hardware_toggle_directly_starts_and_stops_same_core_service() -> None:
    core = _Core()
    control = QwenSessionController(core.request)
    first = control.toggle(_payload)
    assert first.executed and first.action == "start"
    assert ("POST", "/v1/realtime/qwen/live/start") in core.calls
    core.state = "streaming"
    second = control.toggle(_payload)
    assert second.executed and second.action == "stop"
    assert core.state == "stopped"


def test_launcher_start_and_hardware_stop_share_one_lifecycle() -> None:
    core = _Core()
    control = QwenSessionController(core.request)
    assert control.request_start(_payload).executed
    core.state = "connected"
    assert control.toggle(_payload).action == "stop"
    assert [path for method, path in core.calls if method == "POST"] == [
        "/v1/realtime/qwen/live/start",
        "/v1/realtime/qwen/live/stop",
    ]


def test_hardware_start_and_launcher_stop_share_one_lifecycle() -> None:
    core = _Core()
    control = QwenSessionController(core.request)
    assert control.toggle(_payload).action == "start"
    core.state = "streaming"
    assert control.request_stop().action == "stop"
    assert [path for method, path in core.calls if method == "POST"] == [
        "/v1/realtime/qwen/live/start",
        "/v1/realtime/qwen/live/stop",
    ]


def test_overlapping_control_command_is_ignored() -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingCore(_Core):
        def request(self, path: str, *, method: str = "GET", payload=None):  # noqa: ANN001, ANN202
            if path.endswith("/start"):
                entered.set()
                release.wait(1)
            return super().request(path, method=method, payload=payload)

    core = BlockingCore()
    control = QwenSessionController(core.request)
    thread = threading.Thread(target=lambda: control.request_start(_payload))
    thread.start()
    assert entered.wait(1)
    ignored = control.toggle(_payload)
    assert not ignored.executed
    assert ignored.ignored_reason == "transition_in_progress"
    release.set()
    thread.join(1)
