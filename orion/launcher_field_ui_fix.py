from __future__ import annotations

import tkinter as tk
from tkinter import BOTH, LEFT, X, BooleanVar, StringVar, ttk


class LauncherFieldUiFixMixin:
    """Field-test fixes for flicker, Audio readability and visible Test controls.

    This layer is intentionally additive and narrow: it does not change Launcher
    navigation, Core lifecycle, DCS behavior or existing feature pages.
    """

    def _apply_health(self, report) -> None:  # noqa: ANN001
        self.health = report
        self._render_status_strip()

    def _style(self) -> None:
        super()._style()
        style = ttk.Style(self.root)
        style.configure(
            "Audio.TCombobox",
            fieldbackground="#0f1b26",
            background="#223746",
            foreground="#f7fbfd",
            arrowcolor="#f7fbfd",
            borderwidth=1,
            relief="solid",
            padding=(9, 7),
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "Audio.TCombobox",
            fieldbackground=[("readonly", "#0f1b26"), ("disabled", "#18232e")],
            foreground=[("readonly", "#f7fbfd"), ("disabled", "#7d8b96")],
            selectbackground=[("readonly", "#0f1b26")],
            selectforeground=[("readonly", "#f7fbfd")],
        )

    @staticmethod
    def _action_button(parent, text: str, command, *, primary: bool = False, enabled: bool = True):  # noqa: ANN001
        bg = "#4ac6d7" if primary else "#1b2a36"
        fg = "#031014" if primary else "#f0f5f8"
        active_bg = "#6bd7e5" if primary else "#294052"
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active_bg,
            activeforeground=fg,
            disabledforeground="#7b8994",
            relief="flat",
            bd=0,
            padx=18,
            pady=10,
            font=("Segoe UI Semibold", 9),
            cursor="hand2" if enabled else "arrow",
        )
        if not enabled:
            button.configure(state="disabled", bg="#17222b")
        return button

    def _page_settings(self) -> None:
        language = StringVar(value=self.config.language)
        channel = StringVar(value=self.config.update_channel)
        autostart = BooleanVar(value=self.config.start_with_windows)
        minimize = BooleanVar(value=self.config.minimize_to_tray)

        ttk.Label(self.content, text="LAUNCHER SETTINGS", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        form = ttk.Frame(self.content, style="Card.TFrame", padding=18)
        form.pack(fill=X)
        ttk.Label(form, text=self.t("settings.language"), style="CardText.TLabel").grid(row=0, column=0, sticky="w", pady=8)
        ttk.Combobox(form, values=("en", "ru"), state="readonly", textvariable=language, width=18).grid(row=0, column=1, padx=16, sticky="w")
        ttk.Label(form, text=self.t("settings.update_channel"), style="CardText.TLabel").grid(row=1, column=0, sticky="w", pady=8)
        ttk.Combobox(form, values=("stable", "beta", "alpha"), state="readonly", textvariable=channel, width=18).grid(row=1, column=1, padx=16, sticky="w")
        ttk.Checkbutton(form, text=self.t("settings.start_windows"), variable=autostart).grid(row=2, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Checkbutton(form, text=self.t("settings.minimize_tray"), variable=minimize).grid(row=3, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Button(
            form,
            text="SAVE SETTINGS",
            style="Primary.TButton",
            command=lambda: self._save_settings(language.get(), channel.get(), autostart.get(), minimize.get()),
        ).grid(row=4, column=0, sticky="w", pady=(14, 0))

        ttk.Separator(self.content, orient="horizontal").pack(fill=X, pady=(20, 14))
        ttk.Label(self.content, text="AUDIO", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            self.content,
            text="Select the microphone and output used by ORION Core. Changes remain owned by Core after Launcher reconnects.",
            style="Muted.TLabel",
            wraplength=800,
            justify="left",
        ).pack(anchor="w", pady=(4, 10))

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
        ttk.Combobox(box, textvariable=input_var, values=tuple(input_map), state="readonly", style="Audio.TCombobox", width=70).pack(anchor="w", fill=X, pady=(6, 12))
        ttk.Label(box, text="HEADPHONES / OUTPUT", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Combobox(box, textvariable=output_var, values=tuple(output_map), state="readonly", style="Audio.TCombobox", width=70).pack(anchor="w", fill=X, pady=(6, 12))
        ttk.Label(box, text=f"Core: {state.get('message', 'Unknown')}", style="CardText.TLabel").pack(anchor="w")

        buttons = tk.Frame(box, bg="#111923")
        buttons.pack(fill=X, pady=(12, 0))
        self._action_button(buttons, "APPLY TO CORE", lambda: self._apply_audio_selection(input_map[input_var.get()], output_map[output_var.get()]), primary=True).pack(side=LEFT, padx=(0, 8))
        self._action_button(buttons, "REFRESH DEVICES", lambda: self.show_page("settings")).pack(side=LEFT, padx=(0, 8))
        self._action_button(buttons, "OPEN TEST", lambda: self.show_page("test")).pack(side=LEFT)

    def _page_test(self) -> None:
        hero = ttk.Frame(self.content, style="CardAlt.TFrame", padding=18)
        hero.pack(fill=X)
        ttk.Label(hero, text="FUNCTIONAL VERIFICATION", style="CardAltTitle.TLabel").pack(anchor="w")
        ttk.Label(hero, text="TEST", style="Hero.TLabel").pack(anchor="w", pady=(5, 2))
        ttk.Label(hero, text="Run focused checks without leaving Launcher.", style="HeroMuted.TLabel").pack(anchor="w")

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

        stt = ttk.Frame(self.content, style="Card.TFrame", padding=14)
        stt.pack(fill=X, pady=(12, 10))
        ttk.Label(stt, text="LOCAL SPEECH RECOGNITION", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            stt,
            text="Whisper medium runs locally on CPU. Download and install it once before the conversational audio test.",
            style="CardText.TLabel",
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(4, 7))
        self._stt_status_label = ttk.Label(stt, text="Checking Whisper medium…", style="CardText.TLabel")
        self._stt_status_label.pack(anchor="w", pady=(0, 5))
        self._stt_progress = ttk.Progressbar(stt, orient="horizontal", mode="determinate", maximum=100.0, length=520)
        self._stt_progress.pack(anchor="w", fill=X, pady=(0, 8))
        stt_actions = tk.Frame(stt, bg="#111923")
        stt_actions.pack(fill=X)
        self._stt_prepare_button = self._action_button(
            stt_actions,
            "DOWNLOAD & INSTALL STT",
            self._prepare_speech_recognition,
            primary=True,
            enabled=core_ok,
        )
        self._stt_prepare_button.pack(side=LEFT)

        audio = ttk.Frame(self.content, style="Card.TFrame", padding=14)
        audio.pack(fill=X, pady=(0, 10))
        ttk.Label(audio, text="CONVERSATIONAL AUDIO TEST", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            audio,
            text='Press START and say: “Привет, как дела?”  Expected reply: “Дела отлично. Связь установлена.”',
            style="CardText.TLabel",
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(4, 9))
        action_row = tk.Frame(audio, bg="#111923")
        action_row.pack(fill=X)
        self._conversation_button = self._action_button(
            action_row,
            "START AUDIO TEST",
            self._run_conversational_audio_test,
            primary=True,
            enabled=False,
        )
        self._conversation_button.pack(side=LEFT, padx=(0, 8))
        self._action_button(action_row, "TEST MICROPHONE", lambda: self._run_physical_audio_test("input", resolved_in), enabled=resolved_in is not None).pack(side=LEFT, padx=(0, 8))
        self._action_button(action_row, "TEST OUTPUT", lambda: self._run_physical_audio_test("output", resolved_out), enabled=resolved_out is not None).pack(side=LEFT)

        checks = (
            ("CORE", "PASS — connected" if core_ok else "FAIL — not reachable"),
            ("AUDIO DISCOVERY", f"PASS — {len(inputs)} input / {len(outputs)} output" if audio_api_ok else "FAIL — API unavailable"),
            ("MICROPHONE", self._selection_text(selection.get("input_device_id", "default"), resolved_in)),
            ("OUTPUT", self._selection_text(selection.get("output_device_id", "default"), resolved_out)),
        )
        ttk.Label(self.content, text="CURRENT CHECKS", style="Section.TLabel").pack(anchor="w", pady=(4, 6))
        row = ttk.Frame(self.content, style="Orion.TFrame")
        row.pack(fill=X)
        for index, (title, text) in enumerate(checks):
            card = self._card(row, title, text, wrap=185)
            card.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 7 if index < len(checks) - 1 else 0))

        if core_ok:
            self.root.after(50, self._poll_stt_status)
