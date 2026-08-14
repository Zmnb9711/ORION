from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from time import perf_counter
from tkinter import X, messagebox
from tkinter import ttk
from typing import Any
from uuid import uuid4

from orion.audio_hardware_test import AudioHardwareTester
from orion.windows_wasapi_backend import WasapiEndpoint


class LauncherConversationTestMixin:
    """Add the approved conversational Voice↔Core diagnostic to Test."""

    CONVERSATION_TIMEOUT_SECONDS = 120.0
    STT_POLL_MS = 750

    def _page_test(self) -> None:
        super()._page_test()

        stt_card = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        stt_card.pack(fill=X, pady=(12, 0))
        ttk.Label(stt_card, text="LOCAL SPEECH RECOGNITION", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            stt_card,
            text="Whisper medium runs locally on CPU. Prepare it once before the conversational audio test.",
            style="CardText.TLabel",
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(6, 8))
        self._stt_status_label = ttk.Label(stt_card, text="Checking Whisper medium…", style="CardText.TLabel")
        self._stt_status_label.pack(anchor="w", pady=(0, 6))
        self._stt_progress = ttk.Progressbar(stt_card, orient="horizontal", mode="determinate", maximum=100.0, length=520)
        self._stt_progress.pack(anchor="w", fill=X, pady=(0, 8))
        self._stt_prepare_button = ttk.Button(
            stt_card,
            text="PREPARE SPEECH RECOGNITION",
            style="Primary.TButton",
            command=self._prepare_speech_recognition,
        )
        self._stt_prepare_button.pack(anchor="w")

        card = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        card.pack(fill=X, pady=(12, 0))
        ttk.Label(card, text="CONVERSATIONAL AUDIO TEST", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            card,
            text='Press START, then say: “Привет, как дела?” ORION should answer: “Дела отлично. Связь установлена.”',
            style="CardText.TLabel",
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(6, 10))
        self._conversation_button = ttk.Button(
            card,
            text="START CONVERSATIONAL AUDIO TEST",
            style="Primary.TButton",
            command=self._run_conversational_audio_test,
        )
        self._conversation_button.pack(anchor="w")
        if not self.core.healthy():
            self._conversation_button.configure(state="disabled")
            self._stt_prepare_button.configure(state="disabled")
        else:
            self.root.after(50, self._poll_stt_status)

    def _new_test_log(self, test_name: str) -> Path:
        log_dir = self.runtime_dir / "test-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = log_dir / f"orion-test-{timestamp}-{uuid4().hex[:8]}.log"
        self._append_test_log(path, f"START test={test_name}")
        self._append_test_log(path, f"core_base_url={self.core.base_url}")
        return path

    @staticmethod
    def _append_test_log(path: Path, message: str) -> None:
        stamp = datetime.now().isoformat(timespec="milliseconds")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {message}\n")

    def _run_physical_audio_test(self, direction: str, endpoint_payload: dict[str, Any] | None) -> None:
        log_path = self._new_test_log(f"physical-{direction}")
        if endpoint_payload is None:
            self._append_test_log(log_path, "ERROR endpoint=unresolved")
            self._append_test_log(log_path, "END status=FAIL")
            messagebox.showwarning(
                "ORION Test",
                f"No active {direction} endpoint is resolved by Core\n\nTest log:\n{log_path}",
                parent=self.root,
            )
            return

        endpoint = WasapiEndpoint.model_validate(endpoint_payload)
        self._append_test_log(log_path, f"ENDPOINT id={endpoint.device_id!r} name={endpoint.name!r}")
        tester = AudioHardwareTester()
        started = perf_counter()
        try:
            result = tester.test_input(endpoint) if direction == "input" else tester.test_output(endpoint)
        except (ImportError, OSError, RuntimeError) as exc:
            elapsed_ms = (perf_counter() - started) * 1000.0
            self._append_test_log(log_path, f"ERROR elapsed_ms={elapsed_ms:.1f} exception={type(exc).__name__}: {exc}")
            self._append_test_log(log_path, "END status=FAIL")
            messagebox.showerror("ORION Test", f"{exc}\n\nTest log:\n{log_path}", parent=self.root)
            return

        elapsed_ms = (perf_counter() - started) * 1000.0
        self._append_test_log(log_path, f"RESULT elapsed_ms={elapsed_ms:.1f} ok={result.ok} message={result.message!r}")
        self._append_test_log(log_path, f"END status={'PASS' if result.ok else 'FAIL'}")
        text = f"{result.message}\n\nTest log:\n{log_path}"
        if result.ok:
            messagebox.showinfo("ORION Test", text, parent=self.root)
        else:
            messagebox.showwarning("ORION Test", text, parent=self.root)

    def _core_json(self, method: str, path: str, *, timeout: float = 5.0) -> Any:
        request = urllib.request.Request(f"{self.core.base_url}{path}", method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Core audio API unavailable: {exc}") from exc

    def _conversation_core_json(self) -> Any:
        return self._core_json(
            "POST",
            "/v1/windows-audio/test/conversation",
            timeout=self.CONVERSATION_TIMEOUT_SECONDS,
        )

    def _stt_status_text(self, payload: dict[str, Any]) -> str:
        if payload.get("ready"):
            return "READY — Whisper medium installed locally (CPU only)"
        if payload.get("error"):
            return f"FAILED — {payload['error']}"
        stage = str(payload.get("stage", "not_installed"))
        labels = {
            "not_installed": "NOT INSTALLED — press Prepare Speech Recognition",
            "starting": "Starting Whisper preparation…",
            "runtime": "Downloading whisper.cpp CPU runtime…",
            "runtime_verify": "Verifying whisper.cpp runtime…",
            "model": "Downloading Whisper medium model…",
            "model_verify": "Verifying Whisper medium model…",
            "ready": "READY — Whisper medium installed locally (CPU only)",
            "failed": "Whisper preparation failed",
        }
        text = labels.get(stage, stage.replace("_", " ").title())
        percent = payload.get("percent")
        downloaded = int(payload.get("downloaded_bytes") or 0)
        total = payload.get("total_bytes")
        if percent is not None:
            text += f" — {float(percent):.1f}%"
        if downloaded:
            mib = downloaded / (1024 * 1024)
            if total:
                text += f" ({mib:.0f}/{int(total) / (1024 * 1024):.0f} MiB)"
            else:
                text += f" ({mib:.0f} MiB)"
        return text

    def _apply_stt_status(self, payload: dict[str, Any]) -> None:
        label = getattr(self, "_stt_status_label", None)
        progress = getattr(self, "_stt_progress", None)
        prepare = getattr(self, "_stt_prepare_button", None)
        conversation = getattr(self, "_conversation_button", None)
        if label is None or progress is None or prepare is None or conversation is None:
            return
        label.configure(text=self._stt_status_text(payload))
        percent = payload.get("percent")
        progress.configure(value=float(percent) if percent is not None else 0.0)
        ready = bool(payload.get("ready"))
        running = bool(payload.get("running"))
        prepare.configure(state="disabled" if running or ready else "normal")
        conversation.configure(state="normal" if ready else "disabled")

    def _poll_stt_status(self) -> None:
        if not hasattr(self, "_stt_status_label"):
            return
        try:
            payload = self._core_json("GET", "/v1/windows-audio/stt/status", timeout=3.0)
        except RuntimeError as exc:
            if hasattr(self, "_stt_status_label"):
                self._stt_status_label.configure(text=str(exc))
            return
        self._apply_stt_status(payload)
        if payload.get("running"):
            self.root.after(self.STT_POLL_MS, self._poll_stt_status)

    def _prepare_speech_recognition(self) -> None:
        log_path = self._new_test_log("stt-prepare")
        self._append_test_log(log_path, "REQUEST method=POST path=/v1/windows-audio/stt/prepare")
        try:
            payload = self._core_json("POST", "/v1/windows-audio/stt/prepare", timeout=5.0)
        except RuntimeError as exc:
            self._append_test_log(log_path, f"ERROR {exc}")
            self._append_test_log(log_path, "END status=FAIL")
            if hasattr(self, "_stt_status_label"):
                self._stt_status_label.configure(text=str(exc))
            return
        self._append_test_log(log_path, f"STARTED stage={payload.get('stage')} running={bool(payload.get('running'))}")
        self._apply_stt_status(payload)
        self.root.after(self.STT_POLL_MS, self._poll_stt_status)

    def _run_conversational_audio_test(self) -> None:
        log_path = self._new_test_log("conversation")
        try:
            stt = self._core_json("GET", "/v1/windows-audio/stt/status", timeout=3.0)
        except RuntimeError as exc:
            self._append_test_log(log_path, f"ERROR STT status unavailable: {exc}")
            self._append_test_log(log_path, "END status=FAIL")
            return
        if not stt.get("ready"):
            self._append_test_log(log_path, f"ERROR stt_not_ready stage={stt.get('stage')!r}")
            self._append_test_log(log_path, "END status=FAIL")
            self._apply_stt_status(stt)
            return

        started = perf_counter()
        self._append_test_log(
            log_path,
            f"REQUEST method=POST path=/v1/windows-audio/test/conversation timeout_s={self.CONVERSATION_TIMEOUT_SECONDS:.1f}",
        )
        try:
            result = self._conversation_core_json()
        except RuntimeError as exc:
            elapsed_ms = (perf_counter() - started) * 1000.0
            self._append_test_log(log_path, f"ERROR elapsed_ms={elapsed_ms:.1f} exception={type(exc).__name__}: {exc}")
            self._append_test_log(log_path, "END status=FAIL")
            messagebox.showerror("ORION Audio Test", f"{exc}\n\nTest log:\n{log_path}", parent=self.root)
            return

        elapsed_ms = (perf_counter() - started) * 1000.0
        self._append_test_log(log_path, f"RESPONSE elapsed_ms={elapsed_ms:.1f} ok={bool(result.get('ok'))}")
        stages = result.get("stages", {})
        for key, value in stages.items():
            self._append_test_log(log_path, f"STAGE {key}={bool(value)}")
        recognized = str(result.get("recognized_text", "")).strip()
        if recognized:
            self._append_test_log(log_path, f"RECOGNIZED text={recognized!r}")
        self._append_test_log(log_path, f"MESSAGE {result.get('message', 'Audio test completed')}")
        self._append_test_log(log_path, f"END status={'PASS' if result.get('ok') else 'FAIL'}")

        ordered = (
            ("core_connected", "Core connected"),
            ("input_resolved", "Input resolved"),
            ("audio_captured", "Audio captured"),
            ("phrase_recognized", "Phrase recognized"),
            ("output_resolved", "Output resolved"),
            ("response_played", "Response played"),
        )
        details = "\n".join(f"{'PASS' if stages.get(key) else 'FAIL'} — {label}" for key, label in ordered)
        if recognized:
            details += f"\n\nRecognized: {recognized}"
        text = f"{result.get('message', 'Audio test completed')}\n\n{details}\n\nTest log:\n{log_path}"
        if result.get("ok"):
            messagebox.showinfo("ORION Audio Test", text, parent=self.root)
        else:
            messagebox.showwarning("ORION Audio Test", text, parent=self.root)
