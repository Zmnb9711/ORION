"""Tkinter entry point for the standalone Yandex Realtime reference tester."""

from __future__ import annotations

import argparse
import json
import queue
import sys
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from yandex_reference_core import (
    APP_NAME,
    AudioDevice,
    DEFAULT_LANGUAGE,
    DEFAULT_MODEL,
    DEFAULT_VOICE,
    SessionConfig,
    YandexReferenceSession,
    list_audio_devices,
    write_diagnostic_report,
)

LANGUAGE_LABEL = "Russian (ru-RU)"


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


class TesterApp:
    def __init__(
        self,
        root: tk.Tk,
        *,
        device_lister: Callable[[], tuple[list[AudioDevice], list[AudioDevice]]] = list_audio_devices,
        session_factory: Callable[..., YandexReferenceSession] = YandexReferenceSession,
        poll_events: bool = True,
    ) -> None:
        self.root = root
        self.base_dir = app_root()
        self.logs_dir = self.base_dir / "logs"
        self.device_lister = device_lister
        self.session_factory = session_factory
        self.ui_events: queue.Queue[tuple[str, dict[str, object]]] = queue.Queue()
        self.session: YandexReferenceSession | None = None
        self.inputs: list[AudioDevice] = []
        self.outputs: list[AudioDevice] = []
        self._poll_after_id: str | None = None
        self._closing = False
        self._close_deadline = 0.0

        root.title(APP_NAME)
        root.geometry("790x850")
        root.minsize(720, 740)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self.refresh_devices(initial=True)
        if poll_events:
            self._poll_after_id = self.root.after(100, self._poll_events)

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=APP_NAME, font=("Segoe UI", 16, "bold")).pack(
            anchor="w", pady=(0, 12)
        )

        connection = ttk.LabelFrame(outer, text="Connection", padding=10)
        connection.pack(fill="x")
        self.api_key = self._row_entry(connection, 0, "API Key:", show="•")
        self.folder_id = self._row_entry(connection, 1, "Folder ID:")
        self.model = self._row_entry(connection, 2, "Model:")
        self.model.insert(0, DEFAULT_MODEL)
        self.voice = self._row_entry(connection, 3, "Voice:")
        self.voice.insert(0, DEFAULT_VOICE)
        self.language = self._row_combo(connection, 4, "Language:", [LANGUAGE_LABEL])
        self.language.set(LANGUAGE_LABEL)

        audio = ttk.LabelFrame(outer, text="Audio devices", padding=10)
        audio.pack(fill="x", pady=(10, 0))
        self.input_device = self._row_combo(audio, 0, "Input device:", [])
        self.output_device = self._row_combo(audio, 1, "Output device:", [])
        ttk.Button(audio, text="REFRESH DEVICES", command=self.refresh_devices).grid(
            row=2, column=1, sticky="w", pady=(6, 0)
        )

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=10)
        self.start_button = ttk.Button(actions, text="START SESSION", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(
            actions, text="STOP SESSION", command=self.stop, state="disabled"
        )
        self.stop_button.pack(side="left", padx=8)
        ttk.Label(actions, text="Status:").pack(side="left", padx=(18, 5))
        self.status = tk.StringVar(value="Disconnected")
        ttk.Label(actions, textvariable=self.status, font=("Segoe UI", 10, "bold")).pack(
            side="left"
        )

        event_box = ttk.LabelFrame(outer, text="Live Events", padding=6)
        event_box.pack(fill="both", expand=True)
        self.events = tk.Text(
            event_box, height=15, wrap="none", state="disabled", font=("Consolas", 9)
        )
        scroll = ttk.Scrollbar(event_box, orient="vertical", command=self.events.yview)
        self.events.configure(yscrollcommand=scroll.set)
        self.events.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        metrics = ttk.LabelFrame(outer, text="Metrics (latest response)", padding=10)
        metrics.pack(fill="x", pady=(10, 0))
        names = [
            ("first_audio_latency_ms", "First audio latency"),
            ("delta_count", "Audio delta count"),
            ("total_audio_duration_ms", "Total audio duration"),
            ("max_delta_gap_ms", "Max delta gap"),
            ("average_delta_gap_ms", "Average delta gap"),
            ("response_completed", "Response completed"),
            ("websocket_close", "WebSocket close"),
        ]
        self.metric_vars: dict[str, tk.StringVar] = {}
        for row, (key, label) in enumerate(names):
            ttk.Label(metrics, text=f"{label}:").grid(
                row=row, column=0, sticky="w", padx=(0, 12)
            )
            variable = tk.StringVar(value="-")
            self.metric_vars[key] = variable
            ttk.Label(metrics, textvariable=variable).grid(row=row, column=1, sticky="w")

        ttk.Button(
            outer, text="EXPORT DIAGNOSTIC REPORT", command=self.export_report
        ).pack(anchor="w", pady=(10, 0))

    @staticmethod
    def _row_entry(parent: ttk.Widget, row: int, label: str, show: str | None = None) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
        entry = ttk.Entry(parent, width=66, show=show or "")
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        parent.columnconfigure(1, weight=1)
        return entry

    @staticmethod
    def _row_combo(
        parent: ttk.Widget, row: int, label: str, values: list[str]
    ) -> ttk.Combobox:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
        combo = ttk.Combobox(parent, values=values, state="readonly", width=63)
        combo.grid(row=row, column=1, sticky="ew", pady=3)
        parent.columnconfigure(1, weight=1)
        return combo

    def refresh_devices(self, initial: bool = False) -> None:
        old_input = self._selected_device(self.input_device, self.inputs)
        old_output = self._selected_device(self.output_device, self.outputs)
        try:
            new_inputs, new_outputs = self.device_lister()
        except Exception as exc:
            self.status.set("AUDIO DEVICE ERROR")
            self._append_event("audio.devices.error", {"message": str(exc)})
            return
        self.inputs, self.outputs = new_inputs, new_outputs
        self.input_device["values"] = [device.label for device in self.inputs]
        self.output_device["values"] = [device.label for device in self.outputs]
        self._restore_exact_selection(
            self.input_device, self.inputs, old_input, "input", initial
        )
        self._restore_exact_selection(
            self.output_device, self.outputs, old_output, "output", initial
        )
        self._append_event(
            "audio.devices.refreshed",
            {"inputs": len(self.inputs), "outputs": len(self.outputs)},
        )

    @staticmethod
    def _selected_device(
        combo: ttk.Combobox, devices: list[AudioDevice]
    ) -> AudioDevice | None:
        position = combo.current()
        return devices[position] if 0 <= position < len(devices) else None

    def _restore_exact_selection(
        self,
        combo: ttk.Combobox,
        devices: list[AudioDevice],
        previous: AudioDevice | None,
        direction: str,
        initial: bool,
    ) -> None:
        if initial:
            if devices:
                combo.current(0)
            else:
                combo.set("")
            return
        if previous is None:
            combo.set("")
            return
        position = next(
            (
                index
                for index, device in enumerate(devices)
                if device.identity() == previous.identity()
            ),
            None,
        )
        if position is None:
            combo.set("")
            self._append_event(
                "audio.device.selection_invalidated",
                {
                    "direction": direction,
                    "device_index": previous.index,
                    "name": previous.name,
                    "host_api": previous.hostapi_name,
                },
            )
        else:
            combo.current(position)

    def start(self) -> None:
        if self.session and self.session.thread and self.session.thread.is_alive():
            return
        try:
            config = self._current_config()
        except ValueError as exc:
            self.status.set("SESSION CONFIG ERROR")
            self._append_event(
                "client.error", {"category": "SESSION CONFIG ERROR", "message": str(exc)}
            )
            return
        self._clear_metrics()
        self.session = self.session_factory(config, self._queue_event)
        self.session.start()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

    def _current_config(self) -> SessionConfig:
        input_device = self._selected_device(self.input_device, self.inputs)
        output_device = self._selected_device(self.output_device, self.outputs)
        if input_device is None:
            raise ValueError("Select an input audio device.")
        if output_device is None:
            raise ValueError("Select an output audio device.")
        config = SessionConfig(
            api_key=self.api_key.get().strip(),
            folder_id=self.folder_id.get().strip(),
            model=self.model.get().strip() or DEFAULT_MODEL,
            voice=self.voice.get().strip() or DEFAULT_VOICE,
            language=DEFAULT_LANGUAGE,
            input_device=input_device,
            output_device=output_device,
        )
        config.validate()
        return config

    def stop(self) -> None:
        if self.session is not None:
            self.session.stop()
        self.stop_button.configure(state="disabled")

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._close_deadline = time.monotonic() + 2.0
        if self._poll_after_id is not None:
            try:
                self.root.after_cancel(self._poll_after_id)
            except tk.TclError:
                pass
            self._poll_after_id = None
        if self.session is not None:
            self.session.stop()
        self._finish_close()

    def _finish_close(self) -> None:
        thread = self.session.thread if self.session is not None else None
        if thread is not None and thread.is_alive() and time.monotonic() < self._close_deadline:
            self.root.after(50, self._finish_close)
            return
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _queue_event(self, event: str, fields: dict[str, object]) -> None:
        self.ui_events.put((event, fields))

    def _poll_events(self) -> None:
        if self._closing:
            return
        try:
            while True:
                event, fields = self.ui_events.get_nowait()
                if event == "status":
                    value = str(fields.get("value", ""))
                    self.status.set(value)
                    if value in {
                        "Disconnected",
                        "AUTH ERROR",
                        "FOLDER/MODEL ERROR",
                        "WEBSOCKET ERROR",
                        "SESSION CONFIG ERROR",
                        "INPUT DEVICE ERROR",
                        "OUTPUT DEVICE ERROR",
                        "UNSUPPORTED AUDIO FORMAT",
                        "SERVER ERROR",
                    }:
                        self.start_button.configure(state="normal")
                        self.stop_button.configure(state="disabled")
                else:
                    self._append_event(event, fields)
                    self._update_metrics(event, fields)
        except queue.Empty:
            pass
        if not self._closing:
            self._poll_after_id = self.root.after(100, self._poll_events)

    def _append_event(self, event: str, fields: dict[str, object]) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if event == "conversation.item.input_audio_transcription.completed":
            line = f"{timestamp}  USER TRANSCRIPT: {fields.get('transcript', '')}"
        elif event in {
            "response.output_audio_transcript.done",
            "response.output_text.done",
        }:
            line = f"{timestamp}  ASSISTANT: {fields.get('transcript', '')}"
        else:
            details = " ".join(
                f"{key}={value}" for key, value in fields.items() if value is not None
            )
            line = f"{timestamp}  {event}{'  ' + details if details else ''}"
        self.events.configure(state="normal")
        self.events.insert("end", line + "\n")
        self.events.see("end")
        self.events.configure(state="disabled")

    def _update_metrics(self, event: str, fields: dict[str, object]) -> None:
        if event == "response.output_audio.delta":
            self.metric_vars["delta_count"].set(str(fields.get("delta_index", "-")))
            latency = fields.get("first_audio_latency_ms")
            if latency is not None:
                self.metric_vars["first_audio_latency_ms"].set(f"{latency} ms")
        elif event == "response.done":
            for key in (
                "delta_count",
                "total_audio_duration_ms",
                "max_delta_gap_ms",
                "average_delta_gap_ms",
            ):
                value = fields.get(key)
                suffix = " ms" if key.endswith("_ms") and value is not None else ""
                self.metric_vars[key].set(f"{value}{suffix}" if value is not None else "-")
            self.metric_vars["response_completed"].set(
                "YES" if fields.get("response_completed") else "NO"
            )
        elif event == "websocket.closed":
            code = fields.get("code")
            reason = fields.get("reason") or ""
            state = fields.get("state") or "closed"
            self.metric_vars["websocket_close"].set(
                f"{state}; code={code if code is not None else 'unavailable'}"
                f"{'; reason=' + str(reason) if reason else ''}"
            )

    def _clear_metrics(self) -> None:
        for variable in self.metric_vars.values():
            variable.set("-")

    def export_report(self) -> None:
        if self.session is None:
            self._append_event(
                "diagnostic.export.unavailable", {"message": "No session has been started."}
            )
            return
        default = f"yandex-realtime-diagnostic-{datetime.now():%Y%m%d-%H%M%S}.txt"
        selected = filedialog.asksaveasfilename(
            title="Export Diagnostic Report",
            initialdir=self.logs_dir,
            initialfile=default,
            defaultextension=".txt",
            filetypes=[("Text report", "*.txt")],
        )
        if not selected:
            return
        try:
            write_diagnostic_report(Path(selected), self.session.diagnostic_text())
        except OSError as exc:
            self.status.set("DIAGNOSTIC EXPORT ERROR")
            self._append_event("diagnostic.export.failed", {"message": str(exc)})
            return
        self._append_event("diagnostic.export.completed", {"path": selected})
        messagebox.showinfo(APP_NAME, f"Report saved:\n{selected}")


def main() -> None:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--gui-smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.smoke_test:
        inputs, outputs = list_audio_devices()
        print(
            json.dumps(
                {"inputs": len(inputs), "outputs": len(outputs), "root": str(app_root())},
                ensure_ascii=False,
            )
        )
        return
    root = tk.Tk()
    app = TesterApp(root)
    if args.gui_smoke_test:
        root.withdraw()
        root.after(200, app.close)
    root.mainloop()


if __name__ == "__main__":
    main()
