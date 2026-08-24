from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import LEFT, X, StringVar, TclError, messagebox
from tkinter import ttk
from typing import Any

from orion.controller_input import (
    BoundedControlDiagnostics,
    ControllerBinding,
    ControllerBindingStore,
    PygameJoystickBackend,
    QwenControllerMonitor,
)
from orion.qwen_realtime_provider import QwenRealtimeConfig, QwenRealtimeProvider
from orion.qwen_session_control import QwenControlResult, QwenSessionController
from orion.realtime_session_control import RealtimeSessionController


@dataclass(slots=True)
class CloudVoiceConfig:
    cloud_provider: str = "qwen_realtime"
    qwen_region: str = "singapore"
    qwen_workspace_id: str = ""
    qwen_model: str = "qwen3.5-omni-flash-realtime"
    yandex_folder_id: str = ""


class CloudVoiceConfigStore:
    """Persist non-secret ADR-004 Launcher settings only."""

    def __init__(self, runtime_dir: Path) -> None:
        self.path = runtime_dir / "cloud-voice.json"

    def load(self) -> CloudVoiceConfig:
        if not self.path.is_file():
            return CloudVoiceConfig()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return CloudVoiceConfig()
        if not isinstance(payload, dict):
            return CloudVoiceConfig()
        allowed = CloudVoiceConfig.__dataclass_fields__
        return CloudVoiceConfig(**{key: value for key, value in payload.items() if key in allowed})

    def save(self, config: CloudVoiceConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Deliberately contains no API key / bearer token.
        self.path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False), encoding="utf-8")


class QwenControlsViewLifecycle:
    """Own and cancel every Tk callback associated with one Settings view."""

    def __init__(self, root: Any) -> None:
        self.root = root
        self._generation = 0
        self._owner: Any | None = None
        self._active = False
        self._after_ids: set[str] = set()
        self._lock = threading.RLock()

    def activate(self, owner: Any) -> int:
        self.deactivate()
        with self._lock:
            self._generation += 1
            self._owner = owner
            self._active = True
            return self._generation

    def is_active(self, generation: int) -> bool:
        with self._lock:
            return self._active and generation == self._generation

    def is_alive(self, generation: int) -> bool:
        with self._lock:
            if not self._active or generation != self._generation:
                return False
            owner = self._owner
        if owner is None:
            return False
        try:
            return bool(owner.winfo_exists())
        except TclError:
            return False

    def schedule(self, delay_ms: int, callback: Any, generation: int) -> str | None:
        if not self.is_active(generation):
            return None
        holder: dict[str, str] = {}

        def run() -> None:
            callback_id = holder.get("id")
            if callback_id is not None:
                with self._lock:
                    self._after_ids.discard(callback_id)
            if self.is_alive(generation):
                callback()

        try:
            callback_id = str(self.root.after(delay_ms, run))
        except TclError:
            return None
        holder["id"] = callback_id
        with self._lock:
            if not self._active or generation != self._generation:
                try:
                    self.root.after_cancel(callback_id)
                except TclError:
                    pass
                return None
            self._after_ids.add(callback_id)
        return callback_id

    def deactivate(self) -> None:
        with self._lock:
            self._active = False
            self._generation += 1
            self._owner = None
            callback_ids = tuple(self._after_ids)
            self._after_ids.clear()
        for callback_id in callback_ids:
            try:
                self.root.after_cancel(callback_id)
            except TclError:
                # The root may already be tearing down. Ownership has already
                # been invalidated, so no callback can reschedule itself.
                pass

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._after_ids)


class LauncherCloudVoiceSectionsMixin:
    """Provider-selectable Settings → Voice surface layered onto the Launcher."""

    root: Any
    runtime_dir: Path
    core: Any
    content: Any

    def __init__(self, root, runtime_dir: Path, core) -> None:  # noqa: ANN001
        self._qwen_view_lifecycle = QwenControlsViewLifecycle(root)
        self._qwen_view_generation = 0
        super().__init__(root, runtime_dir, core)  # type: ignore[misc]
        self._qwen_control_diagnostics = BoundedControlDiagnostics()
        self._qwen_session_controller = QwenSessionController(self._realtime_core_json)
        self._realtime_session_controller = RealtimeSessionController(self._realtime_core_json)
        self._qwen_controller_monitor = QwenControllerMonitor(
            backend=PygameJoystickBackend(),
            store=ControllerBindingStore(runtime_dir),
            on_toggle=self._hardware_qwen_toggle,
            diagnostics=self._qwen_control_diagnostics,
        )
        self._qwen_controller_monitor.start()

    def _clear(self) -> None:
        self._teardown_qwen_controls_view()
        super()._clear()  # type: ignore[misc]

    def _cloud_voice_store(self) -> CloudVoiceConfigStore:
        return CloudVoiceConfigStore(self.runtime_dir)

    def _current_qwen_api_key(self) -> str:
        """Return the session key without losing it when Tk pages are rebuilt."""
        return str(getattr(self, "_qwen_api_key", "") or os.environ.get("DASHSCOPE_API_KEY", "")).strip()

    def _remember_qwen_api_key(self, value: str) -> None:
        """Keep the edited key for the lifetime of this Launcher process."""
        self._qwen_api_key = value.strip()

    def _current_yandex_api_key(self) -> str:
        return str(getattr(self, "_yandex_api_key", "")).strip()

    def _remember_yandex_api_key(self, value: str) -> None:
        self._yandex_api_key = value.strip()

    def _page_settings(self) -> None:
        super()._page_settings()  # type: ignore[misc]
        config = self._cloud_voice_store().load()

        ttk.Separator(self.content, orient="horizontal").pack(fill=X, pady=(24, 18))
        ttk.Label(self.content, text="VOICE", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            self.content,
            text=(
                "Select Qwen Realtime or Yandex Realtime. Provider transports and audio paths remain "
                "independent; only one provider can own the selected devices at a time."
            ),
            style="Muted.TLabel",
            wraplength=820,
            justify="left",
        ).pack(anchor="w", pady=(4, 12))

        provider_labels = {"Qwen Realtime": "qwen_realtime", "Yandex Realtime": "yandex"}
        region_labels = {"Singapore": "singapore", "China (Beijing)": "beijing"}
        reverse_provider = {value: label for label, value in provider_labels.items()}
        reverse_region = {value: label for label, value in region_labels.items()}

        provider = StringVar(value=reverse_provider.get(config.cloud_provider, "Qwen Realtime"))
        region = StringVar(value=reverse_region.get(config.qwen_region, "Singapore"))
        workspace = StringVar(value=config.qwen_workspace_id)
        model = StringVar(value=config.qwen_model)
        api_key = StringVar(value=self._current_qwen_api_key())
        yandex_api_key = StringVar(value=self._current_yandex_api_key())
        yandex_folder_id = StringVar(value=config.yandex_folder_id)
        # Settings pages are destroyed/recreated during navigation. Mirror every
        # edit immediately into Launcher session memory, not only on SAVE.
        api_key.trace_add("write", lambda *_: self._remember_qwen_api_key(api_key.get()))
        yandex_api_key.trace_add("write", lambda *_: self._remember_yandex_api_key(yandex_api_key.get()))
        live_status = StringVar(value="STOPPED — Realtime voice is not active")

        box = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        box.pack(fill=X)
        ttk.Label(box, text="CLOUD PROVIDER", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Combobox(box, textvariable=provider, values=tuple(provider_labels), state="readonly", width=42).pack(anchor="w", pady=(6, 12))
        qwen_fields = ttk.Frame(box, style="Card.TFrame")
        ttk.Label(qwen_fields, text="REGION", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Combobox(qwen_fields, textvariable=region, values=tuple(region_labels), state="readonly", width=42).pack(anchor="w", pady=(6, 12))
        ttk.Label(qwen_fields, text="WORKSPACE ID", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Entry(qwen_fields, textvariable=workspace, width=72).pack(anchor="w", fill=X, pady=(6, 12))
        ttk.Label(qwen_fields, text="MODEL", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Entry(qwen_fields, textvariable=model, width=72).pack(anchor="w", fill=X, pady=(6, 12))
        ttk.Label(qwen_fields, text="QWEN API KEY", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Entry(qwen_fields, textvariable=api_key, show="*", width=72).pack(anchor="w", fill=X, pady=(6, 12))
        yandex_fields = ttk.Frame(box, style="Card.TFrame")
        ttk.Label(yandex_fields, text="YANDEX API KEY", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Entry(yandex_fields, textvariable=yandex_api_key, show="*", width=72).pack(anchor="w", fill=X, pady=(6, 12))
        ttk.Label(yandex_fields, text="FOLDER ID", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Entry(yandex_fields, textvariable=yandex_folder_id, width=72).pack(anchor="w", fill=X, pady=(6, 12))
        ttk.Label(
            yandex_fields,
            text="Model: speech-realtime-260528  |  Voice: dasha  |  Language: ru-RU",
            style="CardText.TLabel",
        ).pack(anchor="w", pady=(0, 12))
        ttk.Label(
            box,
            text="Provider API keys are kept separately in memory and are never written to cloud-voice.json.",
            style="CardText.TLabel",
        ).pack(anchor="w", pady=(0, 12))
        ttk.Label(
            box,
            text=(
                "Selected microphone → ORION Core → selected realtime provider → selected output. "
                "Stop the active provider before switching."
            ),
            style="CardText.TLabel",
            wraplength=780,
            justify="left",
        ).pack(anchor="w")

        buttons = ttk.Frame(box, style="Card.TFrame")
        buttons.pack(fill=X, pady=(16, 0))

        def selected_config() -> CloudVoiceConfig:
            return CloudVoiceConfig(
                cloud_provider=provider_labels[provider.get()],
                qwen_region=region_labels[region.get()],
                qwen_workspace_id=workspace.get().strip(),
                qwen_model=model.get().strip() or "qwen3.5-omni-flash-realtime",
                yandex_folder_id=yandex_folder_id.get().strip(),
            )

        def save() -> None:
            self._cloud_voice_store().save(selected_config())
            self._remember_qwen_api_key(api_key.get())
            self._remember_yandex_api_key(yandex_api_key.get())
            messagebox.showinfo("ORION Voice", "Voice settings saved. API key kept in memory only.", parent=self.root)

        ttk.Button(buttons, text="SAVE VOICE SETTINGS", style="Primary.TButton", command=save).pack(side=LEFT, padx=(0, 8))
        ttk.Button(
            buttons,
            text="TEST CONNECTION",
            style="Secondary.TButton",
            command=lambda: self._provider_smoke_async(
                selected_config(), api_key.get(), yandex_api_key.get(), tool=False
            ),
        ).pack(side=LEFT, padx=(0, 8))
        tool_button = ttk.Button(
            buttons,
            text="TEST TOOL CALL",
            style="Secondary.TButton",
            command=lambda: self._provider_smoke_async(
                selected_config(), api_key.get(), yandex_api_key.get(), tool=True
            ),
        )
        tool_button.pack(side=LEFT)

        ttk.Separator(box, orient="horizontal").pack(fill=X, pady=(18, 14))
        ttk.Label(box, text="LIVE REALTIME AUDIO", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(box, textvariable=live_status, style="CardText.TLabel", wraplength=780, justify="left").pack(anchor="w", pady=(6, 10))
        live_buttons = ttk.Frame(box, style="Card.TFrame")
        live_buttons.pack(fill=X)
        ttk.Button(
            live_buttons,
            text="START LIVE",
            style="Primary.TButton",
            command=lambda: self._realtime_live_async(
                selected_config(), api_key.get(), yandex_api_key.get(), live_status, start=True
            ),
        ).pack(side=LEFT, padx=(0, 8))
        ttk.Button(
            live_buttons,
            text="STOP LIVE",
            style="Secondary.TButton",
            command=lambda: self._realtime_live_async(
                selected_config(), api_key.get(), yandex_api_key.get(), live_status, start=False
            ),
        ).pack(side=LEFT)

        def refresh_provider_fields(*_args: object) -> None:
            selected = provider_labels[provider.get()]
            if selected == "yandex":
                qwen_fields.pack_forget()
                yandex_fields.pack(fill=X, before=buttons)
                tool_button.state(["disabled"])
            else:
                yandex_fields.pack_forget()
                qwen_fields.pack(fill=X, before=buttons)
                tool_button.state(["!disabled"])

        provider.trace_add("write", refresh_provider_fields)
        refresh_provider_fields()
        generation = self._build_qwen_controls(box)
        self._realtime_live_poll(live_status, generation)

    @staticmethod
    def _qwen_start_payload(config: CloudVoiceConfig, api_key: str) -> dict[str, object]:
        key = api_key.strip()
        if not key:
            raise ValueError("Qwen API key is required")
        return {
            "api_key": key,
            "workspace_id": config.qwen_workspace_id,
            "region": config.qwen_region,
            "model": config.qwen_model,
            "voice": "Tina",
        }

    def _hardware_start_payload(self) -> dict[str, object]:
        return self._qwen_start_payload(
            self._cloud_voice_store().load(),
            self._current_qwen_api_key(),
        )

    @staticmethod
    def _realtime_start_payload(
        config: CloudVoiceConfig,
        qwen_api_key: str,
        yandex_api_key: str,
    ) -> dict[str, object]:
        if config.cloud_provider == "yandex":
            key = yandex_api_key.strip()
            if not key:
                raise ValueError("Yandex API key is required")
            if not config.yandex_folder_id.strip():
                raise ValueError("Yandex Folder ID is required")
            return {
                "provider": "yandex",
                "api_key": key,
                "folder_id": config.yandex_folder_id,
            }
        return {"provider": "qwen", **LauncherCloudVoiceSectionsMixin._qwen_start_payload(config, qwen_api_key)}

    def _hardware_qwen_toggle(self) -> None:
        try:
            result = self._qwen_session_controller.toggle(self._hardware_start_payload)
        except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
            self._qwen_control_diagnostics.record(
                "toggle_failed",
                error_type=type(exc).__name__,
            )
            self._set_live_status_text(f"ERROR — {type(exc).__name__}: {exc}")
            return
        event = (
            f"{result.action}_requested"
            if result.executed
            else "toggle_ignored"
        )
        self._qwen_control_diagnostics.record(
            event,
            state=result.state,
            reason=result.ignored_reason,
        )
        self._set_live_status_text(f"{result.state.upper()} — {result.message}")

    def _set_live_status_text(self, text: str) -> None:
        def apply() -> None:
            variable = getattr(self, "_qwen_live_status_var", None)
            if variable is not None:
                variable.set(text)

        self._schedule_qwen_ui(0, apply)

    def _build_qwen_controls(self, box: ttk.Frame) -> int:
        monitor = self._qwen_controller_monitor
        devices = monitor.devices()
        labels = {item.display_name: item for item in devices}
        binding = monitor.binding
        selected_label = ""
        if binding is not None:
            selected_label = next(
                (
                    label
                    for label, item in labels.items()
                    if item.identity.stable_key == binding.device.stable_key
                ),
                "",
            )
        if not selected_label and labels:
            selected_label = next(iter(labels))

        ttk.Separator(box, orient="horizontal").pack(fill=X, pady=(18, 14))
        controls = ttk.Frame(box, style="Card.TFrame")
        controls.pack(fill=X)
        generation = self._qwen_view_lifecycle.activate(controls)
        self._qwen_view_generation = generation
        ttk.Label(controls, text="CONTROLS", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            controls,
            text="Assign one joystick/HOTAS/throttle button to start and stop the same Core-owned Qwen session.",
            style="CardText.TLabel",
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(6, 10))

        device_var = StringVar(value=selected_label)
        binding_var = StringVar()
        self._qwen_control_device_var = device_var
        self._qwen_control_binding_var = binding_var
        self._qwen_control_devices = labels

        ttk.Label(controls, text="DEVICE", style="CardTitle.TLabel").pack(anchor="w")
        device_row = ttk.Frame(controls, style="Card.TFrame")
        device_row.pack(fill=X, pady=(6, 12))
        device_combo = ttk.Combobox(
            device_row,
            textvariable=device_var,
            values=tuple(labels),
            state="readonly",
            width=64,
        )
        device_combo.pack(side=LEFT, fill=X, expand=True)
        self._qwen_control_device_combo = device_combo
        ttk.Button(
            device_row,
            text="REFRESH",
            style="Secondary.TButton",
            command=self._refresh_qwen_controller_devices,
        ).pack(side=LEFT, padx=(8, 0))

        diagnostic_var = StringVar()
        self._qwen_control_diagnostic_var = diagnostic_var
        ttk.Label(
            controls,
            textvariable=diagnostic_var,
            style="CardText.TLabel",
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(0, 12))

        ttk.Label(controls, text="QWEN SESSION TOGGLE", style="CardTitle.TLabel").pack(anchor="w")
        control_row = ttk.Frame(controls, style="Card.TFrame")
        control_row.pack(fill=X, pady=(6, 0))
        ttk.Label(
            control_row,
            textvariable=binding_var,
            style="CardText.TLabel",
            wraplength=510,
            justify="left",
        ).pack(side=LEFT, fill=X, expand=True)
        assign = ttk.Button(
            control_row,
            text="ASSIGN / CHANGE",
            style="Secondary.TButton",
        )
        assign.configure(command=lambda: self._assign_qwen_control(assign))
        assign.pack(side=LEFT, padx=(8, 0))
        ttk.Button(
            control_row,
            text="CLEAR",
            style="Secondary.TButton",
            command=self._clear_qwen_control,
        ).pack(side=LEFT, padx=(8, 0))
        self._qwen_control_assign_button = assign
        self._refresh_qwen_control_status()
        return generation

    def _schedule_qwen_ui(
        self,
        delay_ms: int,
        callback: Any,
        generation: int | None = None,
    ) -> str | None:
        token = self._qwen_view_generation if generation is None else generation
        return self._qwen_view_lifecycle.schedule(delay_ms, callback, token)

    def _teardown_qwen_controls_view(self) -> None:
        lifecycle = getattr(self, "_qwen_view_lifecycle", None)
        if lifecycle is not None:
            lifecycle.deactivate()
        monitor = getattr(self, "_qwen_controller_monitor", None)
        if monitor is not None:
            monitor.cancel_assignment(notify=False, reason="Qwen controls view closed")
        for name in (
            "_qwen_control_device_combo",
            "_qwen_control_device_var",
            "_qwen_control_binding_var",
            "_qwen_control_diagnostic_var",
        ):
            self.__dict__.pop(name, None)
        self._qwen_control_devices = {}

    def _refresh_qwen_controller_devices(self) -> None:
        self._qwen_controller_monitor.refresh()
        self._schedule_qwen_ui(150, self._refresh_qwen_control_ui)

    def _refresh_qwen_control_ui(self, generation: int | None = None) -> None:
        token = self._qwen_view_generation if generation is None else generation
        if not self._qwen_view_lifecycle.is_alive(token):
            return
        devices = self._qwen_controller_monitor.devices()
        labels = {item.display_name: item for item in devices}
        self._qwen_control_devices = labels
        combo = getattr(self, "_qwen_control_device_combo", None)
        if combo is None:
            return
        device_var = getattr(self, "_qwen_control_device_var", None)
        if device_var is None:
            return
        combo.configure(values=tuple(labels))
        current = device_var.get()
        if current not in labels:
            binding = self._qwen_controller_monitor.binding
            current = next(
                (
                    label
                    for label, item in labels.items()
                    if binding is not None
                    and item.identity.stable_key == binding.device.stable_key
                ),
                next(iter(labels), ""),
            )
            device_var.set(current)
        self._refresh_qwen_control_status()

    def _refresh_qwen_control_status(self) -> None:
        variable = getattr(self, "_qwen_control_binding_var", None)
        if variable is None:
            return
        binding = self._qwen_controller_monitor.binding
        _, availability = self._qwen_controller_monitor.binding_availability()
        variable.set("UNASSIGNED" if binding is None else f"{binding.display_name} — {availability}")
        diagnostic = getattr(self, "_qwen_control_diagnostic_var", None)
        if diagnostic is not None:
            status = self._qwen_controller_monitor.diagnostic_status()
            error = status.get("error")
            prefix = "SDL ERROR" if error else "SDL READY" if status["initialized"] else "SDL INITIALIZING"
            device_var = getattr(self, "_qwen_control_device_var", None)
            selected = device_var.get() if device_var is not None else ""
            selected_device = self._qwen_control_devices.get(selected)
            selected_status = "resolved" if selected_device is not None and selected_device.assignable else "not selected/resolved"
            details = f"{prefix} — {status['device_count']} device(s) visible; selected: {selected or 'none'} ({selected_status})"
            diagnostic.set(f"{details}{'' if not error else f'; {error}'}")

    def _assign_qwen_control(self, button: ttk.Button) -> None:
        device_var = getattr(self, "_qwen_control_device_var", None)
        binding_var = getattr(self, "_qwen_control_binding_var", None)
        if device_var is None or binding_var is None:
            return
        if str(button.cget("text")) == "CANCEL":
            self._qwen_controller_monitor.cancel_assignment()
            button.configure(text="ASSIGN / CHANGE")
            self._refresh_qwen_control_status()
            return
        selected = self._qwen_control_devices.get(device_var.get())
        if selected is None:
            binding_var.set("Select an available controller first")
            return

        generation = self._qwen_view_generation

        def captured(binding: ControllerBinding | None, error: str | None) -> None:
            def apply() -> None:
                button.configure(text="ASSIGN / CHANGE")
                if error:
                    binding_var.set(error)
                else:
                    self._refresh_qwen_control_status()

            self._schedule_qwen_ui(0, apply, generation)

        if self._qwen_controller_monitor.begin_assignment(selected.identity.stable_key, captured):
            button.configure(text="CANCEL")
            binding_var.set(
                f"WAITING FOR BUTTON — {selected.identity.name}"
            )
        else:
            binding_var.set("Selected controller is no longer available; press Refresh")

    def _clear_qwen_control(self) -> None:
        self._qwen_controller_monitor.clear_binding()
        self._refresh_qwen_control_status()

    def _shutdown_qwen_controls(self) -> None:
        self._teardown_qwen_controls_view()
        monitor = getattr(self, "_qwen_controller_monitor", None)
        if monitor is not None:
            monitor.stop()

    def _stop_qwen_before_exit(self) -> None:
        self._stop_realtime_before_exit()

    def _stop_realtime_before_exit(self) -> None:
        """Best-effort graceful stop while Core is still available."""
        self._shutdown_qwen_controls()
        try:
            self._realtime_core_json("/v1/realtime/live/stop", method="POST")
        except Exception:
            # Explicit application exit must still shut down a stopped or
            # unreachable Core.  Core process shutdown is the final boundary.
            return

    def _realtime_core_json(self, path: str, *, method: str = "GET", payload: dict[str, object] | None = None) -> dict[str, object]:
        """Realtime-only Core JSON helper.

        Deliberately does not override LauncherAudioSectionsMixin._core_json: the
        canonical audio helper must continue accepting list responses from the
        WASAPI discovery endpoints used by Build #317.
        """
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.core.base_url.rstrip('/')}{path}",
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"} if data is not None else {},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=4.0) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not isinstance(result, dict):
            raise RuntimeError("ORION Core returned an invalid realtime response")
        return result

    def _qwen_live_async(
        self,
        config: CloudVoiceConfig,
        api_key: str,
        live_status: StringVar,
        *,
        start: bool,
    ) -> None:
        key = api_key.strip() or self._current_qwen_api_key()
        self._qwen_live_status_var = live_status
        generation = self._qwen_view_generation

        def worker() -> None:
            try:
                if start:
                    control = self._qwen_session_controller.request_start(
                        lambda: self._qwen_start_payload(config, key)
                    )
                else:
                    control = self._qwen_session_controller.request_stop()
                state = control.state.upper()
                message = control.message
                self._schedule_qwen_ui(0, lambda: live_status.set(f"{state} — {message}"), generation)
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
                self._schedule_qwen_ui(
                    0,
                    lambda exc=exc: live_status.set(f"ERROR — {type(exc).__name__}: {exc}"),
                    generation,
                )

        threading.Thread(target=worker, name="orion-qwen-live-control", daemon=True).start()

    def _qwen_live_poll(self, live_status: StringVar, generation: int) -> None:
        if not self._qwen_view_lifecycle.is_alive(generation):
            return
        self._qwen_live_status_var = live_status

        def worker() -> None:
            try:
                result = self._realtime_core_json("/v1/realtime/qwen/live")
            except Exception:
                return
            state = str(result.get("state", "unknown")).upper()
            message = str(result.get("message", ""))
            input_chunks = int(str(result.get("input_chunks", 0) or 0))
            output_chunks = int(str(result.get("output_chunks", 0) or 0))
            suffix = "" if not (input_chunks or output_chunks) else f" | mic={input_chunks} qwen_audio={output_chunks}"

            def apply() -> None:
                live_status.set(f"{state} — {message}{suffix}")
                self._refresh_qwen_control_ui(generation)

            self._schedule_qwen_ui(
                0,
                apply,
                generation,
            )

        threading.Thread(target=worker, name="orion-qwen-live-status", daemon=True).start()
        self._schedule_qwen_ui(
            750,
            lambda: self._qwen_live_poll(live_status, generation),
            generation,
        )

    def _qwen_smoke_async(self, config: CloudVoiceConfig, api_key: str, *, tool: bool) -> None:
        key = api_key.strip() or self._current_qwen_api_key()
        qwen = QwenRealtimeProvider(
            QwenRealtimeConfig(
                api_key=key,
                workspace_id=config.qwen_workspace_id,
                core_base_url=self.core.base_url,
                region=config.qwen_region,
                model=config.qwen_model,
            )
        )

        def worker() -> None:
            result = qwen.test_tool_call() if tool else qwen.test_connection()

            def show() -> None:
                latency = "" if result.latency_ms is None else f"\nLatency: {result.latency_ms:.0f} ms"
                tool_text = "" if result.tool_name is None else f"\nTool: {result.tool_name}\nOutput: {result.tool_output}"
                assistant = "" if result.assistant_text is None else f"\nQwen: {result.assistant_text}"
                message = f"{result.message}{latency}{tool_text}{assistant}"
                if result.ok:
                    messagebox.showinfo("ORION Qwen Realtime", message, parent=self.root)
                else:
                    messagebox.showerror("ORION Qwen Realtime", message, parent=self.root)

            self.root.after(0, show)

        threading.Thread(target=worker, name="orion-qwen-smoke", daemon=True).start()

    def _realtime_live_async(
        self,
        config: CloudVoiceConfig,
        qwen_api_key: str,
        yandex_api_key: str,
        live_status: StringVar,
        *,
        start: bool,
    ) -> None:
        self._qwen_live_status_var = live_status
        generation = self._qwen_view_generation

        def worker() -> None:
            try:
                control = (
                    self._realtime_session_controller.request_start(
                        lambda: self._realtime_start_payload(config, qwen_api_key, yandex_api_key)
                    )
                    if start
                    else self._realtime_session_controller.request_stop()
                )
                self._schedule_qwen_ui(
                    0,
                    lambda: live_status.set(f"{control.state.upper()} — {control.message}"),
                    generation,
                )
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
                self._schedule_qwen_ui(
                    0,
                    lambda exc=exc: live_status.set(f"ERROR — {type(exc).__name__}: {exc}"),
                    generation,
                )

        threading.Thread(target=worker, name="orion-realtime-live-control", daemon=True).start()

    def _realtime_live_poll(self, live_status: StringVar, generation: int) -> None:
        if not self._qwen_view_lifecycle.is_alive(generation):
            return
        self._qwen_live_status_var = live_status

        def worker() -> None:
            try:
                result = self._realtime_core_json("/v1/realtime/live/status")
            except Exception:
                return
            state = str(result.get("state", "unknown")).upper()
            provider = str(result.get("provider") or "")
            message = str(result.get("message", ""))
            input_chunks = int(str(result.get("input_chunks", 0) or 0))
            output_chunks = int(str(result.get("output_chunks", 0) or 0))
            suffix = "" if not (input_chunks or output_chunks) else f" | mic={input_chunks} audio={output_chunks}"
            prefix = f"{provider.upper()} " if provider else ""
            self._schedule_qwen_ui(
                0, lambda: live_status.set(f"{prefix}{state} — {message}{suffix}"), generation
            )

        threading.Thread(target=worker, name="orion-realtime-live-status", daemon=True).start()
        self._schedule_qwen_ui(
            750, lambda: self._realtime_live_poll(live_status, generation), generation
        )

    def _provider_smoke_async(
        self,
        config: CloudVoiceConfig,
        qwen_api_key: str,
        yandex_api_key: str,
        *,
        tool: bool,
    ) -> None:
        if config.cloud_provider != "yandex":
            self._qwen_smoke_async(config, qwen_api_key, tool=tool)
            return
        if tool:
            messagebox.showinfo(
                "ORION Yandex Realtime",
                "Yandex tool-call integration not implemented yet",
                parent=self.root,
            )
            return

        def worker() -> None:
            try:
                key = yandex_api_key.strip() or self._current_yandex_api_key()
                if not key:
                    raise ValueError("Yandex API key is required")
                result = self._realtime_core_json(
                    "/v1/realtime/yandex/test-connection",
                    method="POST",
                    payload={"api_key": key, "folder_id": config.yandex_folder_id},
                )
                ok = bool(result.get("ok"))
                message = str(result.get("message", ""))
            except Exception as exc:
                ok = False
                message = f"{type(exc).__name__}: {exc}"

            def show() -> None:
                dialog = messagebox.showinfo if ok else messagebox.showerror
                dialog("ORION Yandex Realtime", message, parent=self.root)

            self.root.after(0, show)

        threading.Thread(target=worker, name="orion-yandex-smoke", daemon=True).start()
