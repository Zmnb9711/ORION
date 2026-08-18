from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import LEFT, X, StringVar, messagebox
from tkinter import ttk

from orion.qwen_realtime_provider import QwenRealtimeConfig, QwenRealtimeProvider


@dataclass(slots=True)
class CloudVoiceConfig:
    voice_backend: str = "local_whisper"
    cloud_provider: str = "qwen_realtime"
    fallback_backend: str = "local_whisper"
    qwen_region: str = "singapore"
    qwen_workspace_id: str = ""
    qwen_model: str = "qwen3.5-omni-flash-realtime"


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


class LauncherCloudVoiceSectionsMixin:
    """ADR-004 Settings → Voice surface layered onto the field-confirmed Launcher."""

    def _cloud_voice_store(self) -> CloudVoiceConfigStore:
        return CloudVoiceConfigStore(self.runtime_dir)

    def _current_qwen_api_key(self) -> str:
        """Return the session key without losing it when Tk pages are rebuilt."""
        return str(getattr(self, "_qwen_api_key", "") or os.environ.get("DASHSCOPE_API_KEY", "")).strip()

    def _remember_qwen_api_key(self, value: str) -> None:
        """Keep the edited key for the lifetime of this Launcher process."""
        self._qwen_api_key = value.strip()

    def _page_settings(self) -> None:
        super()._page_settings()
        config = self._cloud_voice_store().load()

        ttk.Separator(self.content, orient="horizontal").pack(fill=X, pady=(24, 18))
        ttk.Label(self.content, text="VOICE", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            self.content,
            text=(
                "Choose the ORION voice backend. Cloud Realtime is experimental; the field-confirmed "
                "whisper.cpp path remains installed and available as fallback."
            ),
            style="Muted.TLabel",
            wraplength=820,
            justify="left",
        ).pack(anchor="w", pady=(4, 12))

        backend_labels = {"Local / Whisper.cpp": "local_whisper", "Cloud Realtime": "cloud_realtime"}
        provider_labels = {"Qwen Realtime": "qwen_realtime"}
        region_labels = {"Singapore": "singapore", "China (Beijing)": "beijing"}
        reverse_backend = {value: label for label, value in backend_labels.items()}
        reverse_provider = {value: label for label, value in provider_labels.items()}
        reverse_region = {value: label for label, value in region_labels.items()}

        backend = StringVar(value=reverse_backend.get(config.voice_backend, "Local / Whisper.cpp"))
        provider = StringVar(value=reverse_provider.get(config.cloud_provider, "Qwen Realtime"))
        region = StringVar(value=reverse_region.get(config.qwen_region, "Singapore"))
        workspace = StringVar(value=config.qwen_workspace_id)
        model = StringVar(value=config.qwen_model)
        api_key = StringVar(value=self._current_qwen_api_key())
        # Settings pages are destroyed/recreated during navigation. Mirror every
        # edit immediately into Launcher session memory, not only on SAVE.
        api_key.trace_add("write", lambda *_: self._remember_qwen_api_key(api_key.get()))
        fallback = StringVar(value="Local / Whisper.cpp")
        live_status = StringVar(value="STOPPED — Qwen live audio is not active")

        box = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        box.pack(fill=X)
        ttk.Label(box, text="VOICE BACKEND", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Combobox(box, textvariable=backend, values=tuple(backend_labels), state="readonly", width=42).pack(anchor="w", pady=(6, 12))
        ttk.Label(box, text="CLOUD PROVIDER", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Combobox(box, textvariable=provider, values=tuple(provider_labels), state="readonly", width=42).pack(anchor="w", pady=(6, 12))
        ttk.Label(box, text="REGION", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Combobox(box, textvariable=region, values=tuple(region_labels), state="readonly", width=42).pack(anchor="w", pady=(6, 12))
        ttk.Label(box, text="WORKSPACE ID", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Entry(box, textvariable=workspace, width=72).pack(anchor="w", fill=X, pady=(6, 12))
        ttk.Label(box, text="MODEL", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Entry(box, textvariable=model, width=72).pack(anchor="w", fill=X, pady=(6, 12))
        ttk.Label(box, text="API KEY", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Entry(box, textvariable=api_key, show="*", width=72).pack(anchor="w", fill=X, pady=(6, 12))
        ttk.Label(
            box,
            text="The API key is kept in memory for this Launcher session and is not written to cloud-voice.json.",
            style="CardText.TLabel",
        ).pack(anchor="w", pady=(0, 12))
        ttk.Label(box, text="FALLBACK", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Combobox(box, textvariable=fallback, values=("Local / Whisper.cpp",), state="readonly", width=42).pack(anchor="w", pady=(6, 12))
        ttk.Label(
            box,
            text=(
                "ADR-004 clean live path: selected microphone → ORION Core → Qwen Realtime → selected output. "
                "ATC/AWACS/JTAC/AAR tools remain disabled; whisper.cpp remains fallback."
            ),
            style="CardText.TLabel",
            wraplength=780,
            justify="left",
        ).pack(anchor="w")

        buttons = ttk.Frame(box, style="Card.TFrame")
        buttons.pack(fill=X, pady=(16, 0))

        def selected_config() -> CloudVoiceConfig:
            return CloudVoiceConfig(
                voice_backend=backend_labels[backend.get()],
                cloud_provider=provider_labels[provider.get()],
                fallback_backend="local_whisper",
                qwen_region=region_labels[region.get()],
                qwen_workspace_id=workspace.get().strip(),
                qwen_model=model.get().strip() or "qwen3.5-omni-flash-realtime",
            )

        def save() -> None:
            self._cloud_voice_store().save(selected_config())
            self._remember_qwen_api_key(api_key.get())
            messagebox.showinfo("ORION Voice", "Voice settings saved. API key kept in memory only.", parent=self.root)

        ttk.Button(buttons, text="SAVE VOICE SETTINGS", style="Primary.TButton", command=save).pack(side=LEFT, padx=(0, 8))
        ttk.Button(
            buttons,
            text="TEST CONNECTION",
            style="Secondary.TButton",
            command=lambda: self._qwen_smoke_async(selected_config(), api_key.get(), tool=False),
        ).pack(side=LEFT, padx=(0, 8))
        ttk.Button(
            buttons,
            text="TEST TOOL CALL",
            style="Secondary.TButton",
            command=lambda: self._qwen_smoke_async(selected_config(), api_key.get(), tool=True),
        ).pack(side=LEFT)

        ttk.Separator(box, orient="horizontal").pack(fill=X, pady=(18, 14))
        ttk.Label(box, text="QWEN LIVE REALTIME AUDIO", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(box, textvariable=live_status, style="CardText.TLabel", wraplength=780, justify="left").pack(anchor="w", pady=(6, 10))
        live_buttons = ttk.Frame(box, style="Card.TFrame")
        live_buttons.pack(fill=X)
        ttk.Button(
            live_buttons,
            text="START LIVE QWEN",
            style="Primary.TButton",
            command=lambda: self._qwen_live_async(selected_config(), api_key.get(), live_status, start=True),
        ).pack(side=LEFT, padx=(0, 8))
        ttk.Button(
            live_buttons,
            text="STOP LIVE QWEN",
            style="Secondary.TButton",
            command=lambda: self._qwen_live_async(selected_config(), api_key.get(), live_status, start=False),
        ).pack(side=LEFT)

        self._qwen_live_poll(live_status)

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

        def worker() -> None:
            try:
                if start:
                    if not key:
                        raise ValueError("Qwen API key is required")
                    payload: dict[str, object] = {
                        "api_key": key,
                        "workspace_id": config.qwen_workspace_id,
                        "region": config.qwen_region,
                        "model": config.qwen_model,
                        "voice": "Tina",
                    }
                    result = self._realtime_core_json("/v1/realtime/qwen/live/start", method="POST", payload=payload)
                else:
                    result = self._realtime_core_json("/v1/realtime/qwen/live/stop", method="POST")
                state = str(result.get("state", "unknown")).upper()
                message = str(result.get("message", ""))
                self.root.after(0, lambda: live_status.set(f"{state} — {message}"))
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
                self.root.after(0, lambda exc=exc: live_status.set(f"ERROR — {type(exc).__name__}: {exc}"))

        threading.Thread(target=worker, name="orion-qwen-live-control", daemon=True).start()

    def _qwen_live_poll(self, live_status: StringVar) -> None:
        def worker() -> None:
            try:
                result = self._realtime_core_json("/v1/realtime/qwen/live")
            except Exception:
                return
            state = str(result.get("state", "unknown")).upper()
            message = str(result.get("message", ""))
            input_chunks = int(result.get("input_chunks", 0) or 0)
            output_chunks = int(result.get("output_chunks", 0) or 0)
            suffix = "" if not (input_chunks or output_chunks) else f" | mic={input_chunks} qwen_audio={output_chunks}"
            self.root.after(0, lambda: live_status.set(f"{state} — {message}{suffix}"))

        threading.Thread(target=worker, name="orion-qwen-live-status", daemon=True).start()
        self.root.after(750, lambda: self._qwen_live_poll(live_status))

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
