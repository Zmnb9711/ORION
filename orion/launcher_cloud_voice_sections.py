from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import LEFT, X, BooleanVar, StringVar, TclError, filedialog, messagebox
from tkinter import ttk
from typing import Any, Callable

from orion.controller_input import (
    BoundedControlDiagnostics,
    ControllerBinding,
    ControllerBindingStore,
    PygameJoystickBackend,
    QwenControllerMonitor,
)
from orion.qwen_realtime_provider import QwenRealtimeConfig, QwenRealtimeProvider
from orion.realtime_session_control import RealtimeSessionController
from orion.srs_process_control import (
    SrsExternalProcessController,
    SrsProcessKind,
    SrsProcessState,
    SrsProcessStatus,
)
from orion.windows_credentials import (
    CredentialStoreError,
    VoiceCredential,
    default_voice_credential_store,
)

SRS_CONNECT_INSTRUCTION = "In SRS Client press CONNECT, then CONNECT EAM."


@dataclass(slots=True)
class CloudVoiceConfig:
    cloud_provider: str = "qwen_realtime"
    voice_transport: str = "direct"
    qwen_region: str = "singapore"
    qwen_workspace_id: str = ""
    qwen_model: str = "qwen3.5-omni-flash-realtime"
    yandex_folder_id: str = ""
    srs_host: str = "127.0.0.1"
    srs_port: int = 5002
    srs_server_path: str = ""
    srs_client_path: str = ""


def format_srs_process_status(status: SrsProcessStatus) -> str:
    label = "SRS SERVER" if status.kind is SrsProcessKind.SERVER else "SRS CLIENT"
    pid = f" (PID {status.pid})" if status.pid is not None else ""
    detail = f" — {status.message}" if status.message else ""
    return f"{label}: {status.state.value}{pid}{detail}"


def format_orion_srs_status(result: Mapping[str, object]) -> str:
    if str(result.get("transport") or "").casefold() != "srs":
        return "ORION SRS: NOT CONNECTED"
    state = str(result.get("state") or "stopped").casefold()
    phase = str(result.get("phase") or "idle").casefold()
    if state == "error":
        return f"ORION SRS: ERROR — {result.get('message') or 'SRS session failed'}"
    if state == "streaming":
        return "ORION SRS: READY"
    if phase == "registering_radio":
        return "ORION SRS: REGISTERING RADIO"
    if phase == "registering_udp":
        return "ORION SRS: REGISTERING UDP"
    if state in {"starting", "connected"} or phase in {"srs_connecting", "provider_connecting"}:
        return "ORION SRS: CONNECTING"
    return "ORION SRS: NOT CONNECTED"


def format_test_evidence_status(result: Mapping[str, object]) -> str:
    if bool(result.get("active")):
        provider = str(result.get("provider") or "unknown").upper()
        transport = str(result.get("transport") or "unknown").upper()
        count = int(str(result.get("event_count") or 0))
        return f"Test Session: RECORDING — {provider} / {transport} | events={count}"
    export_path = str(result.get("last_export_path") or "").strip()
    return f"Test Session: OFF{f' — Last export: {export_path}' if export_path else ''}"


def format_presentation_probe_status(result: Mapping[str, object]) -> str:
    state = str(result.get("state") or "idle").upper()
    message = str(result.get("message") or "Presentation probe is idle")
    case_id = str(result.get("probe_case_id") or "").strip()
    suffix = f" | case={case_id}" if case_id else ""
    return f"Presentation Probe: {state} — {message}{suffix}"


def format_hybrid_probe_status(result: Mapping[str, object]) -> str:
    state = str(result.get("state") or "off").upper()
    message = str(result.get("message") or "Hybrid presentation probe is off")
    case_id = str(result.get("case_id") or "").strip()
    backend = str(result.get("backend") or "").strip()
    suffix = f" | {case_id}/{backend}" if case_id and backend else ""
    return f"Hybrid Probe: {state} — {message}{suffix}"


def format_live_golden_status(result: Mapping[str, object]) -> str:
    state = str(result.get("state") or "off").upper()
    message = str(result.get("message") or "Live Golden Conversation is off")
    raw_case_number = result.get("case_number")
    raw_total = result.get("total_cases")
    case_number = raw_case_number if isinstance(raw_case_number, int) else 0
    total = raw_total if isinstance(raw_total, int) else 8
    prompt = str(result.get("next_prompt") or "").strip()
    progress = f" [{case_number}/{total}]" if case_number else ""
    next_case = f"\nSAY: {prompt}" if prompt else ""
    return f"Live Golden: {state}{progress} — {message}{next_case}"


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
        self._realtime_session_controller = RealtimeSessionController(self._realtime_core_json)
        self._voice_credential_store = default_voice_credential_store()
        self._last_test_evidence_export = ""
        self._srs_process_controller = SrsExternalProcessController()
        self._qwen_controller_monitor = QwenControllerMonitor(
            backend=PygameJoystickBackend(),
            store=ControllerBindingStore(runtime_dir),
            on_toggle=self._hardware_ai_session_toggle,
            diagnostics=self._qwen_control_diagnostics,
        )
        self._qwen_controller_monitor.start()

    def _clear(self) -> None:
        self._teardown_qwen_controls_view()
        super()._clear()  # type: ignore[misc]

    def _cloud_voice_store(self) -> CloudVoiceConfigStore:
        return CloudVoiceConfigStore(self.runtime_dir)

    def _current_qwen_api_key(self) -> str:
        """Return the protected key without losing edits when Tk pages rebuild."""
        if hasattr(self, "_qwen_api_key"):
            return str(self._qwen_api_key).strip()
        store = getattr(self, "_voice_credential_store", None)
        saved = store.load(VoiceCredential.QWEN_API_KEY) if store is not None else ""
        return str(saved or os.environ.get("DASHSCOPE_API_KEY", "")).strip()

    def _remember_qwen_api_key(self, value: str) -> None:
        """Keep the edited key for the lifetime of this Launcher process."""
        self._qwen_api_key = value.strip()

    def _current_yandex_api_key(self) -> str:
        if hasattr(self, "_yandex_api_key"):
            return str(self._yandex_api_key).strip()
        store = getattr(self, "_voice_credential_store", None)
        return str(store.load(VoiceCredential.YANDEX_API_KEY) if store is not None else "").strip()

    def _remember_yandex_api_key(self, value: str) -> None:
        self._yandex_api_key = value.strip()

    def _current_srs_eam_password(self) -> str:
        if hasattr(self, "_srs_eam_password"):
            return str(self._srs_eam_password)
        store = getattr(self, "_voice_credential_store", None)
        return str(store.load(VoiceCredential.SRS_EAM_PASSWORD) if store is not None else "")

    def _remember_srs_eam_password(self, value: str) -> None:
        self._srs_eam_password = value

    @staticmethod
    def _validated_srs_port(value: str) -> int:
        try:
            port = int(value.strip())
        except ValueError as exc:
            raise ValueError("SRS Server Port must be a number") from exc
        if not 1 <= port <= 65_535:
            raise ValueError("SRS Server Port must be between 1 and 65535")
        return port

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
        transport_labels = {"Direct Audio": "direct", "SRS Radio": "srs"}
        region_labels = {"Singapore": "singapore", "China (Beijing)": "beijing"}
        reverse_provider = {value: label for label, value in provider_labels.items()}
        reverse_transport = {value: label for label, value in transport_labels.items()}
        reverse_region = {value: label for label, value in region_labels.items()}

        provider = StringVar(value=reverse_provider.get(config.cloud_provider, "Qwen Realtime"))
        transport = StringVar(value=reverse_transport.get(config.voice_transport, "Direct Audio"))
        region = StringVar(value=reverse_region.get(config.qwen_region, "Singapore"))
        workspace = StringVar(value=config.qwen_workspace_id)
        model = StringVar(value=config.qwen_model)
        api_key = StringVar(value=self._current_qwen_api_key())
        yandex_api_key = StringVar(value=self._current_yandex_api_key())
        yandex_folder_id = StringVar(value=config.yandex_folder_id)
        srs_host = StringVar(value=config.srs_host)
        srs_port = StringVar(value=str(config.srs_port))
        srs_server_path = StringVar(value=config.srs_server_path)
        srs_client_path = StringVar(value=config.srs_client_path)
        srs_eam_password = StringVar(value=self._current_srs_eam_password())
        # Settings pages are destroyed/recreated during navigation. Mirror every
        # edit immediately into Launcher session memory, not only on SAVE.
        api_key.trace_add("write", lambda *_: self._remember_qwen_api_key(api_key.get()))
        yandex_api_key.trace_add("write", lambda *_: self._remember_yandex_api_key(yandex_api_key.get()))
        srs_eam_password.trace_add(
            "write", lambda *_: self._remember_srs_eam_password(srs_eam_password.get())
        )
        live_status = StringVar(value="STOPPED — Realtime voice is not active")
        test_evidence_status = StringVar(value="Test Session: OFF")
        compatibility_status = StringVar()
        srs_server_status = StringVar(value="SRS SERVER: STOPPED")
        srs_client_status = StringVar(value="SRS CLIENT: STOPPED")
        orion_srs_status = StringVar(value="ORION SRS: NOT CONNECTED")

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

        transport_fields = ttk.Frame(box, style="Card.TFrame")
        transport_fields.pack(fill=X, pady=(4, 0))
        ttk.Label(transport_fields, text="VOICE TRANSPORT", style="CardTitle.TLabel").pack(
            anchor="w"
        )
        ttk.Combobox(
            transport_fields,
            textvariable=transport,
            values=tuple(transport_labels),
            state="readonly",
            width=42,
        ).pack(anchor="w", pady=(6, 8))
        ttk.Label(
            transport_fields,
            textvariable=compatibility_status,
            style="CardText.TLabel",
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        srs_fields = ttk.Frame(box, style="Card.TFrame")
        ttk.Label(srs_fields, text="SRS CONNECTION", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            srs_fields,
            text=(
                "ORION uses a validated 251.000 MHz AM radio profile. Configure radios, PTT, "
                "audio devices and volume only in the official SRS Client."
            ),
            style="CardText.TLabel",
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(6, 10))

        connection_row = ttk.Frame(srs_fields, style="Card.TFrame")
        connection_row.pack(fill=X, pady=(0, 10))
        ttk.Label(connection_row, text="SERVER HOST", style="CardTitle.TLabel").pack(side=LEFT)
        ttk.Entry(connection_row, textvariable=srs_host, width=30).pack(side=LEFT, padx=(8, 18))
        ttk.Label(connection_row, text="PORT", style="CardTitle.TLabel").pack(side=LEFT)
        ttk.Entry(connection_row, textvariable=srs_port, width=10).pack(side=LEFT, padx=(8, 0))

        ttk.Label(srs_fields, text="ORION EAM PASSWORD", style="CardTitle.TLabel").pack(
            anchor="w"
        )
        ttk.Entry(srs_fields, textvariable=srs_eam_password, show="*", width=72).pack(
            anchor="w", fill=X, pady=(6, 12)
        )

        ttk.Label(srs_fields, textvariable=srs_server_status, style="CardText.TLabel").pack(
            anchor="w"
        )
        server_row = ttk.Frame(srs_fields, style="Card.TFrame")
        server_row.pack(fill=X, pady=(6, 12))
        ttk.Entry(server_row, textvariable=srs_server_path, width=58).pack(
            side=LEFT, fill=X, expand=True
        )
        ttk.Button(
            server_row,
            text="SELECT",
            style="Secondary.TButton",
            command=lambda: self._select_srs_executable(SrsProcessKind.SERVER, srs_server_path),
        ).pack(side=LEFT, padx=(8, 0))
        ttk.Button(
            server_row,
            text="START SRS SERVER",
            style="Secondary.TButton",
            command=lambda: self._start_srs_process_async(
                SrsProcessKind.SERVER,
                srs_server_path.get(),
                srs_client_path.get(),
                srs_server_status,
                srs_client_status,
            ),
        ).pack(side=LEFT, padx=(8, 0))

        ttk.Label(srs_fields, textvariable=srs_client_status, style="CardText.TLabel").pack(
            anchor="w"
        )
        client_row = ttk.Frame(srs_fields, style="Card.TFrame")
        client_row.pack(fill=X, pady=(6, 10))
        ttk.Entry(client_row, textvariable=srs_client_path, width=58).pack(
            side=LEFT, fill=X, expand=True
        )
        ttk.Button(
            client_row,
            text="SELECT",
            style="Secondary.TButton",
            command=lambda: self._select_srs_executable(SrsProcessKind.CLIENT, srs_client_path),
        ).pack(side=LEFT, padx=(8, 0))
        ttk.Button(
            client_row,
            text="START SRS CLIENT",
            style="Secondary.TButton",
            command=lambda: self._start_srs_process_async(
                SrsProcessKind.CLIENT,
                srs_server_path.get(),
                srs_client_path.get(),
                srs_server_status,
                srs_client_status,
            ),
        ).pack(side=LEFT, padx=(8, 0))
        ttk.Label(
            srs_fields,
            text=SRS_CONNECT_INSTRUCTION,
            style="CardText.TLabel",
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(srs_fields, textvariable=orion_srs_status, style="CardText.TLabel").pack(
            anchor="w", pady=(0, 10)
        )
        ttk.Label(
            box,
            text=(
                "Provider API keys and the ORION EAM password are stored in Windows Credential "
                "Manager and are never written to cloud-voice.json."
            ),
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
            selected_transport = transport_labels[transport.get()]
            selected_srs_port = (
                self._validated_srs_port(srs_port.get())
                if selected_transport == "srs"
                else config.srs_port
            )
            return CloudVoiceConfig(
                cloud_provider=provider_labels[provider.get()],
                voice_transport=selected_transport,
                qwen_region=region_labels[region.get()],
                qwen_workspace_id=workspace.get().strip(),
                qwen_model=model.get().strip() or "qwen3.5-omni-flash-realtime",
                yandex_folder_id=yandex_folder_id.get().strip(),
                srs_host=srs_host.get().strip() or "127.0.0.1",
                srs_port=selected_srs_port,
                srs_server_path=srs_server_path.get().strip(),
                srs_client_path=srs_client_path.get().strip(),
            )

        def save() -> None:
            try:
                selected = selected_config()
                self._cloud_voice_store().save(selected)
                self._voice_credential_store.save_all(
                    qwen_api_key=api_key.get(),
                    yandex_api_key=yandex_api_key.get(),
                    srs_eam_password=srs_eam_password.get(),
                )
            except (CredentialStoreError, ValueError) as exc:
                messagebox.showerror("ORION Voice", str(exc), parent=self.root)
                return
            self._remember_qwen_api_key(api_key.get())
            self._remember_yandex_api_key(yandex_api_key.get())
            self._remember_srs_eam_password(srs_eam_password.get())
            messagebox.showinfo(
                "ORION Voice",
                "Voice settings saved. Credentials are protected by Windows Credential Manager.",
                parent=self.root,
            )

        def clear_saved_credentials() -> None:
            try:
                self._voice_credential_store.clear_all()
            except CredentialStoreError as exc:
                messagebox.showerror("ORION Voice", str(exc), parent=self.root)
                return
            self._remember_qwen_api_key("")
            self._remember_yandex_api_key("")
            self._remember_srs_eam_password("")
            api_key.set("")
            yandex_api_key.set("")
            srs_eam_password.set("")
            messagebox.showinfo(
                "ORION Voice",
                "Saved Voice credentials cleared.",
                parent=self.root,
            )

        ttk.Button(buttons, text="SAVE VOICE SETTINGS", style="Primary.TButton", command=save).pack(side=LEFT, padx=(0, 8))
        ttk.Button(
            buttons,
            text="CLEAR SAVED CREDENTIALS",
            style="Secondary.TButton",
            command=clear_saved_credentials,
        ).pack(side=LEFT, padx=(0, 8))
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
        def control_live(*, start: bool) -> None:
            try:
                live_config = selected_config() if start else config
            except ValueError as exc:
                messagebox.showerror("ORION Voice", str(exc), parent=self.root)
                return
            self._realtime_live_async(
                live_config,
                api_key.get(),
                yandex_api_key.get(),
                srs_eam_password.get(),
                live_status,
                start=start,
            )

        live_start_button = ttk.Button(
            live_buttons,
            text="START LIVE",
            style="Primary.TButton",
            command=lambda: control_live(start=True),
        )
        live_start_button.pack(side=LEFT, padx=(0, 8))
        ttk.Button(
            live_buttons,
            text="STOP LIVE",
            style="Secondary.TButton",
            command=lambda: control_live(start=False),
        ).pack(side=LEFT)

        ttk.Label(
            box,
            text="LIVE GOLDEN CONVERSATION / MODE A",
            style="CardTitle.TLabel",
        ).pack(anchor="w", pady=(18, 0))
        ttk.Label(
            box,
            text=(
                "Real speech via official SRS Client → existing Yandex transcript → "
                "Qwen FREE/OPERATIONAL → controlled Golden ATC → FAP_RUSSIAN_ATC → "
                "SpeechKit → existing RadioRouter/SRS adapter. Start Yandex + SRS and "
                "Test Session first. DCS is not required."
            ),
            style="CardText.TLabel",
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(6, 8))
        live_golden_status = StringVar(value="Live Golden: OFF")
        ttk.Label(
            box,
            textvariable=live_golden_status,
            style="CardText.TLabel",
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        live_golden_row = ttk.Frame(box, style="Card.TFrame")
        live_golden_row.pack(fill=X)
        capture_live_golden_audio = BooleanVar(value=True)
        ttk.Checkbutton(
            live_golden_row,
            text="Include finalized SpeechKit→SRS WAVs in Test Evidence",
            variable=capture_live_golden_audio,
        ).pack(side=LEFT, padx=(0, 8))
        ttk.Button(
            live_golden_row,
            text="START LIVE GOLDEN",
            style="Primary.TButton",
            command=lambda: self._live_golden_start_async(
                capture_live_golden_audio.get(), live_golden_status
            ),
        ).pack(side=LEFT, padx=(0, 8))
        ttk.Button(
            live_golden_row,
            text="STOP LIVE GOLDEN",
            style="Secondary.TButton",
            command=lambda: self._live_golden_stop_async(live_golden_status),
        ).pack(side=LEFT)
        live_golden_review_row = ttk.Frame(box, style="Card.TFrame")
        live_golden_review_row.pack(fill=X, pady=(8, 0))
        live_golden_review = StringVar(value="CLEAR")
        ttk.Combobox(
            live_golden_review_row,
            textvariable=live_golden_review,
            values=("CLEAR", "UNCLEAR", "NOT_HEARD"),
            state="readonly",
            width=14,
        ).pack(side=LEFT, padx=(0, 8))
        ttk.Button(
            live_golden_review_row,
            text="RECORD CASE REVIEW",
            style="Secondary.TButton",
            command=lambda: self._live_golden_review_async(
                live_golden_review.get(), live_golden_status
            ),
        ).pack(side=LEFT)

        ttk.Label(box, text="HYBRID PRESENTATION / SPEECHKIT PROBE", style="CardTitle.TLabel").pack(anchor="w", pady=(18, 0))
        ttk.Label(
            box,
            text=(
                "Compares disposable Yandex Realtime rendering with direct SpeechKit TTS, "
                "then sends each synthetic phrase through the existing SRS TX one at a time. "
                "Requires Yandex + SRS and an active Test Session."
            ),
            style="CardText.TLabel",
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(6, 8))
        hybrid_status = StringVar(value="Hybrid Probe: OFF")
        ttk.Label(box, textvariable=hybrid_status, style="CardText.TLabel", wraplength=780, justify="left").pack(anchor="w", pady=(0, 8))
        hybrid_row = ttk.Frame(box, style="Card.TFrame")
        hybrid_row.pack(fill=X)
        capture_hybrid_audio = BooleanVar(value=False)
        ttk.Checkbutton(
            hybrid_row,
            text="Include bounded synthetic probe WAVs in Test Evidence",
            variable=capture_hybrid_audio,
        ).pack(side=LEFT, padx=(0, 8))
        ttk.Button(
            hybrid_row,
            text="RUN HYBRID PRESENTATION PROBE",
            style="Secondary.TButton",
            command=lambda: self._hybrid_probe_async(capture_hybrid_audio.get(), hybrid_status),
        ).pack(side=LEFT)
        hybrid_review_row = ttk.Frame(box, style="Card.TFrame")
        hybrid_review_row.pack(fill=X, pady=(8, 0))
        hybrid_review = StringVar(value="CLEAR")
        ttk.Combobox(
            hybrid_review_row,
            textvariable=hybrid_review,
            values=("CLEAR", "REVIEW", "FAIL"),
            state="readonly",
            width=12,
        ).pack(side=LEFT, padx=(0, 8))
        ttk.Button(
            hybrid_review_row,
            text="RECORD ACOUSTIC REVIEW",
            style="Secondary.TButton",
            command=lambda: self._hybrid_review_async(hybrid_review.get(), hybrid_status),
        ).pack(side=LEFT)

        ttk.Label(
            box,
            textvariable=test_evidence_status,
            style="CardText.TLabel",
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(12, 8))
        test_evidence_buttons = ttk.Frame(box, style="Card.TFrame")
        test_evidence_buttons.pack(fill=X)
        reveal_test_evidence_button = ttk.Button(
            test_evidence_buttons,
            text="OPEN EXPORT FOLDER",
            style="Secondary.TButton",
            state="disabled",
            command=self._open_last_test_evidence_export,
        )

        def start_test_evidence() -> None:
            evidence_config = CloudVoiceConfig(
                cloud_provider=provider_labels[provider.get()],
                voice_transport=transport_labels[transport.get()],
            )
            self._start_test_evidence_async(
                evidence_config,
                test_evidence_status,
            )

        ttk.Button(
            test_evidence_buttons,
            text="START TEST SESSION",
            style="Primary.TButton",
            command=start_test_evidence,
        ).pack(side=LEFT, padx=(0, 8))
        ttk.Button(
            test_evidence_buttons,
            text="STOP & EXPORT TEST SESSION",
            style="Secondary.TButton",
            command=lambda: self._stop_test_evidence_async(
                test_evidence_status,
                reveal_test_evidence_button,
            ),
        ).pack(side=LEFT, padx=(0, 8))
        reveal_test_evidence_button.pack(side=LEFT)
        self._test_evidence_status_var = test_evidence_status
        self._test_evidence_reveal_button = reveal_test_evidence_button

        ttk.Separator(box, orient="horizontal").pack(fill=X, pady=(18, 14))
        ttk.Label(box, text="PRESENTATION PROBE", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            box,
            text=(
                "Runs bounded synthetic IA-1 cases in the existing active Yandex session. "
                "Start Test Session first for field evidence."
            ),
            style="CardText.TLabel",
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(6, 8))
        probe_status = StringVar(value="Presentation Probe: IDLE")
        ttk.Label(
            box,
            textvariable=probe_status,
            style="CardText.TLabel",
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        probe_row = ttk.Frame(box, style="Card.TFrame")
        probe_row.pack(fill=X)
        probe_selection = StringVar(value="FULL")
        ttk.Combobox(
            probe_row,
            textvariable=probe_selection,
            values=("NATURALIZE", "VERBATIM", "VOICE", "STYLE", "FULL"),
            state="readonly",
            width=20,
        ).pack(side=LEFT, padx=(0, 8))
        ttk.Button(
            probe_row,
            text="RUN PRESENTATION PROBE",
            style="Secondary.TButton",
            command=lambda: self._presentation_probe_async(
                probe_selection.get(),
                probe_status,
            ),
        ).pack(side=LEFT)

        def refresh_provider_fields(*_args: object) -> None:
            selected = provider_labels[provider.get()]
            selected_transport = transport_labels[transport.get()]
            if selected == "yandex":
                qwen_fields.pack_forget()
                yandex_fields.pack(fill=X, before=buttons)
                tool_button.state(["disabled"])
            else:
                yandex_fields.pack_forget()
                qwen_fields.pack(fill=X, before=buttons)
                tool_button.state(["!disabled"] if selected_transport == "direct" else ["disabled"])

            if selected_transport == "srs":
                srs_fields.pack(fill=X, before=buttons, pady=(8, 4))
            else:
                srs_fields.pack_forget()

            if selected == "qwen_realtime" and selected_transport == "srs":
                compatibility_status.set(
                    "Qwen + SRS Radio is not available in v0.1. Select Direct Audio or Yandex."
                )
                live_start_button.state(["disabled"])
            else:
                compatibility_status.set(
                    "SUPPORTED — provider and transport are selected independently."
                )
                live_start_button.state(["!disabled"])

        provider.trace_add("write", refresh_provider_fields)
        transport.trace_add("write", refresh_provider_fields)
        refresh_provider_fields()
        generation = self._build_qwen_controls(box)
        self._realtime_live_poll(
            live_status,
            orion_srs_status,
            lambda: transport_labels[transport.get()],
            generation,
        )
        self._test_evidence_poll(
            test_evidence_status,
            reveal_test_evidence_button,
            generation,
        )
        self._presentation_probe_poll(probe_status, generation)
        self._hybrid_probe_poll(hybrid_status, generation)
        self._live_golden_poll(live_golden_status, generation)
        self._srs_process_poll(
            srs_server_path,
            srs_client_path,
            srs_server_status,
            srs_client_status,
            generation,
        )

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
        config = self._cloud_voice_store().load()
        return self._realtime_start_payload(
            config,
            self._current_qwen_api_key(),
            self._current_yandex_api_key(),
            self._current_srs_eam_password(),
        )

    @staticmethod
    def _realtime_start_payload(
        config: CloudVoiceConfig,
        qwen_api_key: str,
        yandex_api_key: str,
        srs_eam_password: str = "",
    ) -> dict[str, object]:
        transport = config.voice_transport.strip().casefold()
        if transport not in {"direct", "srs"}:
            raise ValueError(f"Unsupported voice transport: {config.voice_transport}")
        if config.cloud_provider != "yandex" and transport == "srs":
            raise ValueError("Qwen + SRS Radio is not available in v0.1")
        if config.cloud_provider == "yandex":
            key = yandex_api_key.strip()
            if not key:
                raise ValueError("Yandex API key is required")
            if not config.yandex_folder_id.strip():
                raise ValueError("Yandex Folder ID is required")
            payload: dict[str, object] = {
                "provider": "yandex",
                "transport": transport,
                "api_key": key,
                "folder_id": config.yandex_folder_id,
            }
            if transport == "srs":
                password = srs_eam_password.strip()
                if not password:
                    raise ValueError("SRS EAM password is required")
                if not config.srs_host.strip():
                    raise ValueError("SRS Server Host is required")
                payload["srs"] = {
                    "host": config.srs_host.strip(),
                    "port": config.srs_port,
                    "eam_password": password,
                }
            return payload
        return {
            "provider": "qwen",
            "transport": "direct",
            **LauncherCloudVoiceSectionsMixin._qwen_start_payload(config, qwen_api_key),
        }

    def _hardware_ai_session_toggle(self) -> None:
        try:
            result = self._realtime_session_controller.toggle(self._hardware_start_payload)
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

    @staticmethod
    def _selected_test_evidence_identity(
        config: CloudVoiceConfig,
        live_status: Mapping[str, object],
    ) -> tuple[str, str]:
        active_state = str(live_status.get("state") or "").casefold()
        if active_state in {"starting", "connected", "streaming"}:
            provider = str(live_status.get("provider") or "").casefold()
            transport = str(live_status.get("transport") or "").casefold()
        else:
            provider = config.cloud_provider.strip().casefold()
            transport = config.voice_transport.strip().casefold()
        if provider == "qwen_realtime":
            provider = "qwen"
        if provider not in {"qwen", "yandex"}:
            raise ValueError("Cannot determine the active realtime provider safely")
        if transport not in {"direct", "srs"}:
            raise ValueError("Cannot determine the active realtime transport safely")
        if provider == "qwen" and transport != "direct":
            raise ValueError("Qwen + SRS Radio is not available in v0.1")
        return provider, transport

    def _start_test_evidence(self, config: CloudVoiceConfig) -> dict[str, object]:
        current = self._test_evidence_status()
        if bool(current.get("active")):
            return {**current, "already_active": True}
        live_status = self._realtime_core_json("/v1/realtime/live/status")
        provider, transport = self._selected_test_evidence_identity(config, live_status)
        return self._realtime_core_json(
            "/v1/realtime/test-evidence/start",
            method="POST",
            payload={"provider": provider, "transport": transport},
        )

    def _test_evidence_status(self) -> dict[str, object]:
        return self._realtime_core_json("/v1/realtime/test-evidence/status")

    def _presentation_probe_status(self) -> dict[str, object]:
        return self._realtime_core_json(
            "/v1/realtime/yandex/presentation-probe/status"
        )

    def _start_presentation_probe(self, selection: str) -> dict[str, object]:
        return self._realtime_core_json(
            "/v1/realtime/yandex/presentation-probe/start",
            method="POST",
            payload={"selection": selection.strip().casefold()},
        )

    def _presentation_probe_async(
        self,
        selection: str,
        status_var: StringVar,
    ) -> None:
        generation = self._qwen_view_generation

        def worker() -> None:
            try:
                result = self._start_presentation_probe(selection)
                text = format_presentation_probe_status(result)
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
                text = f"Presentation Probe: ERROR — {type(exc).__name__}: {exc}"
            self._schedule_qwen_ui(0, lambda: status_var.set(text), generation)

        threading.Thread(
            target=worker,
            name="orion-presentation-probe-start",
            daemon=True,
        ).start()

    def _hybrid_probe_status(self) -> dict[str, object]:
        return self._realtime_core_json(
            "/v1/realtime/yandex/hybrid-presentation-probe/status"
        )

    def _live_golden_status(self) -> dict[str, object]:
        return self._realtime_core_json(
            "/v1/realtime/live-golden-conversation/status"
        )

    def _live_golden_start_async(
        self,
        capture_audio: bool,
        status_var: StringVar,
    ) -> None:
        generation = self._qwen_view_generation

        def worker() -> None:
            try:
                result = self._realtime_core_json(
                    "/v1/realtime/live-golden-conversation/start",
                    method="POST",
                    payload={"capture_response_audio": capture_audio},
                )
                text = format_live_golden_status(result)
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
                text = f"Live Golden: FAIL — {type(exc).__name__}: {exc}"
            self._schedule_qwen_ui(0, lambda: status_var.set(text), generation)

        threading.Thread(
            target=worker,
            name="orion-live-golden-start",
            daemon=True,
        ).start()

    def _live_golden_stop_async(self, status_var: StringVar) -> None:
        generation = self._qwen_view_generation

        def worker() -> None:
            try:
                result = self._realtime_core_json(
                    "/v1/realtime/live-golden-conversation/stop",
                    method="POST",
                )
                text = format_live_golden_status(result)
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
                text = f"Live Golden: FAIL — {type(exc).__name__}: {exc}"
            self._schedule_qwen_ui(0, lambda: status_var.set(text), generation)

        threading.Thread(
            target=worker,
            name="orion-live-golden-stop",
            daemon=True,
        ).start()

    def _live_golden_review_async(
        self,
        result: str,
        status_var: StringVar,
    ) -> None:
        generation = self._qwen_view_generation

        def worker() -> None:
            try:
                response = self._realtime_core_json(
                    "/v1/realtime/live-golden-conversation/review",
                    method="POST",
                    payload={"result": result.strip().casefold()},
                )
                text = format_live_golden_status(response)
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
                text = f"Live Golden: FAIL — {type(exc).__name__}: {exc}"
            self._schedule_qwen_ui(0, lambda: status_var.set(text), generation)

        threading.Thread(
            target=worker,
            name="orion-live-golden-review",
            daemon=True,
        ).start()

    def _start_hybrid_probe(self, capture_audio: bool) -> dict[str, object]:
        return self._realtime_core_json(
            "/v1/realtime/yandex/hybrid-presentation-probe/start",
            method="POST",
            payload={"capture_synthetic_audio": capture_audio},
        )

    def _hybrid_probe_async(self, capture_audio: bool, status_var: StringVar) -> None:
        generation = self._qwen_view_generation

        def worker() -> None:
            try:
                result = self._start_hybrid_probe(capture_audio)
                text = format_hybrid_probe_status(result)
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
                text = f"Hybrid Probe: FAIL — {type(exc).__name__}: {exc}"
            self._schedule_qwen_ui(0, lambda: status_var.set(text), generation)

        threading.Thread(target=worker, name="orion-hybrid-probe-start", daemon=True).start()

    def _hybrid_review_async(self, result: str, status_var: StringVar) -> None:
        generation = self._qwen_view_generation

        def worker() -> None:
            try:
                response = self._realtime_core_json(
                    "/v1/realtime/yandex/hybrid-presentation-probe/review",
                    method="POST",
                    payload={"result": result.strip().casefold()},
                )
                text = format_hybrid_probe_status(response)
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
                text = f"Hybrid Probe: FAIL — {type(exc).__name__}: {exc}"
            self._schedule_qwen_ui(0, lambda: status_var.set(text), generation)

        threading.Thread(target=worker, name="orion-hybrid-probe-review", daemon=True).start()

    def _stop_test_evidence(self) -> dict[str, object]:
        return self._realtime_core_json(
            "/v1/realtime/test-evidence/stop-export",
            method="POST",
        )

    def _start_test_evidence_async(
        self,
        config: CloudVoiceConfig,
        status_var: StringVar,
    ) -> None:
        generation = self._qwen_view_generation

        def worker() -> None:
            try:
                result = self._start_test_evidence(config)
                text = format_test_evidence_status(result)
                if bool(result.get("already_active")):
                    text += " — already active"
                self._schedule_qwen_ui(0, lambda: status_var.set(text), generation)
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
                text = f"Test Session: ERROR — {type(exc).__name__}: {exc}"
                self._schedule_qwen_ui(0, lambda: status_var.set(text), generation)

        threading.Thread(target=worker, name="orion-test-evidence-start", daemon=True).start()

    def _stop_test_evidence_async(
        self,
        status_var: StringVar,
        reveal_button: ttk.Button,
    ) -> None:
        generation = self._qwen_view_generation

        def worker() -> None:
            try:
                result = self._stop_test_evidence()
                export_path = str(result.get("export_path") or "").strip()
                if not export_path:
                    raise RuntimeError("ORION Core did not return an evidence export path")

                def apply_success() -> None:
                    self._last_test_evidence_export = export_path
                    status_var.set(f"Test Session: OFF — Exported: {export_path}")
                    reveal_button.state(["!disabled"])
                    messagebox.showinfo(
                        "ORION Test Evidence",
                        f"Test recording stopped.\n\nExport: {export_path}",
                        parent=self.root,
                    )

                self._schedule_qwen_ui(0, apply_success, generation)
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
                text = f"Test Session: ERROR — {type(exc).__name__}: {exc}"
                self._schedule_qwen_ui(0, lambda: status_var.set(text), generation)

        threading.Thread(target=worker, name="orion-test-evidence-stop", daemon=True).start()

    def _open_last_test_evidence_export(self) -> None:
        export_path = str(getattr(self, "_last_test_evidence_export", "")).strip()
        try:
            if not export_path:
                raise ValueError("No Test Evidence export is available")
            directory = Path(export_path).resolve().parent
            if not directory.is_dir():
                raise FileNotFoundError(f"Export folder does not exist: {directory}")
            startfile = getattr(os, "startfile", None)
            if not callable(startfile):
                raise RuntimeError("Windows folder reveal is unavailable")
            startfile(str(directory))
        except (OSError, ValueError, RuntimeError) as exc:
            messagebox.showerror("ORION Test Evidence", str(exc), parent=self.root)

    def _test_evidence_poll(
        self,
        status_var: StringVar,
        reveal_button: ttk.Button,
        generation: int,
    ) -> None:
        if not self._qwen_view_lifecycle.is_alive(generation):
            return

        def worker() -> None:
            try:
                result = self._test_evidence_status()
            except Exception:
                result = None
            if result is not None:
                def apply() -> None:
                    status_var.set(format_test_evidence_status(result))
                    export_path = str(result.get("last_export_path") or "").strip()
                    if export_path:
                        self._last_test_evidence_export = export_path
                        reveal_button.state(["!disabled"])
                    else:
                        reveal_button.state(["disabled"])

                self._schedule_qwen_ui(0, apply, generation)

        threading.Thread(target=worker, name="orion-test-evidence-status", daemon=True).start()
        self._schedule_qwen_ui(
            1000,
            lambda: self._test_evidence_poll(status_var, reveal_button, generation),
            generation,
        )

    def _presentation_probe_poll(
        self,
        status_var: StringVar,
        generation: int,
    ) -> None:
        if not self._qwen_view_lifecycle.is_alive(generation):
            return

        def worker() -> None:
            try:
                result = self._presentation_probe_status()
            except Exception:
                result = None
            if result is not None:
                text = format_presentation_probe_status(result)
                self._schedule_qwen_ui(0, lambda: status_var.set(text), generation)

        threading.Thread(
            target=worker,
            name="orion-presentation-probe-status",
            daemon=True,
        ).start()
        self._schedule_qwen_ui(
            1000,
            lambda: self._presentation_probe_poll(status_var, generation),
            generation,
        )

    def _hybrid_probe_poll(self, status_var: StringVar, generation: int) -> None:
        if not self._qwen_view_lifecycle.is_alive(generation):
            return

        def worker() -> None:
            try:
                result = self._hybrid_probe_status()
            except Exception:
                result = None
            if result is not None:
                text = format_hybrid_probe_status(result)
                self._schedule_qwen_ui(0, lambda: status_var.set(text), generation)

        threading.Thread(target=worker, name="orion-hybrid-probe-status", daemon=True).start()
        self._schedule_qwen_ui(
            1000,
            lambda: self._hybrid_probe_poll(status_var, generation),
            generation,
        )

    def _live_golden_poll(self, status_var: StringVar, generation: int) -> None:
        if not self._qwen_view_lifecycle.is_alive(generation):
            return

        def worker() -> None:
            try:
                result = self._live_golden_status()
            except Exception:
                result = None
            if result is not None:
                text = format_live_golden_status(result)
                self._schedule_qwen_ui(0, lambda: status_var.set(text), generation)

        threading.Thread(
            target=worker,
            name="orion-live-golden-status",
            daemon=True,
        ).start()
        self._schedule_qwen_ui(
            1000,
            lambda: self._live_golden_poll(status_var, generation),
            generation,
        )

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

        ttk.Label(controls, text="AI SESSION TOGGLE", style="CardTitle.TLabel").pack(anchor="w")
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

    def _select_srs_executable(self, kind: SrsProcessKind, variable: Any) -> None:
        executable = "SRS-Server.exe" if kind is SrsProcessKind.SERVER else "SR-ClientRadio.exe"
        selected = filedialog.askopenfilename(
            parent=self.root,
            title=f"Select {executable}",
            filetypes=((executable, executable), ("Executable", "*.exe")),
        )
        if selected:
            variable.set(selected)

    def _start_srs_process_async(
        self,
        kind: SrsProcessKind,
        server_path: str,
        client_path: str,
        server_status: StringVar,
        client_status: StringVar,
    ) -> None:
        generation = self._qwen_view_generation

        def publish(status: SrsProcessStatus) -> None:
            variable = server_status if status.kind is SrsProcessKind.SERVER else client_status
            self._schedule_qwen_ui(
                0,
                lambda: variable.set(format_srs_process_status(status)),
                generation,
            )

        def worker() -> None:
            if kind is SrsProcessKind.SERVER:
                self._srs_process_controller.start_server(server_path, on_status=publish)
            else:
                self._srs_process_controller.start_client(
                    client_path,
                    server_path=server_path,
                    on_status=publish,
                )

        threading.Thread(
            target=worker,
            name=f"orion-srs-{kind.value}-start",
            daemon=True,
        ).start()

    def _srs_process_poll(
        self,
        server_path: StringVar,
        client_path: StringVar,
        server_status: StringVar,
        client_status: StringVar,
        generation: int,
    ) -> None:
        if not self._qwen_view_lifecycle.is_alive(generation):
            return
        configured_server = server_path.get()
        configured_client = client_path.get()

        def worker() -> None:
            server = self._srs_process_controller.status(
                SrsProcessKind.SERVER,
                configured_server,
            )
            client = self._srs_process_controller.status(
                SrsProcessKind.CLIENT,
                configured_client,
            )

            def apply() -> None:
                server_status.set(format_srs_process_status(server))
                client_status.set(format_srs_process_status(client))
                if not server_path.get().strip() and server.executable_path:
                    server_path.set(server.executable_path)
                if not client_path.get().strip() and client.executable_path:
                    client_path.set(client.executable_path)

            self._schedule_qwen_ui(0, apply, generation)

        threading.Thread(target=worker, name="orion-srs-process-status", daemon=True).start()
        self._schedule_qwen_ui(
            2500,
            lambda: self._srs_process_poll(
                server_path,
                client_path,
                server_status,
                client_status,
                generation,
            ),
            generation,
        )

    def _realtime_live_async(
        self,
        config: CloudVoiceConfig,
        qwen_api_key: str,
        yandex_api_key: str,
        srs_eam_password: str,
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
                        lambda: self._realtime_start_payload(
                            config,
                            qwen_api_key,
                            yandex_api_key,
                            srs_eam_password,
                        )
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

    def _realtime_live_poll(
        self,
        live_status: StringVar,
        orion_srs_status: StringVar,
        selected_transport: Callable[[], str],
        generation: int,
    ) -> None:
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

            def apply() -> None:
                live_status.set(f"{prefix}{state} — {message}{suffix}")
                if selected_transport() == "srs":
                    orion_srs_status.set(format_orion_srs_status(result))
                else:
                    orion_srs_status.set("ORION SRS: NOT CONNECTED")

            self._schedule_qwen_ui(
                0,
                apply,
                generation,
            )

        threading.Thread(target=worker, name="orion-realtime-live-status", daemon=True).start()
        self._schedule_qwen_ui(
            750,
            lambda: self._realtime_live_poll(
                live_status,
                orion_srs_status,
                selected_transport,
                generation,
            ),
            generation,
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
