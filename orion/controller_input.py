from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(slots=True, frozen=True)
class ControllerDeviceIdentity:
    backend: str
    device_type: str
    guid: str
    name: str
    axes: int
    buttons: int
    hats: int

    @property
    def stable_key(self) -> str:
        payload = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return payload


@dataclass(slots=True, frozen=True)
class ControllerDevice:
    identity: ControllerDeviceIdentity
    runtime_id: int
    ambiguous: bool = False

    @property
    def assignable(self) -> bool:
        return not self.ambiguous and self.identity.buttons > 0

    @property
    def display_name(self) -> str:
        suffix = self.identity.guid[-8:] if self.identity.guid else "unknown"
        warning = " — AMBIGUOUS" if self.ambiguous else ""
        return f"{self.identity.name} — SDL {suffix}{warning}"


@dataclass(slots=True, frozen=True)
class ControllerBinding:
    device: ControllerDeviceIdentity
    control_type: str
    button_index: int
    control_name: str

    @property
    def display_name(self) -> str:
        return f"{self.device.name} — {self.control_name}"


class ControllerBindingStore:
    def __init__(self, runtime_dir: Path) -> None:
        self.path = runtime_dir / "qwen-controller-binding.json"

    def load(self) -> ControllerBinding | None:
        if not self.path.is_file():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("version") != 1:
                return None
            device = ControllerDeviceIdentity(**payload["device"])
            control = payload["control"]
            if not isinstance(control, dict) or control.get("type") != "button":
                return None
            button_index = int(control["index"])
            if button_index < 0:
                return None
            return ControllerBinding(
                device=device,
                control_type="button",
                button_index=button_index,
                control_name=str(control.get("name") or f"Button {button_index + 1}"),
            )
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def save(self, binding: ControllerBinding) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "device": asdict(binding.device),
            "control": {
                "type": binding.control_type,
                "index": binding.button_index,
                "name": binding.control_name,
            },
        }
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            return


class ControllerBackend(Protocol):
    def pump(self) -> None: ...

    def refresh(self) -> list[ControllerDevice]: ...

    def pressed_buttons(self, runtime_id: int) -> frozenset[int]: ...

    def close(self) -> None: ...


class PygameJoystickBackend:
    """SDL joystick adapter for background, nonexclusive HOTAS button state."""

    def __init__(self) -> None:
        self._pygame: Any | None = None
        self._joysticks: dict[int, Any] = {}
        self._initialized = False
        self._last_error: str | None = None

    def _ensure_started(self) -> Any:
        if self._pygame is not None:
            return self._pygame
        os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        try:
            import pygame
        except ImportError as exc:
            self._last_error = "pygame/SDL controller support is not installed"
            raise RuntimeError("pygame/SDL controller support is not installed") from exc
        try:
            # pygame's event queue requires an initialized display owner even
            # when Tk owns the visible Launcher window.  A hidden 1x1 surface
            # gives the controller thread a valid event-pump lifecycle without
            # taking focus or consuming the HOTAS input from DCS.
            pygame.display.init()
            if pygame.display.get_surface() is None:
                pygame.display.set_mode((1, 1), flags=pygame.HIDDEN)
            pygame.joystick.init()
        except pygame.error as exc:
            self._last_error = f"SDL initialization failed: {exc}"
            raise RuntimeError(self._last_error) from exc
        self._pygame = pygame
        self._initialized = True
        self._last_error = None
        return pygame

    def pump(self) -> None:
        pygame = self._ensure_started()
        try:
            pygame.event.pump()
        except pygame.error as exc:
            self._last_error = f"SDL event pump failed: {exc}"
            raise RuntimeError(self._last_error) from exc
        self._last_error = None

    def refresh(self) -> list[ControllerDevice]:
        pygame = self._ensure_started()
        self.pump()
        found: list[ControllerDevice] = []
        joysticks: dict[int, Any] = {}
        for index in range(pygame.joystick.get_count()):
            joystick = pygame.joystick.Joystick(index)
            if not joystick.get_init():
                joystick.init()
            runtime_id = int(joystick.get_instance_id())
            identity = ControllerDeviceIdentity(
                backend="sdl2",
                device_type="joystick",
                guid=str(joystick.get_guid()).casefold(),
                name=str(joystick.get_name()).strip() or "Unnamed controller",
                axes=int(joystick.get_numaxes()),
                buttons=int(joystick.get_numbuttons()),
                hats=int(joystick.get_numhats()),
            )
            joysticks[runtime_id] = joystick
            found.append(ControllerDevice(identity=identity, runtime_id=runtime_id))
        counts: dict[str, int] = {}
        for item in found:
            counts[item.identity.stable_key] = counts.get(item.identity.stable_key, 0) + 1
        self._joysticks = joysticks
        return [
            ControllerDevice(
                identity=item.identity,
                runtime_id=item.runtime_id,
                ambiguous=counts[item.identity.stable_key] > 1,
            )
            for item in found
        ]

    def pressed_buttons(self, runtime_id: int) -> frozenset[int]:
        joystick = self._joysticks.get(runtime_id)
        pygame = self._pygame
        if joystick is None or pygame is None:
            raise OSError("Controller is unavailable")
        try:
            return frozenset(
                index for index in range(int(joystick.get_numbuttons())) if joystick.get_button(index)
            )
        except pygame.error as exc:
            raise OSError("Controller disconnected while reading buttons") from exc

    def close(self) -> None:
        pygame = self._pygame
        joysticks = list(self._joysticks.values())
        self._joysticks.clear()
        self._pygame = None
        self._initialized = False
        if pygame is not None:
            for joystick in joysticks:
                joystick.quit()
            pygame.joystick.quit()
            pygame.display.quit()

    def diagnostic_status(self) -> dict[str, object]:
        return {
            "backend": "pygame/SDL2",
            "initialized": self._initialized,
            "device_count": len(self._joysticks),
            "error": self._last_error,
        }


@dataclass(slots=True, frozen=True)
class ControlDiagnosticEvent:
    event: str
    timestamp: float
    details: dict[str, object]


class BoundedControlDiagnostics:
    def __init__(self, max_events: int = 500) -> None:
        self._events: deque[ControlDiagnosticEvent] = deque(maxlen=max_events)
        self._lock = threading.RLock()

    def record(self, event: str, **details: object) -> None:
        with self._lock:
            self._events.append(ControlDiagnosticEvent(event, time.time(), dict(details)))

    def snapshot(self) -> list[ControlDiagnosticEvent]:
        with self._lock:
            return list(self._events)


AssignmentCallback = Callable[[ControllerBinding | None, str | None], None]
ToggleCallback = Callable[[], None]


class QwenControllerMonitor:
    """Edge-triggered controller binding monitor shared by assignment/runtime."""

    def __init__(
        self,
        *,
        backend: ControllerBackend,
        store: ControllerBindingStore,
        on_toggle: ToggleCallback,
        diagnostics: BoundedControlDiagnostics | None = None,
        poll_interval_s: float = 0.05,
        refresh_interval_s: float = 1.0,
        debounce_s: float = 0.35,
    ) -> None:
        self.backend = backend
        self.store = store
        self.on_toggle = on_toggle
        self.diagnostics = diagnostics or BoundedControlDiagnostics()
        self.poll_interval_s = poll_interval_s
        self.refresh_interval_s = refresh_interval_s
        self.debounce_s = debounce_s
        self._binding = store.load()
        self._devices: list[ControllerDevice] = []
        self._previous: dict[int, frozenset[int]] = {}
        self._assignment: tuple[str, AssignmentCallback] | None = None
        self._suppressed_until_release: tuple[str, int] | None = None
        self._last_toggle_at = 0.0
        self._availability: str | None = None
        self._backend_state: tuple[object, ...] | None = None
        self._pump_error: str | None = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._refresh = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def binding(self) -> ControllerBinding | None:
        with self._lock:
            return self._binding

    def devices(self) -> list[ControllerDevice]:
        with self._lock:
            return list(self._devices)

    def diagnostic_status(self) -> dict[str, object]:
        status_getter = getattr(self.backend, "diagnostic_status", None)
        raw_value = status_getter() if callable(status_getter) else {}
        raw: dict[str, object] = raw_value if isinstance(raw_value, dict) else {}
        devices = self.devices()
        return {
            "backend": str(raw.get("backend", "controller")),
            "initialized": bool(raw.get("initialized", True)),
            "device_count": len(devices),
            "error": raw.get("error"),
            "devices": [
                {
                    "name": item.identity.name,
                    "guid": item.identity.guid,
                    "buttons": item.identity.buttons,
                    "runtime_id": item.runtime_id,
                    "ambiguous": item.ambiguous,
                }
                for item in devices
            ],
        }

    def binding_availability(self) -> tuple[bool, str]:
        binding = self.binding
        if binding is None:
            return False, "UNASSIGNED"
        matches = [item for item in self.devices() if item.identity.stable_key == binding.device.stable_key]
        if not matches:
            return False, "DEVICE UNAVAILABLE"
        if len(matches) != 1 or matches[0].ambiguous:
            return False, "DEVICE AMBIGUOUS"
        return True, "READY"

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="orion-qwen-controller", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self.backend.close()

    def refresh(self) -> None:
        self._refresh.set()

    def begin_assignment(self, stable_key: str, callback: AssignmentCallback) -> bool:
        matches = [item for item in self.devices() if item.identity.stable_key == stable_key]
        if len(matches) != 1 or not matches[0].assignable:
            callback(None, "Selected controller is unavailable or ambiguous")
            return False
        with self._lock:
            self._assignment = (stable_key, callback)
        self.diagnostics.record(
            "assignment_started",
            device=matches[0].identity.name,
            guid=matches[0].identity.guid,
            buttons=matches[0].identity.buttons,
            resolved=True,
        )
        return True

    def cancel_assignment(self, *, notify: bool = True, reason: str = "Assignment cancelled") -> None:
        with self._lock:
            assignment = self._assignment
            self._assignment = None
        if assignment is not None:
            self.diagnostics.record("assignment_cancelled", reason=reason)
            if notify:
                assignment[1](None, reason)

    def clear_binding(self) -> None:
        with self._lock:
            self._binding = None
            self._suppressed_until_release = None
        self.store.clear()
        self.diagnostics.record("binding_cleared")

    def _refresh_devices(self) -> None:
        error: str | None = None
        try:
            devices = self.backend.refresh()
        except (OSError, RuntimeError) as exc:
            devices = []
            error = str(exc)
        lost_assignment: tuple[str, AssignmentCallback] | None = None
        with self._lock:
            self._devices = devices
            runtime_ids = {item.runtime_id for item in devices}
            self._previous = {
                runtime_id: pressed for runtime_id, pressed in self._previous.items() if runtime_id in runtime_ids
            }
            assignment = self._assignment
            if assignment is not None:
                matches = [
                    item
                    for item in devices
                    if item.identity.stable_key == assignment[0] and item.assignable
                ]
                if len(matches) != 1:
                    lost_assignment = assignment
                    self._assignment = None
        status = self.diagnostic_status()
        backend_state = (
            status["initialized"],
            status["device_count"],
            error or status["error"],
            tuple(
                (item["name"], item["guid"], item["buttons"], item["ambiguous"])
                for item in status["devices"]  # type: ignore[union-attr]
            ),
        )
        if backend_state != self._backend_state:
            self._backend_state = backend_state
            self.diagnostics.record(
                "backend_refresh",
                initialized=status["initialized"],
                device_count=status["device_count"],
                devices=status["devices"],
                error=error or status["error"],
            )
        if lost_assignment is not None:
            reason = "Selected controller became unavailable during assignment"
            self.diagnostics.record("assignment_unavailable", reason=reason)
            lost_assignment[1](None, reason)
        available, reason = self.binding_availability()
        availability = "resolved" if available else reason.casefold().replace(" ", "_")
        if availability != self._availability:
            self._availability = availability
            self.diagnostics.record("binding_resolution", state=availability)

    def _run(self) -> None:
        next_refresh = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            try:
                self.backend.pump()
            except (OSError, RuntimeError) as exc:
                error = str(exc)
                if error != self._pump_error:
                    self._pump_error = error
                    self.diagnostics.record("backend_pump_failed", error=error)
                self._stop.wait(self.poll_interval_s)
                continue
            if self._pump_error is not None:
                self._pump_error = None
                self.diagnostics.record("backend_pump_recovered")
            if now >= next_refresh or self._refresh.is_set():
                self._refresh.clear()
                self._refresh_devices()
                next_refresh = now + self.refresh_interval_s
            for device in self.devices():
                try:
                    pressed = self.backend.pressed_buttons(device.runtime_id)
                except (OSError, RuntimeError):
                    continue
                previous = self._previous.get(device.runtime_id, frozenset())
                down = pressed - previous
                self._previous[device.runtime_id] = pressed
                if down:
                    self._handle_down(device, min(down), now)
                suppressed = self._suppressed_until_release
                if (
                    suppressed is not None
                    and device.identity.stable_key == suppressed[0]
                    and suppressed[1] not in pressed
                ):
                    self._suppressed_until_release = None
            self._stop.wait(self.poll_interval_s)

    def _handle_down(self, device: ControllerDevice, button: int, now: float) -> None:
        with self._lock:
            assignment = self._assignment
        if assignment is not None:
            if assignment[0] != device.identity.stable_key:
                return
            binding = ControllerBinding(
                device=device.identity,
                control_type="button",
                button_index=button,
                control_name=f"Button {button + 1}",
            )
            self.store.save(binding)
            with self._lock:
                self._binding = binding
                self._assignment = None
                self._suppressed_until_release = (device.identity.stable_key, button)
            self.diagnostics.record(
                "assignment_captured",
                device=device.identity.name,
                button=button + 1,
            )
            assignment[1](binding, None)
            return

        binding = self.binding
        if binding is None or device.identity.stable_key != binding.device.stable_key:
            return
        if device.ambiguous or button != binding.button_index:
            return
        if self._suppressed_until_release == (device.identity.stable_key, button):
            return
        if now - self._last_toggle_at < self.debounce_s:
            self.diagnostics.record("toggle_ignored", reason="debounce")
            return
        self._last_toggle_at = now
        self.diagnostics.record(
            "button_down_edge",
            device=device.identity.name,
            button=button + 1,
        )
        self.on_toggle()
