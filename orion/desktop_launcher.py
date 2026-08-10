from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, BooleanVar, StringVar, Tk, Toplevel, filedialog, messagebox
from tkinter import ttk

import uvicorn

from orion import __version__
from orion.alpha_smoke_diagnostics import write_alpha_diagnostics_bundle
from orion.recovery_launch import start_dcs_for_recovery
from orion.startup_health import StartupHealthReport, inspect_startup_health


@dataclass(slots=True)
class LauncherConfig:
    language: str = "en"
    theme: str = "dark"
    minimize_to_tray: bool = True
    start_with_windows: bool = False
    ai_provider: str = "auto"


class LauncherConfigStore:
    def __init__(self, runtime_dir: Path) -> None:
        self.path = runtime_dir / "launcher.json"

    def load(self) -> LauncherConfig:
        if not self.path.is_file():
            return LauncherConfig()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return LauncherConfig()
        allowed = LauncherConfig.__dataclass_fields__
        return LauncherConfig(**{key: value for key, value in payload.items() if key in allowed})

    def save(self, config: LauncherConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "language": config.language,
                    "theme": config.theme,
                    "minimize_to_tray": config.minimize_to_tray,
                    "start_with_windows": config.start_with_windows,
                    "ai_provider": config.ai_provider,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


class CoreServer:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        config = uvicorn.Config(
            "orion.app:app",
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, name="orion-core", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def healthy(self, timeout: float = 0.5) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/health", timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return False
        return payload.get("status") == "ok"


class OrionDesktopLauncher:
    NAV_ITEMS = (
        ("Home", "home"),
        ("Fly with ORION", "fly"),
        ("Mission Studio", "mission"),
        ("Diagnostics", "diagnostics"),
        ("AI Providers", "providers"),
        ("Settings", "settings"),
        ("Logs", "logs"),
        ("About", "about"),
    )

    def __init__(self, root: Tk, runtime_dir: Path, core: CoreServer) -> None:
        self.root = root
        self.runtime_dir = runtime_dir
        self.core = core
        self.config_store = LauncherConfigStore(runtime_dir)
        self.config = self.config_store.load()
        self.current_page = "home"
        self.status_var = StringVar(value="Starting ORION Core…")
        self.page_title = StringVar(value="Home")
        self.health: StartupHealthReport | None = None

        self.root.title(f"ORION Alpha {__version__}")
        self.root.geometry("1180x760")
        self.root.minsize(980, 640)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._configure_style()
        self._build_shell()
        self.show_page("home")
        self._poll_core()
        self._refresh_health_async()

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        bg = "#0b1220"
        panel = "#121c2e"
        card = "#17243a"
        fg = "#eef5ff"
        muted = "#9baac0"
        accent = "#2878ff"
        self.root.configure(background=bg)
        style.configure("Orion.TFrame", background=bg)
        style.configure("Panel.TFrame", background=panel)
        style.configure("Card.TFrame", background=card)
        style.configure("Orion.TLabel", background=bg, foreground=fg, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=bg, foreground=muted, font=("Segoe UI", 9))
        style.configure("Panel.TLabel", background=panel, foreground=fg, font=("Segoe UI", 10))
        style.configure("PanelMuted.TLabel", background=panel, foreground=muted, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=bg, foreground=fg, font=("Segoe UI Semibold", 22))
        style.configure("Section.TLabel", background=bg, foreground=fg, font=("Segoe UI Semibold", 14))
        style.configure("CardTitle.TLabel", background=card, foreground=fg, font=("Segoe UI Semibold", 11))
        style.configure("CardText.TLabel", background=card, foreground=muted, font=("Segoe UI", 9))
        style.configure("Nav.TButton", anchor="w", padding=(14, 11), font=("Segoe UI", 10))
        style.configure("Primary.TButton", padding=(16, 10), font=("Segoe UI Semibold", 10), foreground="white", background=accent)
        style.map("Primary.TButton", background=[("active", "#3f8aff")])
        style.configure("TButton", padding=(12, 8))
        style.configure("TCheckbutton", background=bg, foreground=fg)
        style.configure("TCombobox", padding=6)

    def _build_shell(self) -> None:
        outer = ttk.Frame(self.root, style="Orion.TFrame")
        outer.pack(fill=BOTH, expand=True)

        sidebar = ttk.Frame(outer, style="Panel.TFrame", width=220)
        sidebar.pack(side=LEFT, fill=Y)
        sidebar.pack_propagate(False)
        ttk.Label(sidebar, text="✦ ORION", style="Panel.TLabel", font=("Segoe UI Semibold", 24)).pack(anchor="w", padx=20, pady=(22, 26))

        for label, key in self.NAV_ITEMS:
            ttk.Button(sidebar, text=label, style="Nav.TButton", command=lambda page=key: self.show_page(page)).pack(fill=X, padx=10, pady=2)

        ttk.Separator(sidebar).pack(fill=X, padx=14, pady=16)
        self.sidebar_status = ttk.Label(sidebar, textvariable=self.status_var, style="PanelMuted.TLabel", wraplength=180)
        self.sidebar_status.pack(anchor="w", padx=18, pady=4)
        ttk.Label(sidebar, text=f"Alpha {__version__}", style="PanelMuted.TLabel").pack(side="bottom", anchor="w", padx=18, pady=18)

        main = ttk.Frame(outer, style="Orion.TFrame")
        main.pack(side=RIGHT, fill=BOTH, expand=True)
        header = ttk.Frame(main, style="Orion.TFrame")
        header.pack(fill=X, padx=28, pady=(22, 12))
        ttk.Label(header, textvariable=self.page_title, style="Title.TLabel").pack(side=LEFT)
        ttk.Button(header, text="Refresh", command=self._refresh_health_async).pack(side=RIGHT)

        self.content = ttk.Frame(main, style="Orion.TFrame")
        self.content.pack(fill=BOTH, expand=True, padx=28, pady=(0, 20))

    def _clear_content(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()

    def show_page(self, page: str) -> None:
        self.current_page = page
        self._clear_content()
        title = dict((key, label) for label, key in self.NAV_ITEMS)[page]
        self.page_title.set(title)
        getattr(self, f"_page_{page}")()

    def _card(self, parent: ttk.Frame, title: str, text: str) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Card.TFrame", padding=16)
        ttk.Label(frame, text=title, style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(frame, text=text, style="CardText.TLabel", wraplength=250, justify="left").pack(anchor="w", pady=(6, 0))
        return frame

    def _page_home(self) -> None:
        ttk.Label(self.content, text="ORION control center", style="Muted.TLabel").pack(anchor="w", pady=(0, 14))
        status_row = ttk.Frame(self.content, style="Orion.TFrame")
        status_row.pack(fill=X)
        health = self.health
        values = [
            ("Core API", "Connected" if self.core.healthy() else "Starting"),
            ("DCS World", self._health_message("active_dcs")),
            ("Export.lua", self._health_message("export_integration")),
            ("Telemetry", self._health_message("telemetry")),
        ]
        for title, value in values:
            card = self._card(status_row, title, value)
            card.pack(side=LEFT, fill=X, expand=True, padx=(0, 10))

        ttk.Label(self.content, text="Quick start", style="Section.TLabel").pack(anchor="w", pady=(24, 10))
        actions = ttk.Frame(self.content, style="Orion.TFrame")
        actions.pack(fill=X)
        fly = self._card(actions, "Fly with ORION", "Launch DCS using the active ORION profile and wait for live telemetry.")
        fly.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
        ttk.Button(fly, text="Launch DCS", style="Primary.TButton", command=self._launch_dcs_async).pack(anchor="w", pady=(16, 0))
        diag = self._card(actions, "Diagnostics", "Create a one-shot diagnostics bundle for DCS, Export.lua, telemetry and audio readiness.")
        diag.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
        ttk.Button(diag, text="Run diagnostics", command=self._run_diagnostics_async).pack(anchor="w", pady=(16, 0))
        mission = self._card(actions, "Mission Studio", "Mission Studio #70 is reserved in the launcher. The compiler/editor backend is the next module.")
        mission.pack(side=LEFT, fill=BOTH, expand=True)
        ttk.Button(mission, text="Open Mission Studio", command=lambda: self.show_page("mission")).pack(anchor="w", pady=(16, 0))

        if health is not None:
            ttk.Label(self.content, text="Startup checks", style="Section.TLabel").pack(anchor="w", pady=(24, 10))
            checks = ttk.Frame(self.content, style="Card.TFrame", padding=14)
            checks.pack(fill=X)
            for check in health.checks:
                marker = "✓" if check.passed else "!"
                ttk.Label(checks, text=f"{marker}  {check.message}", style="CardText.TLabel").pack(anchor="w", pady=3)

    def _page_fly(self) -> None:
        ttk.Label(self.content, text="Launch DCS with ORION attached", style="Muted.TLabel").pack(anchor="w", pady=(0, 14))
        health = self.health
        if health is None:
            ttk.Label(self.content, text="Reading DCS configuration…", style="Orion.TLabel").pack(anchor="w")
            return
        card = ttk.Frame(self.content, style="Card.TFrame", padding=18)
        card.pack(fill=X)
        active = health.active_dcs
        if active is None:
            ttk.Label(card, text="No active DCS installation is configured.", style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(card, text="Run Diagnostics or the first-run setup before launching DCS.", style="CardText.TLabel").pack(anchor="w", pady=(6, 0))
        else:
            ttk.Label(card, text="Active DCS installation", style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(card, text=str(active.executable_path), style="CardText.TLabel", wraplength=780).pack(anchor="w", pady=(6, 0))
            ttk.Button(card, text="Launch DCS", style="Primary.TButton", command=self._launch_dcs_async).pack(anchor="w", pady=(18, 0))
        ttk.Button(self.content, text="Open Core API", command=lambda: webbrowser.open(f"{self.core.base_url}/docs")).pack(anchor="w", pady=18)

    def _page_mission(self) -> None:
        card = ttk.Frame(self.content, style="Card.TFrame", padding=20)
        card.pack(fill=X)
        ttk.Label(card, text="Mission Studio", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            card,
            text="The launcher entry is now part of the real desktop shell. Mission Studio #70 itself will add .miz import, analysis, validation, safe patching and generation; those capabilities are not falsely exposed before their backend exists.",
            style="CardText.TLabel",
            wraplength=820,
        ).pack(anchor="w", pady=(8, 14))
        ttk.Button(card, text="Open .miz…", command=self._select_miz).pack(anchor="w")

    def _page_diagnostics(self) -> None:
        ttk.Label(self.content, text="System and DCS integration checks", style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
        frame = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        frame.pack(fill=X)
        if self.health is not None:
            for check in self.health.checks:
                ttk.Label(frame, text=("PASS" if check.passed else "WARN") + f"  {check.message}", style="CardText.TLabel").pack(anchor="w", pady=4)
        ttk.Button(self.content, text="Run full diagnostics", style="Primary.TButton", command=self._run_diagnostics_async).pack(anchor="w", pady=16)
        ttk.Button(self.content, text="Open diagnostics folder", command=self._open_diagnostics_folder).pack(anchor="w")

    def _page_providers(self) -> None:
        ttk.Label(self.content, text="Approved AI backends", style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
        choice = StringVar(value=self.config.ai_provider)
        providers = (
            ("Auto", "auto", "Automatically choose an available configured backend."),
            ("OpenAI", "openai", "International cloud provider."),
            ("Yandex Cloud", "yandex", "Russian cloud provider / OpenAI-compatible models."),
            ("GigaChat", "gigachat", "Russian cloud provider."),
            ("Local AI", "local", "Local model backend; offline-capable."),
        )
        for label, value, text in providers:
            card = ttk.Frame(self.content, style="Card.TFrame", padding=14)
            card.pack(fill=X, pady=4)
            ttk.Radiobutton(card, text=label, variable=choice, value=value).pack(side=LEFT)
            ttk.Label(card, text=text, style="CardText.TLabel").pack(side=LEFT, padx=16)
        ttk.Button(
            self.content,
            text="Save provider preference",
            style="Primary.TButton",
            command=lambda: self._save_provider(choice.get()),
        ).pack(anchor="w", pady=16)
        ttk.Label(
            self.content,
            text="Provider adapters and credential storage are a separate implementation milestone; this launcher does not claim an unconfigured provider is connected.",
            style="Muted.TLabel",
            wraplength=800,
        ).pack(anchor="w")

    def _page_settings(self) -> None:
        language = StringVar(value=self.config.language)
        theme = StringVar(value=self.config.theme)
        minimize = BooleanVar(value=self.config.minimize_to_tray)
        autostart = BooleanVar(value=self.config.start_with_windows)
        form = ttk.Frame(self.content, style="Card.TFrame", padding=18)
        form.pack(fill=X)
        ttk.Label(form, text="Language", style="CardText.TLabel").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Combobox(form, textvariable=language, values=("en", "ru"), state="readonly", width=24).grid(row=0, column=1, sticky="w", padx=20)
        ttk.Label(form, text="Theme", style="CardText.TLabel").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Combobox(form, textvariable=theme, values=("dark",), state="readonly", width=24).grid(row=1, column=1, sticky="w", padx=20)
        ttk.Checkbutton(form, text="Minimize to tray when tray support is available", variable=minimize).grid(row=2, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Checkbutton(form, text="Start with Windows", variable=autostart).grid(row=3, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Button(
            form,
            text="Save settings",
            style="Primary.TButton",
            command=lambda: self._save_settings(language.get(), theme.get(), minimize.get(), autostart.get()),
        ).grid(row=4, column=0, sticky="w", pady=(16, 0))

    def _page_logs(self) -> None:
        ttk.Label(self.content, text="Launcher runtime log", style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        text = __import__("tkinter").Text(self.content, bg="#111b2b", fg="#c8d5e8", insertbackground="white", relief="flat")
        text.pack(fill=BOTH, expand=True)
        text.insert(END, f"ORION Alpha {__version__}\n")
        text.insert(END, f"Core API: {self.core.base_url}\n")
        text.insert(END, f"Runtime: {self.runtime_dir}\n")
        if self.health is not None:
            for check in self.health.checks:
                text.insert(END, f"{'PASS' if check.passed else 'WARN'} {check.key}: {check.message}\n")
        text.configure(state="disabled")

    def _page_about(self) -> None:
        card = ttk.Frame(self.content, style="Card.TFrame", padding=20)
        card.pack(fill=X)
        ttk.Label(card, text=f"ORION Alpha {__version__}", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(card, text="AI Mission Control and Virtual ATC for DCS World", style="CardText.TLabel").pack(anchor="w", pady=(6, 0))
        ttk.Label(card, text=f"Core API: {self.core.base_url}", style="CardText.TLabel").pack(anchor="w", pady=(6, 0))

    def _health_message(self, key: str) -> str:
        if self.health is None:
            return "Checking…"
        for check in self.health.checks:
            if check.key == key:
                return "Ready" if check.passed else check.message
        return "Unknown"

    def _poll_core(self) -> None:
        if self.core.healthy():
            self.status_var.set(f"ORION Core running\n{self.core.base_url}")
        else:
            self.status_var.set("ORION Core starting…")
        self.root.after(1500, self._poll_core)

    def _refresh_health_async(self) -> None:
        def worker() -> None:
            try:
                report = inspect_startup_health()
            except Exception as exc:
                self.root.after(0, lambda: self.status_var.set(f"Health check failed: {exc}"))
                return
            def apply() -> None:
                self.health = report
                if self.current_page in {"home", "fly", "diagnostics", "logs"}:
                    self.show_page(self.current_page)
            self.root.after(0, apply)

        threading.Thread(target=worker, name="orion-health", daemon=True).start()

    def _launch_dcs_async(self) -> None:
        def worker() -> None:
            status = start_dcs_for_recovery()
            self.root.after(0, lambda: messagebox.showinfo("ORION", status.message))
            self.root.after(0, self._refresh_health_async)
        threading.Thread(target=worker, name="orion-launch-dcs", daemon=True).start()

    def _run_diagnostics_async(self) -> None:
        def worker() -> None:
            try:
                bundle = write_alpha_diagnostics_bundle()
            except Exception as exc:
                self.root.after(0, lambda: messagebox.showerror("Diagnostics", str(exc)))
                return
            self.root.after(0, lambda: messagebox.showinfo("Diagnostics complete", f"Bundle created:\n{bundle}"))
        threading.Thread(target=worker, name="orion-diagnostics", daemon=True).start()

    def _open_diagnostics_folder(self) -> None:
        folder = self.runtime_dir / "diagnostics"
        folder.mkdir(parents=True, exist_ok=True)
        try:
            import os
            os.startfile(folder)  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            messagebox.showinfo("Diagnostics", str(folder))

    def _select_miz(self) -> None:
        path = filedialog.askopenfilename(title="Open DCS mission", filetypes=(("DCS Mission", "*.miz"), ("All files", "*.*")))
        if path:
            messagebox.showinfo("Mission Studio", f"Selected:\n{path}\n\nMission Studio parser/editor is scheduled in #70.")

    def _save_provider(self, provider: str) -> None:
        self.config.ai_provider = provider
        self.config_store.save(self.config)
        messagebox.showinfo("AI Providers", f"Provider preference saved: {provider}")

    def _save_settings(self, language: str, theme: str, minimize: bool, autostart: bool) -> None:
        self.config.language = language
        self.config.theme = theme
        self.config.minimize_to_tray = minimize
        self.config.start_with_windows = autostart
        self.config_store.save(self.config)
        messagebox.showinfo("Settings", "Launcher settings saved.")

    def close(self) -> None:
        self.core.stop()
        self.root.destroy()


def run_desktop_launcher(runtime_dir: Path, host: str = "127.0.0.1", port: int = 8000) -> int:
    core = CoreServer(host, port)
    core.start()
    root = Tk()
    OrionDesktopLauncher(root, runtime_dir=runtime_dir, core=core)
    root.mainloop()
    return 0
