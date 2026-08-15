from __future__ import annotations

from tkinter import BOTH, LEFT, X, StringVar, messagebox
from tkinter import ttk
from typing import Any

from orion.audio_hardware_test import AudioHardwareTester
from orion.launcher_core_client import LauncherCoreClient
from orion.windows_wasapi_backend import WasapiEndpoint


class LauncherAudioSectionsMixin:
    """Production Launcher sections for Core/audio foundation diagnostics."""

    NAV_KEYS = (
        "home",
        "fly",
        "mission",
        "modules",
        "test",
        "diagnostics",
        "providers",
        "updates",
        "settings",
        "logs",
        "about",
    )

    def nav_label(self, key: str) -> str:
        fixed = {"modules": "Modules", "test": "Test"}
        return fixed[key] if key in fixed else super().nav_label(key)

    def _core_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        timeout: float = 5.0,
    ) -> Any:
        return LauncherCoreClient(self.core.base_url).request(
            path,
            method=method,
            payload=payload,
            timeout=timeout,
        )

    def _audio_snapshot(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        inputs = self._core_json("/v1/windows-audio/wasapi/inputs")
        outputs = self._core_json("/v1/windows-audio/wasapi/outputs")
        state = self._core_json("/v1/windows-audio/selection")
        return list(inputs), list(outputs), dict(state)

    def _page_modules(self) -> None:
        hero = ttk.Frame(self.content, style="CardAlt.TFrame", padding=22)
        hero.pack(fill=X)
        ttk.Label(hero, text="ORION COMPONENTS", style="CardAltTitle.TLabel").pack(anchor="w")
        ttk.Label(hero, text="MODULES", style="Hero.TLabel").pack(anchor="w", pady=(8, 3))
        ttk.Label(
            hero,
            text="Installed ORION components and aircraft packages will be managed here. Modular install/remove is tracked separately from the current audio foundation milestone.",
            style="HeroMuted.TLabel",
            wraplength=780,
            justify="left",
        ).pack(anchor="w")
        row = ttk.Frame(self.content, style="Orion.TFrame")
        row.pack(fill=X, pady=(20, 0))
        modules = (
            ("ORION CORE", "Installed / managed independently from Launcher"),
            ("LAUNCHER", "Installed / single user-facing control surface"),
            ("DCS INTEGRATION", "Managed through ORION setup and repair"),
        )
        for index, (title, text) in enumerate(modules):
            card = self._card(row, title, text, wrap=260)
            card.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10 if index < len(modules) - 1 else 0))

    def _page_test(self) -> None:
        hero = ttk.Frame(self.content, style="CardAlt.TFrame", padding=22)
        hero.pack(fill=X)
        ttk.Label(hero, text="FUNCTIONAL VERIFICATION", style="CardAltTitle.TLabel").pack(anchor="w")
        ttk.Label(hero, text="TEST", style="Hero.TLabel").pack(anchor="w", pady=(8, 3))
        ttk.Label(
            hero,
            text="Run focused checks without leaving Launcher. This is the expandable diagnostics surface for Core, audio, DCS, Voice and ATC.",
            style="HeroMuted.TLabel",
            wraplength=800,
            justify="left",
        ).pack(anchor="w")

        core_ok = self.core.healthy()
        try:
            inputs, outputs, state = self._audio_snapshot() if core_ok else ([], [], {})
            selection = state.get("selection", {})
            resolved_in = state.get("resolved_input")
            resolved_out = state.get("resolved_output")
            audio_api_ok = core_ok
        except RuntimeError:
            inputs, outputs, state, selection, resolved_in, resolved_out = [], [], {}, {}, None, None
            audio_api_ok = False

        checks = [
            ("CORE CONNECTION", "PASS — Launcher is connected to ORION Core" if core_ok else "FAIL — Core is not reachable"),
            ("WINDOWS AUDIO DISCOVERY", f"PASS — {len(inputs)} input / {len(outputs)} output endpoints" if audio_api_ok else "FAIL — Core audio API unavailable"),
            ("MICROPHONE SELECTION", self._selection_text(selection.get("input_device_id", "default"), resolved_in)),
            ("OUTPUT SELECTION", self._selection_text(selection.get("output_device_id", "default"), resolved_out)),
            ("CORE AUDIO STATE", state.get("message", "Unavailable") if state else "Unavailable"),
        ]
        ttk.Label(self.content, text="CURRENT CHECKS", style="Section.TLabel").pack(anchor="w", pady=(22, 10))
        for title, text in checks:
            self._card(self.content, title, text, wrap=760).pack(fill=X, pady=(0, 8))

        footer = ttk.Frame(self.content, style="Orion.TFrame")
        footer.pack(fill=X, pady=(8, 0))
        ttk.Button(footer, text="RUN AGAIN", style="Primary.TButton", command=lambda: self.show_page("test")).pack(side=LEFT, padx=(0, 8))
        mic_button = ttk.Button(
            footer,
            text="TEST MICROPHONE",
            style="Secondary.TButton",
            command=lambda: self._run_physical_audio_test("input", resolved_in),
        )
        mic_button.pack(side=LEFT, padx=(0, 8))
        output_button = ttk.Button(
            footer,
            text="TEST OUTPUT",
            style="Secondary.TButton",
            command=lambda: self._run_physical_audio_test("output", resolved_out),
        )
        output_button.pack(side=LEFT)
        if resolved_in is None:
            mic_button.configure(state="disabled")
        if resolved_out is None:
            output_button.configure(state="disabled")

    @staticmethod
    def _selection_text(selected: str, resolved: dict[str, Any] | None) -> str:
        if resolved:
            return f"PASS — Core active: {resolved.get('name', selected)}"
        if selected == "default":
            return "WARNING — Windows Default selected; no active endpoint resolved"
        return f"FAIL — selected endpoint unavailable: {selected}"

    def _run_physical_audio_test(self, direction: str, endpoint_payload: dict[str, Any] | None) -> None:
        if endpoint_payload is None:
            messagebox.showwarning("ORION Test", f"No active {direction} endpoint is resolved by Core", parent=self.root)
            return
        endpoint = WasapiEndpoint.model_validate(endpoint_payload)
        tester = AudioHardwareTester()
        try:
            result = tester.test_input(endpoint) if direction == "input" else tester.test_output(endpoint)
        except (ImportError, OSError, RuntimeError) as exc:
            messagebox.showerror("ORION Test", str(exc), parent=self.root)
            return
        if result.ok:
            messagebox.showinfo("ORION Test", result.message, parent=self.root)
        else:
            messagebox.showwarning("ORION Test", result.message, parent=self.root)

    def _page_settings(self) -> None:
        super()._page_settings()
        ttk.Separator(self.content, orient="horizontal").pack(fill=X, pady=(24, 18))
        ttk.Label(self.content, text="AUDIO", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            self.content,
            text="Select the Windows microphone and output endpoint used by ORION Core. Device state is owned by Core and survives Launcher reconnects.",
            style="Muted.TLabel",
            wraplength=800,
            justify="left",
        ).pack(anchor="w", pady=(4, 12))
        try:
            inputs, outputs, state = self._audio_snapshot()
        except RuntimeError as exc:
            self._card(self.content, "AUDIO DEVICES", str(exc), wrap=760).pack(fill=X)
            return

        selection = state.get("selection", {})
        input_map = self._device_display_map(inputs, "Windows Default")
        output_map = self._device_display_map(outputs, "Windows Default")
        reverse_input = {device_id: label for label, device_id in input_map.items()}
        reverse_output = {device_id: label for label, device_id in output_map.items()}
        input_var = StringVar(value=reverse_input.get(selection.get("input_device_id", "default"), "Windows Default"))
        output_var = StringVar(value=reverse_output.get(selection.get("output_device_id", "default"), "Windows Default"))

        box = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        box.pack(fill=X)
        ttk.Label(box, text="MICROPHONE / INPUT", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Combobox(box, textvariable=input_var, values=tuple(input_map), state="readonly", width=70).pack(anchor="w", fill=X, pady=(6, 14))
        ttk.Label(box, text="HEADPHONES / OUTPUT", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Combobox(box, textvariable=output_var, values=tuple(output_map), state="readonly", width=70).pack(anchor="w", fill=X, pady=(6, 14))
        ttk.Label(box, text=f"Core: {state.get('message', 'Unknown')}", style="CardText.TLabel").pack(anchor="w")
        buttons = ttk.Frame(box, style="Card.TFrame")
        buttons.pack(fill=X, pady=(14, 0))
        ttk.Button(
            buttons,
            text="APPLY TO CORE",
            style="Primary.TButton",
            command=lambda: self._apply_audio_selection(input_map[input_var.get()], output_map[output_var.get()]),
        ).pack(side=LEFT, padx=(0, 8))
        ttk.Button(buttons, text="REFRESH DEVICES", style="Secondary.TButton", command=lambda: self.show_page("settings")).pack(side=LEFT, padx=(0, 8))
        ttk.Button(buttons, text="OPEN TEST", style="Secondary.TButton", command=lambda: self.show_page("test")).pack(side=LEFT)

    @staticmethod
    def _device_display_map(items: list[dict[str, Any]], default_label: str) -> dict[str, str]:
        result = {default_label: "default"}
        for item in items:
            device_id = str(item.get("device_id", ""))
            if not device_id:
                continue
            name = str(item.get("name", "Audio endpoint"))
            result[f"{name}  [{device_id[-18:]}]"] = device_id
        return result

    def _apply_audio_selection(self, input_device_id: str, output_device_id: str) -> None:
        try:
            state = self._core_json(
                "/v1/windows-audio/selection",
                method="PUT",
                payload={"input_device_id": input_device_id, "output_device_id": output_device_id},
            )
        except RuntimeError as exc:
            messagebox.showerror("ORION Audio", str(exc), parent=self.root)
            return
        messagebox.showinfo("ORION Audio", state.get("message", "Audio selection updated"), parent=self.root)
        self.show_page("settings")
