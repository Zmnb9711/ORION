from __future__ import annotations

from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, BooleanVar, StringVar, TclError, Tk
from tkinter import ttk

from orion import __version__
from orion.desktop_app import CoreServer
from orion.update_center import current_feature_status


class WindowsProductVisualMixin:
    """Shared visual behavior for the canonical Windows product launcher.

    This mixin deliberately does not define a production entry point or own Core
    lifecycle. It exists only to keep the visual shell separate from the Windows
    behavior base while the product launcher remains the canonical concrete class.
    """

    def __init__(self, root: Tk, runtime_dir: Path, core: CoreServer) -> None:
        self.nav_buttons: dict[str, ttk.Button] = {}
        super().__init__(root, runtime_dir, core)

    def _style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except TclError:
            pass

        bg = "#070b10"
        panel = "#0d141d"
        panel_alt = "#111b27"
        card = "#111923"
        card_alt = "#162230"
        fg = "#f0f5f8"
        muted = "#82909d"
        cyan = "#4ac6d7"
        cyan_dim = "#173842"
        amber = "#d6a64d"
        green = "#5cc98a"

        self.root.configure(background=bg)
        for name, background in (
            ("Orion.TFrame", bg),
            ("Panel.TFrame", panel),
            ("PanelAlt.TFrame", panel_alt),
            ("Card.TFrame", card),
            ("CardAlt.TFrame", card_alt),
            ("Status.TFrame", "#0b1118"),
        ):
            style.configure(name, background=background)

        style.configure("Orion.TLabel", background=bg, foreground=fg, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=bg, foreground=muted, font=("Segoe UI", 9))
        style.configure("Eyebrow.TLabel", background=bg, foreground=cyan, font=("Segoe UI Semibold", 9))
        style.configure("Title.TLabel", background=bg, foreground=fg, font=("Segoe UI Semibold", 24))
        style.configure("Hero.TLabel", background=card_alt, foreground=fg, font=("Segoe UI Semibold", 23))
        style.configure("HeroMuted.TLabel", background=card_alt, foreground=muted, font=("Segoe UI", 10))
        style.configure("Panel.TLabel", background=panel, foreground=fg)
        style.configure("PanelMuted.TLabel", background=panel, foreground=muted, font=("Segoe UI", 9))
        style.configure("Brand.TLabel", background=panel, foreground=fg, font=("Segoe UI Semibold", 25))
        style.configure("BrandSub.TLabel", background=panel, foreground=cyan, font=("Segoe UI Semibold", 8))
        style.configure("Section.TLabel", background=bg, foreground=fg, font=("Segoe UI Semibold", 14))
        style.configure("CardTitle.TLabel", background=card, foreground=fg, font=("Segoe UI Semibold", 10))
        style.configure("CardText.TLabel", background=card, foreground=muted, font=("Segoe UI", 9))
        style.configure("CardAltTitle.TLabel", background=card_alt, foreground=fg, font=("Segoe UI Semibold", 11))
        style.configure("CardAltText.TLabel", background=card_alt, foreground=muted, font=("Segoe UI", 9))
        style.configure("StatusName.TLabel", background="#0b1118", foreground=muted, font=("Segoe UI Semibold", 8))
        style.configure("StatusValue.TLabel", background="#0b1118", foreground=fg, font=("Segoe UI Semibold", 10))
        style.configure("StatusGood.TLabel", background="#0b1118", foreground=green, font=("Segoe UI Semibold", 10))
        style.configure("StatusWarn.TLabel", background="#0b1118", foreground=amber, font=("Segoe UI Semibold", 10))

        style.configure("Nav.TButton", anchor="w", padding=(18, 11), relief="flat", borderwidth=0, foreground="#a4b0ba", background=panel, font=("Segoe UI Semibold", 9))
        style.map("Nav.TButton", background=[("active", "#15212c")], foreground=[("active", fg)])
        style.configure("NavActive.TButton", anchor="w", padding=(18, 11), relief="flat", borderwidth=0, foreground=fg, background=cyan_dim, font=("Segoe UI Semibold", 9))
        style.map("NavActive.TButton", background=[("active", cyan_dim)])
        style.configure("Primary.TButton", padding=(18, 11), relief="flat", borderwidth=0, foreground="#031014", background=cyan, font=("Segoe UI Semibold", 9))
        style.map("Primary.TButton", background=[("active", "#6bd7e5"), ("disabled", "#26353b")])
        style.configure("Secondary.TButton", padding=(16, 10), relief="flat", borderwidth=1, foreground=fg, background="#18232e", font=("Segoe UI Semibold", 9))
        style.map("Secondary.TButton", background=[("active", "#223240")])
        style.configure("TButton", padding=(12, 8))
        style.configure("TCombobox", fieldbackground=panel_alt, background=panel_alt, foreground=fg)
        style.configure("TCheckbutton", background=card, foreground=fg)
        style.configure("TRadiobutton", background=card, foreground=fg)
        style.configure("TLabelframe", background=bg, foreground=fg)
        style.configure("TLabelframe.Label", background=bg, foreground=cyan)
        style.configure("TProgressbar", background=cyan, troughcolor="#15202b")

    def _build_shell(self) -> None:
        self.nav_buttons = {}
        outer = ttk.Frame(self.root, style="Orion.TFrame")
        outer.pack(fill=BOTH, expand=True)
        sidebar = ttk.Frame(outer, style="Panel.TFrame", width=248)
        sidebar.pack(side=LEFT, fill=Y)
        sidebar.pack_propagate(False)

        brand = ttk.Frame(sidebar, style="Panel.TFrame")
        brand.pack(fill=X, padx=20, pady=(22, 18))
        ttk.Label(brand, text="ORION", style="Brand.TLabel").pack(anchor="w")
        ttk.Label(brand, text="ATC & MISSION ASSISTANT", style="BrandSub.TLabel").pack(anchor="w", pady=(1, 0))
        ttk.Separator(sidebar, orient="horizontal").pack(fill=X, padx=16, pady=(0, 12))

        nav = ttk.Frame(sidebar, style="Panel.TFrame")
        nav.pack(fill=X)
        nav_captions = {"home": "OVERVIEW", "fly": "FLY / DCS", "mission": "MISSION", "diagnostics": "DIAGNOSTICS", "providers": "AI PROVIDERS", "updates": "UPDATES", "settings": "SETTINGS", "logs": "LOGS", "about": "ABOUT"}
        for key in self.NAV_KEYS:
            button = ttk.Button(nav, text=nav_captions.get(key, self.nav_label(key)).upper(), style="Nav.TButton", command=lambda page=key: self.show_page(page))
            button.pack(fill=X, padx=10, pady=2)
            self.nav_buttons[key] = button

        footer = ttk.Frame(sidebar, style="Panel.TFrame")
        footer.pack(side="bottom", fill=X, padx=18, pady=18)
        ttk.Label(footer, text="CORE STATUS", style="BrandSub.TLabel").pack(anchor="w")
        ttk.Label(footer, textvariable=self.status_var, style="PanelMuted.TLabel", wraplength=200, justify="left").pack(anchor="w", pady=(4, 12))
        ttk.Label(footer, text=f"ORION {__version__}  •  ALPHA", style="PanelMuted.TLabel").pack(anchor="w")

        main = ttk.Frame(outer, style="Orion.TFrame")
        main.pack(side=RIGHT, fill=BOTH, expand=True)
        header = ttk.Frame(main, style="Orion.TFrame")
        header.pack(fill=X, padx=30, pady=(20, 10))
        title_box = ttk.Frame(header, style="Orion.TFrame")
        title_box.pack(side=LEFT)
        ttk.Label(title_box, text="ORION COMMAND CONSOLE", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(title_box, textvariable=self.page_title, style="Title.TLabel").pack(anchor="w")
        ttk.Button(header, text="REFRESH", style="Secondary.TButton", command=self._refresh_page).pack(side=RIGHT, pady=(8, 0))

        self.status_strip = ttk.Frame(main, style="Status.TFrame", padding=(16, 10))
        self.status_strip.pack(fill=X, padx=30, pady=(0, 14))
        self.content = ttk.Frame(main, style="Orion.TFrame")
        self.content.pack(fill=BOTH, expand=True, padx=30, pady=(0, 24))

    def show_page(self, page: str) -> None:
        self.current_page = page
        for key, button in self.nav_buttons.items():
            button.configure(style="NavActive.TButton" if key == page else "Nav.TButton")
        self._render_status_strip()
        self._clear()
        self.page_title.set(self.nav_label(page).upper())
        getattr(self, f"_page_{page}")()

    def _render_status_strip(self) -> None:
        if not hasattr(self, "status_strip"):
            return
        for child in self.status_strip.winfo_children():
            child.destroy()
        values = [
            ("CORE", "CONNECTED" if self.core.healthy() else "STARTING", self.core.healthy()),
            ("DCS", self._compact_health("active_dcs"), self._health_passed("active_dcs")),
            ("TELEMETRY", self._compact_health("telemetry"), self._health_passed("telemetry")),
            ("AI", self.config.ai_provider.upper(), True),
        ]
        for index, (name, value, good) in enumerate(values):
            cell = ttk.Frame(self.status_strip, style="Status.TFrame")
            cell.pack(side=LEFT, fill=X, expand=True)
            ttk.Label(cell, text=name, style="StatusName.TLabel").pack(anchor="w")
            ttk.Label(cell, text=value, style="StatusGood.TLabel" if good else "StatusWarn.TLabel").pack(anchor="w", pady=(1, 0))
            if index < len(values) - 1:
                ttk.Separator(self.status_strip, orient="vertical").pack(side=LEFT, fill=Y, padx=14)

    def _health_passed(self, key: str) -> bool:
        if self.health is None:
            return False
        return any(check.key == key and check.passed for check in self.health.checks)

    def _compact_health(self, key: str) -> str:
        if self.health is None:
            return "CHECKING"
        for check in self.health.checks:
            if check.key == key:
                return "READY" if check.passed else "ATTENTION"
        return "UNKNOWN"

    def _page_home(self) -> None:
        dcs_ready = self._health_passed("active_dcs")
        export_ready = self._health_passed("export_integration")
        telemetry_ready = self._health_passed("telemetry")
        operational = self.core.healthy() and dcs_ready and export_ready and telemetry_ready
        hero = ttk.Frame(self.content, style="CardAlt.TFrame", padding=22)
        hero.pack(fill=X)
        ttk.Label(hero, text="SYSTEM STATUS", style="CardAltTitle.TLabel").pack(anchor="w")
        ttk.Label(hero, text="MISSION READY" if operational else "SETUP REQUIRED", style="Hero.TLabel").pack(anchor="w", pady=(8, 3))
        message = "DCS integration and live telemetry are ready. ORION is standing by as ATC & Mission Assistant." if operational else "Complete DCS setup and establish live telemetry before the first full flight test."
        ttk.Label(hero, text=message, style="HeroMuted.TLabel", wraplength=760, justify="left").pack(anchor="w")
        actions = ttk.Frame(hero, style="CardAlt.TFrame")
        actions.pack(fill=X, pady=(18, 0))
        ttk.Button(actions, text="LAUNCH DCS", style="Primary.TButton", command=self._launch_dcs_async).pack(side=LEFT, padx=(0, 9))
        ttk.Button(actions, text="DCS SETUP", style="Secondary.TButton", command=self._open_setup).pack(side=LEFT, padx=(0, 9))
        ttk.Button(actions, text="CHECK UPDATES", style="Secondary.TButton", command=lambda: self.show_page("updates")).pack(side=LEFT)

        ttk.Label(self.content, text="OPERATIONAL READINESS", style="Section.TLabel").pack(anchor="w", pady=(22, 10))
        row = ttk.Frame(self.content, style="Orion.TFrame")
        row.pack(fill=X)
        readiness = [
            ("DCS WORLD", "Detected and selected" if dcs_ready else self._health_text("active_dcs")),
            ("EXPORT INTEGRATION", "Installed" if export_ready else self._health_text("export_integration")),
            ("LIVE TELEMETRY", "Receiving data" if telemetry_ready else self._health_text("telemetry")),
        ]
        for index, (title, text) in enumerate(readiness):
            card = self._card(row, title, text, wrap=260)
            card.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10 if index < len(readiness) - 1 else 0))

        ttk.Label(self.content, text="CURRENT BUILD", style="Section.TLabel").pack(anchor="w", pady=(22, 10))
        build = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        build.pack(fill=X)
        ttk.Label(build, text=f"ORION {__version__}", style="CardTitle.TLabel").pack(anchor="w")
        update_text = self.update_result.message if self.update_result else "Checking release channel…"
        ttk.Label(build, text=update_text, style="CardText.TLabel", wraplength=760, justify="left").pack(anchor="w", pady=(5, 0))

    def _page_fly(self) -> None:
        ready = self._health_passed("active_dcs") and self._health_passed("telemetry")
        hero = ttk.Frame(self.content, style="CardAlt.TFrame", padding=22)
        hero.pack(fill=X)
        ttk.Label(hero, text="LIVE FLIGHT LINK", style="CardAltTitle.TLabel").pack(anchor="w")
        ttk.Label(hero, text="READY FOR DCS" if ready else "DCS LINK NOT READY", style="Hero.TLabel").pack(anchor="w", pady=(8, 3))
        ttk.Label(hero, text=self._health_text("active_dcs"), style="HeroMuted.TLabel", wraplength=780, justify="left").pack(anchor="w")
        buttons = ttk.Frame(hero, style="CardAlt.TFrame")
        buttons.pack(fill=X, pady=(18, 0))
        ttk.Button(buttons, text="LAUNCH DCS", style="Primary.TButton", command=self._launch_dcs_async).pack(side=LEFT, padx=(0, 9))
        ttk.Button(buttons, text="DCS SETUP", style="Secondary.TButton", command=self._open_setup).pack(side=LEFT)

    def _page_mission(self) -> None:
        hero = ttk.Frame(self.content, style="CardAlt.TFrame", padding=22)
        hero.pack(fill=X)
        ttk.Label(hero, text="MISSION WORKSPACE", style="CardAltTitle.TLabel").pack(anchor="w")
        ttk.Label(hero, text="MISSION STUDIO", style="Hero.TLabel").pack(anchor="w", pady=(8, 3))
        ttk.Label(hero, text="Mission analysis, briefing and preparation will be surfaced here while the dedicated mission backend continues to evolve.", style="HeroMuted.TLabel", wraplength=780, justify="left").pack(anchor="w")

    def _page_diagnostics(self) -> None:
        ttk.Label(self.content, text="SYSTEM CHECKS", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        box = ttk.Frame(self.content, style="Card.TFrame", padding=18)
        box.pack(fill=X)
        if self.health is None:
            ttk.Label(box, text="Running diagnostics…", style="CardText.TLabel").pack(anchor="w")
        else:
            for check in self.health.checks:
                ttk.Label(box, text=f"{'PASS' if check.passed else 'WARN'}  {check.message}", style="CardText.TLabel").pack(anchor="w", pady=3)
        buttons = ttk.Frame(self.content, style="Orion.TFrame")
        buttons.pack(fill=X, pady=(14, 0))
        ttk.Button(buttons, text="EXPORT DIAGNOSTICS", style="Primary.TButton", command=self._diagnostics_async).pack(side=LEFT, padx=(0, 9))
        ttk.Button(buttons, text="DCS SETUP", style="Secondary.TButton", command=self._open_setup).pack(side=LEFT)

    def _page_providers(self) -> None:
        ttk.Label(self.content, text="AI ROUTING", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        choice = StringVar(value=self.config.ai_provider)
        for label, value, description in (
            ("AUTO", "auto", "Let ORION choose the configured provider."),
            ("OPENAI", "openai", "OpenAI cloud provider."),
            ("YANDEX CLOUD", "yandex", "Yandex Cloud provider."),
            ("GIGACHAT", "gigachat", "GigaChat provider."),
            ("LOCAL AI", "local", "Local inference provider."),
        ):
            row = ttk.Frame(self.content, style="Card.TFrame", padding=14)
            row.pack(fill=X, pady=4)
            ttk.Radiobutton(row, text=label, value=value, variable=choice).pack(side=LEFT)
            ttk.Label(row, text=description, style="CardText.TLabel").pack(side=LEFT, padx=(16, 0))
        ttk.Button(self.content, text="SAVE PROVIDER", style="Primary.TButton", command=lambda: self._save_provider(choice.get())).pack(anchor="w", pady=14)

    def _page_updates(self) -> None:
        ttk.Label(self.content, text="UPDATE CENTER", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        card = ttk.Frame(self.content, style="CardAlt.TFrame", padding=20)
        card.pack(fill=X)
        ttk.Label(card, text=f"INSTALLED  •  ORION {__version__}", style="CardAltTitle.TLabel").pack(anchor="w")
        channel = StringVar(value=self.config.update_channel)
        row = ttk.Frame(card, style="CardAlt.TFrame")
        row.pack(fill=X, pady=(14, 0))
        ttk.Combobox(row, values=("stable", "beta", "alpha"), state="readonly", textvariable=channel, width=16).pack(side=LEFT, padx=(0, 9))
        ttk.Button(row, text="CHECK FOR UPDATES", style="Primary.TButton", command=lambda: self._set_channel_and_check(channel.get())).pack(side=LEFT)
        if self.update_progress_text.get():
            ttk.Label(self.content, textvariable=self.update_progress_text, style="Muted.TLabel").pack(anchor="w", pady=(12, 0))
            ttk.Progressbar(self.content, maximum=100, value=self.update_progress).pack(fill=X, pady=4)
        result = self.update_result
        if result and result.latest:
            release = result.latest
            release_card = self._card(self.content, f"ORION {release.version} — {release.title}", release.notes.strip() or "No release notes supplied.", 850)
            release_card.pack(fill=X, pady=(14, 8))
            if result.update_available:
                ttk.Button(release_card, text=f"INSTALL {release.version}", style="Primary.TButton", command=self._install_update_async).pack(anchor="w", pady=(12, 0))
        ttk.Label(self.content, text="CURRENT FUNCTIONALITY", style="Section.TLabel").pack(anchor="w", pady=(18, 8))
        for feature in current_feature_status():
            self._card(self.content, f"{'✓' if feature.state == 'available' else '○'} {feature.name}", feature.description, 820).pack(fill=X, pady=3)

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
        ttk.Button(form, text="SAVE SETTINGS", style="Primary.TButton", command=lambda: self._save_settings(language.get(), channel.get(), autostart.get(), minimize.get())).grid(row=4, column=0, sticky="w", pady=(14, 0))

    def _page_logs(self) -> None:
        ttk.Label(self.content, text="RUNTIME LOG", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        text = __import__("tkinter").Text(self.content, bg="#0b1118", fg="#c8d5e8", insertbackground="#4ac6d7", relief="flat", padx=14, pady=14)
        text.pack(fill=BOTH, expand=True)
        text.insert(END, f"ORION {__version__}\nCore API: {self.core.base_url}\nRuntime: {self.runtime_dir}\n")
        if self.health:
            for check in self.health.checks:
                text.insert(END, f"{'PASS' if check.passed else 'WARN'} {check.key}: {check.message}\n")
        text.configure(state="disabled")

    def _page_about(self) -> None:
        hero = ttk.Frame(self.content, style="CardAlt.TFrame", padding=22)
        hero.pack(fill=X)
        ttk.Label(hero, text="ORION", style="CardAltTitle.TLabel").pack(anchor="w")
        ttk.Label(hero, text="ATC & MISSION ASSISTANT", style="Hero.TLabel").pack(anchor="w", pady=(8, 3))
        ttk.Label(hero, text=f"Version {__version__}  •  AI Mission Control and Virtual ATC for DCS World", style="HeroMuted.TLabel", wraplength=780, justify="left").pack(anchor="w")

    def _apply_health(self, report) -> None:  # noqa: ANN001
        self.health = report
        self._render_status_strip()
        if self.current_page in {"home", "fly", "diagnostics", "logs"}:
            self.show_page(self.current_page)
