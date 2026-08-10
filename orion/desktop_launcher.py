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
from orion.first_run_actions import (
    SelectActiveRequest,
    detect_installations,
    install_active_integration,
    select_active_installation,
    test_live_connection,
)
from orion.recovery_launch import start_dcs_for_recovery
from orion.startup_health import StartupHealthReport, inspect_startup_health
from orion.update_center import (
    ReleaseChannel,
    UpdateCheckResult,
    check_for_updates,
    current_feature_status,
    download_update,
    launch_installer,
)


@dataclass(slots=True)
class LauncherConfig:
    language: str = "en"
    theme: str = "dark"
    minimize_to_tray: bool = True
    start_with_windows: bool = False
    ai_provider: str = "auto"
    update_channel: str = "alpha"


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
                    "update_channel": config.update_channel,
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
        ("Updates", "updates"),
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
        self.update_result: UpdateCheckResult | None = None
        self.update_progress = 0.0
        self.update_progress_text = StringVar(value="")

        self.root.title(f"ORION Alpha {__version__}")
        self.root.geometry("1180x760")
        self.root.minsize(980, 640)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._configure_style()
        self._build_shell()
        self.show_page("home")
        self._poll_core()
        self._refresh_health_async()
        self._check_updates_async(silent=True)
        self.root.after(900, self._maybe_offer_first_run)

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
        ttk.Label(sidebar, textvariable=self.status_var, style="PanelMuted.TLabel", wraplength=180).pack(anchor="w", padx=18, pady=4)
        ttk.Label(sidebar, text=f"ORION {__version__}", style="PanelMuted.TLabel").pack(side="bottom", anchor="w", padx=18, pady=18)

        main = ttk.Frame(outer, style="Orion.TFrame")
        main.pack(side=RIGHT, fill=BOTH, expand=True)
        header = ttk.Frame(main, style="Orion.TFrame")
        header.pack(fill=X, padx=28, pady=(22, 12))
        ttk.Label(header, textvariable=self.page_title, style="Title.TLabel").pack(side=LEFT)
        ttk.Button(header, text="Refresh", command=self._refresh_current_page).pack(side=RIGHT)
        self.content = ttk.Frame(main, style="Orion.TFrame")
        self.content.pack(fill=BOTH, expand=True, padx=28, pady=(0, 20))

    def _clear_content(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()

    def show_page(self, page: str) -> None:
        self.current_page = page
        self._clear_content()
        self.page_title.set(dict((key, label) for label, key in self.NAV_ITEMS)[page])
        getattr(self, f"_page_{page}")()

    def _refresh_current_page(self) -> None:
        if self.current_page == "updates":
            self._check_updates_async(silent=False)
        else:
            self._refresh_health_async()

    def _card(self, parent: ttk.Frame, title: str, text: str, wrap: int = 250) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Card.TFrame", padding=16)
        ttk.Label(frame, text=title, style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(frame, text=text, style="CardText.TLabel", wraplength=wrap, justify="left").pack(anchor="w", pady=(6, 0))
        return frame

    def _page_home(self) -> None:
        ttk.Label(self.content, text=f"ORION {__version__} control center", style="Muted.TLabel").pack(anchor="w", pady=(0, 14))
        status_row = ttk.Frame(self.content, style="Orion.TFrame")
        status_row.pack(fill=X)
        values = [
            ("Core API", "Connected" if self.core.healthy() else "Starting"),
            ("DCS World", self._health_message("active_dcs")),
            ("Export.lua", self._health_message("export_integration")),
            ("Telemetry", self._health_message("telemetry")),
        ]
        for title, value in values:
            self._card(status_row, title, value).pack(side=LEFT, fill=X, expand=True, padx=(0, 10))

        ttk.Label(self.content, text="Quick start", style="Section.TLabel").pack(anchor="w", pady=(24, 10))
        actions = ttk.Frame(self.content, style="Orion.TFrame")
        actions.pack(fill=X)
        fly = self._card(actions, "Fly with ORION", "Launch DCS using the active ORION profile and wait for live telemetry.")
        fly.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
        ttk.Button(fly, text="Launch DCS", style="Primary.TButton", command=self._launch_dcs_async).pack(anchor="w", pady=(16, 0))
        setup = self._card(actions, "DCS Setup", "Detect DCS, install Export.lua integration and verify live telemetry.")
        setup.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
        ttk.Button(setup, text="Run setup", command=self._open_first_run_wizard).pack(anchor="w", pady=(16, 0))
        update = self._card(actions, "Updates", self._update_summary())
        update.pack(side=LEFT, fill=BOTH, expand=True)
        ttk.Button(update, text="Open Update Center", command=lambda: self.show_page("updates")).pack(anchor="w", pady=(16, 0))

        if self.health is not None:
            ttk.Label(self.content, text="Startup checks", style="Section.TLabel").pack(anchor="w", pady=(24, 10))
            checks = ttk.Frame(self.content, style="Card.TFrame", padding=14)
            checks.pack(fill=X)
            for check in self.health.checks:
                marker = "✓" if check.passed else "!"
                ttk.Label(checks, text=f"{marker}  {check.message}", style="CardText.TLabel").pack(anchor="w", pady=3)

    def _page_fly(self) -> None:
        ttk.Label(self.content, text="Launch DCS with ORION attached", style="Muted.TLabel").pack(anchor="w", pady=(0, 14))
        if self.health is None:
            ttk.Label(self.content, text="Reading DCS configuration…", style="Orion.TLabel").pack(anchor="w")
            return
        card = ttk.Frame(self.content, style="Card.TFrame", padding=18)
        card.pack(fill=X)
        active = self.health.active_dcs
        if active is None:
            ttk.Label(card, text="No active DCS installation is configured.", style="CardTitle.TLabel").pack(anchor="w")
            ttk.Button(card, text="Run DCS setup", style="Primary.TButton", command=self._open_first_run_wizard).pack(anchor="w", pady=(16, 0))
        else:
            ttk.Label(card, text="Active DCS installation", style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(card, text=str(active.executable_path), style="CardText.TLabel", wraplength=780).pack(anchor="w", pady=(6, 0))
            ttk.Button(card, text="Launch DCS", style="Primary.TButton", command=self._launch_dcs_async).pack(anchor="w", pady=(18, 0))
        ttk.Button(self.content, text="Open Core API", command=lambda: webbrowser.open(f"{self.core.base_url}/docs")).pack(anchor="w", pady=18)

    def _page_mission(self) -> None:
        card = self._card(self.content, "Mission Studio", "Mission Studio #70 is present in the launcher. The .miz compiler/editor backend is tracked separately and is not falsely exposed before implementation.", 820)
        card.pack(fill=X)
        ttk.Button(card, text="Open .miz…", command=self._select_miz).pack(anchor="w", pady=(14, 0))

    def _page_diagnostics(self) -> None:
        ttk.Label(self.content, text="System and DCS integration checks", style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
        frame = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        frame.pack(fill=X)
        if self.health is not None:
            for check in self.health.checks:
                ttk.Label(frame, text=("PASS" if check.passed else "WARN") + f"  {check.message}", style="CardText.TLabel").pack(anchor="w", pady=4)
        ttk.Button(self.content, text="Run full diagnostics", style="Primary.TButton", command=self._run_diagnostics_async).pack(anchor="w", pady=16)
        ttk.Button(self.content, text="Run DCS setup / repair", command=self._open_first_run_wizard).pack(anchor="w", pady=(0, 8))
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
        ttk.Button(self.content, text="Save provider preference", style="Primary.TButton", command=lambda: self._save_provider(choice.get())).pack(anchor="w", pady=16)

    def _page_updates(self) -> None:
        channel_var = StringVar(value=self.config.update_channel)
        header = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        header.pack(fill=X)
        ttk.Label(header, text=f"Installed version: ORION {__version__}", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Channel", style="CardText.TLabel").grid(row=1, column=0, sticky="w", pady=(12, 0))
        combo = ttk.Combobox(header, textvariable=channel_var, values=("stable", "beta", "alpha"), state="readonly", width=18)
        combo.grid(row=1, column=1, sticky="w", padx=12, pady=(12, 0))
        ttk.Button(header, text="Save channel", command=lambda: self._save_update_channel(channel_var.get())).grid(row=1, column=2, padx=6, pady=(12, 0))
        ttk.Button(header, text="Check now", style="Primary.TButton", command=lambda: self._check_updates_async(silent=False)).grid(row=0, column=2, padx=6)

        ttk.Label(self.content, text="Current functionality", style="Section.TLabel").pack(anchor="w", pady=(20, 8))
        feature_box = ttk.Frame(self.content, style="Card.TFrame", padding=14)
        feature_box.pack(fill=X)
        for feature in current_feature_status():
            marker = "✓" if feature.state == "available" else "○"
            ttk.Label(feature_box, text=f"{marker} {feature.name} — {feature.description}", style="CardText.TLabel", wraplength=850).pack(anchor="w", pady=2)

        ttk.Label(self.content, text="Latest release", style="Section.TLabel").pack(anchor="w", pady=(20, 8))
        result = self.update_result
        release_box = ttk.Frame(self.content, style="Card.TFrame", padding=14)
        release_box.pack(fill=BOTH, expand=True)
        if result is None:
            ttk.Label(release_box, text="Update check has not completed yet.", style="CardText.TLabel").pack(anchor="w")
        else:
            ttk.Label(release_box, text=result.message, style="CardTitle.TLabel").pack(anchor="w")
            if result.latest is not None:
                latest = result.latest
                meta = f"{latest.title}  •  {latest.published_at or 'date unavailable'}"
                if latest.installer_size is not None:
                    meta += f"  •  {latest.installer_size / (1024 * 1024):.1f} MB"
                ttk.Label(release_box, text=meta, style="CardText.TLabel").pack(anchor="w", pady=(6, 8))
                notes = __import__("tkinter").Text(release_box, height=9, bg="#111b2b", fg="#c8d5e8", relief="flat", wrap="word")
                notes.pack(fill=BOTH, expand=True)
                notes.insert(END, latest.notes or "No release notes were provided.")
                notes.configure(state="disabled")
                if result.update_available and latest.installer_url:
                    ttk.Button(release_box, text="Download and install", style="Primary.TButton", command=self._download_update_async).pack(anchor="w", pady=(10, 0))
        if self.update_progress_text.get():
            ttk.Label(self.content, textvariable=self.update_progress_text, style="Muted.TLabel").pack(anchor="w", pady=(10, 4))
            bar = ttk.Progressbar(self.content, maximum=100, value=self.update_progress, mode="determinate")
            bar.pack(fill=X)

    def _page_settings(self) -> None:
        language = StringVar(value=self.config.language)
        theme = StringVar(value=self.config.theme)
        minimize = BooleanVar(value=self.config.minimize_to_tray)
        autostart = BooleanVar(value=self.config.start_with_windows)
        channel = StringVar(value=self.config.update_channel)
        form = ttk.Frame(self.content, style="Card.TFrame", padding=18)
        form.pack(fill=X)
        ttk.Label(form, text="Language", style="CardText.TLabel").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Combobox(form, textvariable=language, values=("en", "ru"), state="readonly", width=24).grid(row=0, column=1, sticky="w", padx=20)
        ttk.Label(form, text="Theme", style="CardText.TLabel").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Combobox(form, textvariable=theme, values=("dark",), state="readonly", width=24).grid(row=1, column=1, sticky="w", padx=20)
        ttk.Label(form, text="Update channel", style="CardText.TLabel").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Combobox(form, textvariable=channel, values=("stable", "beta", "alpha"), state="readonly", width=24).grid(row=2, column=1, sticky="w", padx=20)
        ttk.Checkbutton(form, text="Minimize to tray when tray support is available", variable=minimize).grid(row=3, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Checkbutton(form, text="Start with Windows", variable=autostart).grid(row=4, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Button(form, text="Save settings", style="Primary.TButton", command=lambda: self._save_settings(language.get(), theme.get(), minimize.get(), autostart.get(), channel.get())).grid(row=5, column=0, sticky="w", pady=(16, 0))

    def _page_logs(self) -> None:
        ttk.Label(self.content, text="Launcher runtime log", style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        text = __import__("tkinter").Text(self.content, bg="#111b2b", fg="#c8d5e8", insertbackground="white", relief="flat")
        text.pack(fill=BOTH, expand=True)
        text.insert(END, f"ORION {__version__}\nCore API: {self.core.base_url}\nRuntime: {self.runtime_dir}\nUpdate channel: {self.config.update_channel}\n")
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
        ttk.Button(card, text="Check for updates", command=lambda: self.show_page("updates")).pack(anchor="w", pady=(14, 0))

    def _health_message(self, key: str) -> str:
        if self.health is None:
            return "Checking…"
        for check in self.health.checks:
            if check.key == key:
                return "Ready" if check.passed else check.message
        return "Unknown"

    def _update_summary(self) -> str:
        if self.update_result is None:
            return f"Installed ORION {__version__}. Checking {self.config.update_channel} channel…"
        return self.update_result.message

    def _poll_core(self) -> None:
        self.status_var.set(f"ORION Core running\n{self.core.base_url}" if self.core.healthy() else "ORION Core starting…")
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

    def _save_update_channel(self, channel: str) -> None:
        self.config.update_channel = channel
        self.config_store.save(self.config)
        self.update_result = None
        self._check_updates_async(silent=False)

    def _save_settings(self, language: str, theme: str, minimize: bool, autostart: bool, channel: str) -> None:
        self.config.language = language
        self.config.theme = theme
        self.config.minimize_to_tray = minimize
        self.config.start_with_windows = autostart
        self.config.update_channel = channel
        self.config_store.save(self.config)
        messagebox.showinfo("Settings", "Launcher settings saved.")

    def _channel(self) -> ReleaseChannel:
        try:
            return ReleaseChannel(self.config.update_channel)
        except ValueError:
            self.config.update_channel = "alpha"
            return ReleaseChannel.ALPHA

    def _check_updates_async(self, silent: bool) -> None:
        def worker() -> None:
            result = check_for_updates(channel=self._channel())
            def apply() -> None:
                self.update_result = result
                if self.current_page in {"updates", "home"}:
                    self.show_page(self.current_page)
                if result.update_available and not silent:
                    messagebox.showinfo("ORION Update", result.message)
            self.root.after(0, apply)
        threading.Thread(target=worker, name="orion-update-check", daemon=True).start()

    def _download_update_async(self) -> None:
        result = self.update_result
        if result is None or result.latest is None:
            return
        release = result.latest
        if not messagebox.askyesno("ORION Update", f"Install ORION {release.version}?\n\n{release.title}"):
            return
        self.update_progress = 0.0
        self.update_progress_text.set("Downloading update…")
        self.show_page("updates")

        def progress(downloaded: int, total: int | None) -> None:
            if total and total > 0:
                percent = min(100.0, downloaded * 100.0 / total)
                label = f"Downloading… {percent:.0f}%"
            else:
                percent = 0.0
                label = f"Downloading… {downloaded / (1024 * 1024):.1f} MB"
            def apply() -> None:
                self.update_progress = percent
                self.update_progress_text.set(label)
                if self.current_page == "updates":
                    self.show_page("updates")
            self.root.after(0, apply)

        def worker() -> None:
            try:
                path = download_update(release, progress=progress)
                self.root.after(0, lambda: self.update_progress_text.set("Download verified. Starting installer…"))
                launch_installer(path)
            except Exception as exc:
                self.root.after(0, lambda: messagebox.showerror("ORION Update", str(exc)))
        threading.Thread(target=worker, name="orion-update-download", daemon=True).start()

    def _maybe_offer_first_run(self) -> None:
        if self.health is None:
            self.root.after(800, self._maybe_offer_first_run)
            return
        if self.health.active_dcs is None:
            if messagebox.askyesno("ORION setup", "DCS World is not configured. Run first-time setup now?"):
                self._open_first_run_wizard()

    def _open_first_run_wizard(self) -> None:
        window = Toplevel(self.root)
        window.title("ORION — DCS Setup")
        window.geometry("700x470")
        window.transient(self.root)
        window.grab_set()
        body = ttk.Frame(window, padding=20)
        body.pack(fill=BOTH, expand=True)
        title_var = StringVar(value="Find DCS World")
        status_var = StringVar(value="Press Detect to search Steam and Standalone installations.")
        ttk.Label(body, textvariable=title_var, font=("Segoe UI Semibold", 18)).pack(anchor="w")
        ttk.Label(body, textvariable=status_var, wraplength=620).pack(anchor="w", pady=(8, 14))
        progress = ttk.Progressbar(body, maximum=100, value=10)
        progress.pack(fill=X, pady=(0, 16))
        listbox = __import__("tkinter").Listbox(body, height=8, bg="#111b2b", fg="#c8d5e8", selectbackground="#2878ff")
        listbox.pack(fill=BOTH, expand=True)
        candidates: list = []
        controls = ttk.Frame(body)
        controls.pack(fill=X, pady=(14, 0))

        def detect() -> None:
            nonlocal candidates
            result = detect_installations()
            candidates = [item for item in (result.discovery.candidates if result.discovery else []) if item.exists]
            listbox.delete(0, END)
            for item in candidates:
                listbox.insert(END, f"{item.name} — {item.executable_path}")
            if candidates:
                listbox.selection_set(0)
                title_var.set("Choose DCS installation")
                status_var.set(f"Found {len(candidates)} installation(s). Select one and continue.")
                progress.configure(value=30)
            else:
                status_var.set("No DCS installation was detected automatically. Verify DCS is installed, then try again.")

        def select_and_install() -> None:
            if not candidates:
                detect()
                return
            selected = listbox.curselection()
            index = int(selected[0]) if selected else 0
            item = candidates[index]
            saved = item.saved_games_candidates[0] if item.saved_games_candidates else None
            payload = SelectActiveRequest(
                installation_type=item.installation_type,
                executable_path=item.executable_path,
                install_root=item.install_root,
                saved_games_path=saved,
                display_name=item.name,
            )
            selected_result = select_active_installation(payload)
            if not selected_result.ok:
                status_var.set(selected_result.message)
                return
            install = install_active_integration(saved)
            progress.configure(value=70)
            title_var.set("Install DCS integration")
            status_var.set(install.message)
            if install.ok:
                title_var.set("Test live connection")
                status_var.set("Integration is installed. Start DCS, enter an aircraft, then press Test connection.")

        def test_connection() -> None:
            result = test_live_connection()
            if result.ok:
                progress.configure(value=100)
                title_var.set("Ready to fly")
                status_var.set(f"Live telemetry connected{f' — {result.aircraft_type}' if result.aircraft_type else ''}.")
                self._refresh_health_async()
            else:
                progress.configure(value=85)
                status_var.set(result.message + ". Start DCS and enter an aircraft, then try again.")

        ttk.Button(controls, text="Detect", command=detect).pack(side=LEFT)
        ttk.Button(controls, text="Select & install", command=select_and_install).pack(side=LEFT, padx=8)
        ttk.Button(controls, text="Test connection", style="Primary.TButton", command=test_connection).pack(side=LEFT)
        ttk.Button(controls, text="Close", command=window.destroy).pack(side=RIGHT)
        detect()

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
