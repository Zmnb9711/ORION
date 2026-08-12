from __future__ import annotations

from pathlib import Path
from tkinter import BOTH, LEFT, RIGHT, X, Y, Tk
from tkinter import ttk

from orion import __version__
from orion.desktop_app import CoreServer
from orion.desktop_app_windows import WindowsOrionDesktopLauncher


class WindowsOrionDesktopLauncherV2(WindowsOrionDesktopLauncher):
    """Visual V2 shell layered over the proven Windows launcher backend."""

    def __init__(self, root: Tk, runtime_dir: Path, core: CoreServer) -> None:
        self.nav_buttons: dict[str, ttk.Button] = {}
        super().__init__(root, runtime_dir, core)

    def _style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
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

        style.configure(
            "Nav.TButton",
            anchor="w",
            padding=(18, 11),
            relief="flat",
            borderwidth=0,
            foreground="#a4b0ba",
            background=panel,
            font=("Segoe UI Semibold", 9),
        )
        style.map("Nav.TButton", background=[("active", "#15212c")], foreground=[("active", fg)])
        style.configure(
            "NavActive.TButton",
            anchor="w",
            padding=(18, 11),
            relief="flat",
            borderwidth=0,
            foreground=fg,
            background=cyan_dim,
            font=("Segoe UI Semibold", 9),
        )
        style.map("NavActive.TButton", background=[("active", cyan_dim)])

        style.configure(
            "Primary.TButton",
            padding=(18, 11),
            relief="flat",
            borderwidth=0,
            foreground="#031014",
            background=cyan,
            font=("Segoe UI Semibold", 9),
        )
        style.map("Primary.TButton", background=[("active", "#6bd7e5"), ("disabled", "#26353b")])
        style.configure(
            "Secondary.TButton",
            padding=(16, 10),
            relief="flat",
            borderwidth=1,
            foreground=fg,
            background="#18232e",
            font=("Segoe UI Semibold", 9),
        )
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
        nav_captions = {
            "home": "OVERVIEW",
            "fly": "FLY / DCS",
            "mission": "MISSION",
            "diagnostics": "DIAGNOSTICS",
            "providers": "AI PROVIDERS",
            "updates": "UPDATES",
            "settings": "SETTINGS",
            "logs": "LOGS",
            "about": "ABOUT",
        }
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
        if operational:
            message = "DCS integration and live telemetry are ready. ORION is standing by as ATC & Mission Assistant."
        else:
            message = "Complete DCS setup and establish live telemetry before the first full flight test."
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

    def _apply_health(self, report) -> None:  # noqa: ANN001
        self.health = report
        self._render_status_strip()
        if self.current_page in {"home", "fly", "diagnostics", "logs"}:
            self.show_page(self.current_page)


def run_desktop_launcher(runtime_dir: Path, host: str = "127.0.0.1", port: int = 8000) -> int:
    core = CoreServer(host, port)
    core.start()
    try:
        root = Tk()
        WindowsOrionDesktopLauncherV2(root, runtime_dir=runtime_dir, core=core)
        root.mainloop()
    finally:
        core.stop()
    return 0
