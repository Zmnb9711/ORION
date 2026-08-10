from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, BooleanVar, StringVar, Tk, filedialog, messagebox
from tkinter import ttk

import uvicorn

from orion import __version__
from orion.alpha_smoke_diagnostics import write_alpha_diagnostics_bundle
from orion.recovery_launch import start_dcs_for_recovery
from orion.startup_health import StartupHealthReport, inspect_startup_health
from orion.update_center import UpdateCheckResult, check_for_updates, current_feature_status, download_update, launch_installer


@dataclass(slots=True)
class LauncherConfig:
    language: str = "en"
    theme: str = "dark"
    minimize_to_tray: bool = True
    start_with_windows: bool = False
    ai_provider: str = "auto"
    check_updates_on_start: bool = True


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
        self.path.write_text(json.dumps({key: getattr(config, key) for key in LauncherConfig.__dataclass_fields__}, indent=2), encoding="utf-8")


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
        config = uvicorn.Config("orion.app:app", host=self.host, port=self.port, log_level="warning", access_log=False)
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
        self.update_status_var = StringVar(value="Update status not checked")

        self.root.title(f"ORION Alpha {__version__}")
        self.root.geometry("1220x790")
        self.root.minsize(1020, 660)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._configure_style()
        self._build_shell()
        self.show_page("home")
        self._poll_core()
        self._refresh_health_async()
        if self.config.check_updates_on_start:
            self._check_updates_async(silent=True)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        bg, panel, card, fg, muted, accent = "#0b1220", "#121c2e", "#17243a", "#eef5ff", "#9baac0", "#2878ff"
        self.root.configure(background=bg)
        for name, background in (("Orion.TFrame", bg), ("Panel.TFrame", panel), ("Card.TFrame", card)):
            style.configure(name, background=background)
        style.configure("Orion.TLabel", background=bg, foreground=fg, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=bg, foreground=muted, font=("Segoe UI", 9))
        style.configure("Panel.TLabel", background=panel, foreground=fg, font=("Segoe UI", 10))
        style.configure("PanelMuted.TLabel", background=panel, foreground=muted, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=bg, foreground=fg, font=("Segoe UI Semibold", 22))
        style.configure("Section.TLabel", background=bg, foreground=fg, font=("Segoe UI Semibold", 14))
        style.configure("CardTitle.TLabel", background=card, foreground=fg, font=("Segoe UI Semibold", 11))
        style.configure("CardText.TLabel", background=card, foreground=muted, font=("Segoe UI", 9))
        style.configure("Nav.TButton", anchor="w", padding=(14, 10), font=("Segoe UI", 10))
        style.configure("Primary.TButton", padding=(16, 10), font=("Segoe UI Semibold", 10), foreground="white", background=accent)
        style.map("Primary.TButton", background=[("active", "#3f8aff")])
        style.configure("TButton", padding=(12, 8))
        style.configure("TCheckbutton", background=bg, foreground=fg)

    def _build_shell(self) -> None:
        outer = ttk.Frame(self.root, style="Orion.TFrame")
        outer.pack(fill=BOTH, expand=True)
        sidebar = ttk.Frame(outer, style="Panel.TFrame", width=225)
        sidebar.pack(side=LEFT, fill=Y)
        sidebar.pack_propagate(False)
        ttk.Label(sidebar, text="✦ ORION", style="Panel.TLabel", font=("Segoe UI Semibold", 24)).pack(anchor="w", padx=20, pady=(22, 20))
        ttk.Label(sidebar, text=f"Alpha {__version__}", style="PanelMuted.TLabel").pack(anchor="w", padx=20, pady=(0, 14))
        for label, key in self.NAV_ITEMS:
            ttk.Button(sidebar, text=label, style="Nav.TButton", command=lambda page=key: self.show_page(page)).pack(fill=X, padx=10, pady=2)
        ttk.Separator(sidebar).pack(fill=X, padx=14, pady=14)
        ttk.Label(sidebar, textvariable=self.status_var, style="PanelMuted.TLabel", wraplength=185).pack(anchor="w", padx=18, pady=4)
        ttk.Label(sidebar, textvariable=self.update_status_var, style="PanelMuted.TLabel", wraplength=185).pack(side="bottom", anchor="w", padx=18, pady=18)

        main = ttk.Frame(outer, style="Orion.TFrame")
        main.pack(side=RIGHT, fill=BOTH, expand=True)
        header = ttk.Frame(main, style="Orion.TFrame")
        header.pack(fill=X, padx=28, pady=(22, 12))
        ttk.Label(header, textvariable=self.page_title, style="Title.TLabel").pack(side=LEFT)
        ttk.Button(header, text="Check updates", command=lambda: self.show_page("updates")).pack(side=RIGHT, padx=(8, 0))
        ttk.Button(header, text="Refresh", command=self._refresh_health_async).pack(side=RIGHT)
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

    def _card(self, parent: ttk.Frame, title: str, text: str, wrap: int = 260) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Card.TFrame", padding=16)
        ttk.Label(frame, text=title, style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(frame, text=text, style="CardText.TLabel", wraplength=wrap, justify="left").pack(anchor="w", pady=(6, 0))
        return frame

    def _page_home(self) -> None:
        ttk.Label(self.content, text=f"Current version: ORION {__version__}", style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
        row = ttk.Frame(self.content, style="Orion.TFrame")
        row.pack(fill=X)
        for title, value in (
            ("Core API", "Connected" if self.core.healthy() else "Starting"),
            ("DCS World", self._health_message("active_dcs")),
            ("Export.lua", self._health_message("export_integration")),
            ("Telemetry", self._health_message("telemetry")),
        ):
            self._card(row, title, value).pack(side=LEFT, fill=X, expand=True, padx=(0, 10))
        ttk.Label(self.content, text="Quick start", style="Section.TLabel").pack(anchor="w", pady=(24, 10))
        actions = ttk.Frame(self.content, style="Orion.TFrame")
        actions.pack(fill=X)
        fly = self._card(actions, "Fly with ORION", "Launch DCS using the active ORION profile.")
        fly.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
        ttk.Button(fly, text="Launch DCS", style="Primary.TButton", command=self._launch_dcs_async).pack(anchor="w", pady=(14, 0))
        diag = self._card(actions, "Diagnostics", "Check DCS, Export.lua, telemetry and audio readiness.")
        diag.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
        ttk.Button(diag, text="Run diagnostics", command=self._run_diagnostics_async).pack(anchor="w", pady=(14, 0))
        updates = self._card(actions, "Updates", self.update_status_var.get())
        updates.pack(side=LEFT, fill=BOTH, expand=True)
        ttk.Button(updates, text="Open Update Center", command=lambda: self.show_page("updates")).pack(anchor="w", pady=(14, 0))

    def _page_fly(self) -> None:
        card = ttk.Frame(self.content, style="Card.TFrame", padding=18)
        card.pack(fill=X)
        if self.health is None or self.health.active_dcs is None:
            ttk.Label(card, text="No active DCS installation is configured.", style="CardTitle.TLabel").pack(anchor="w")
        else:
            ttk.Label(card, text="Active DCS installation", style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(card, text=str(self.health.active_dcs.executable_path), style="CardText.TLabel", wraplength=800).pack(anchor="w", pady=(6, 0))
            ttk.Button(card, text="Launch DCS", style="Primary.TButton", command=self._launch_dcs_async).pack(anchor="w", pady=(16, 0))

    def _page_mission(self) -> None:
        card = self._card(self.content, "Mission Studio", "Mission Studio #70 is reserved in the launcher. .miz analysis/editing will appear here when its deterministic backend lands.", 820)
        card.pack(fill=X)
        ttk.Button(card, text="Select .miz…", command=self._select_miz).pack(anchor="w", pady=(14, 0))

    def _page_diagnostics(self) -> None:
        frame = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        frame.pack(fill=X)
        if self.health is not None:
            for check in self.health.checks:
                ttk.Label(frame, text=("PASS" if check.passed else "WARN") + f"  {check.message}", style="CardText.TLabel").pack(anchor="w", pady=4)
        ttk.Button(self.content, text="Run full diagnostics", style="Primary.TButton", command=self._run_diagnostics_async).pack(anchor="w", pady=16)

    def _page_providers(self) -> None:
        ttk.Label(self.content, text="Approved AI backends", style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
        for label, state in (("Auto", "approved"), ("OpenAI", "approved"), ("Yandex Cloud", "approved"), ("GigaChat", "approved"), ("Local AI", "approved")):
            self._card(self.content, label, state).pack(fill=X, pady=4)

    def _page_updates(self) -> None:
        ttk.Label(self.content, text=f"Installed: ORION {__version__}", style="Section.TLabel").pack(anchor="w")
        ttk.Label(self.content, textvariable=self.update_status_var, style="Muted.TLabel").pack(anchor="w", pady=(4, 12))
        ttk.Button(self.content, text="Check for updates", style="Primary.TButton", command=lambda: self._check_updates_async(silent=False)).pack(anchor="w")
        result = self.update_result
        if result is not None and result.latest is not None:
            release = result.latest
            release_card = ttk.Frame(self.content, style="Card.TFrame", padding=16)
            release_card.pack(fill=X, pady=(16, 8))
            ttk.Label(release_card, text=f"Latest: ORION {release.version} — {release.title}", style="CardTitle.TLabel").pack(anchor="w")
            notes = release.notes.strip() or "No release notes supplied."
            text = __import__("tkinter").Text(release_card, height=8, bg="#111b2b", fg="#c8d5e8", relief="flat", wrap="word")
            text.pack(fill=X, pady=(10, 8))
            text.insert(END, notes)
            text.configure(state="disabled")
            if result.update_available:
                ttk.Button(release_card, text=f"Download and install {release.version}", style="Primary.TButton", command=self._install_update_async).pack(anchor="w")
        ttk.Label(self.content, text="Current functionality", style="Section.TLabel").pack(anchor="w", pady=(18, 8))
        features = ttk.Frame(self.content, style="Card.TFrame", padding=14)
        features.pack(fill=BOTH, expand=True)
        for feature in current_feature_status():
            marker = "✓" if feature.state == "available" else "○"
            ttk.Label(features, text=f"{marker} {feature.name} — {feature.state}", style="CardTitle.TLabel").pack(anchor="w", pady=(3, 0))
            ttk.Label(features, text=feature.description, style="CardText.TLabel", wraplength=820).pack(anchor="w", padx=(18, 0), pady=(0, 3))

    def _page_settings(self) -> None:
        update_check = BooleanVar(value=self.config.check_updates_on_start)
        form = ttk.Frame(self.content, style="Card.TFrame", padding=18)
        form.pack(fill=X)
        ttk.Checkbutton(form, text="Automatically check for ORION updates on launch", variable=update_check).pack(anchor="w", pady=6)
        ttk.Button(form, text="Save settings", style="Primary.TButton", command=lambda: self._save_update_setting(update_check.get())).pack(anchor="w", pady=(12, 0))

    def _page_logs(self) -> None:
        text = __import__("tkinter").Text(self.content, bg="#111b2b", fg="#c8d5e8", relief="flat")
        text.pack(fill=BOTH, expand=True)
        text.insert(END, f"ORION {__version__}\nCore API: {self.core.base_url}\nRuntime: {self.runtime_dir}\nUpdate: {self.update_status_var.get()}\n")
        text.configure(state="disabled")

    def _page_about(self) -> None:
        card = ttk.Frame(self.content, style="Card.TFrame", padding=20)
        card.pack(fill=X)
        ttk.Label(card, text=f"ORION Alpha {__version__}", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(card, text="AI Mission Control and Virtual ATC for DCS World", style="CardText.TLabel").pack(anchor="w", pady=(6, 0))
        ttk.Button(card, text="View functionality and updates", command=lambda: self.show_page("updates")).pack(anchor="w", pady=(14, 0))

    def _health_message(self, key: str) -> str:
        if self.health is None:
            return "Checking…"
        for check in self.health.checks:
            if check.key == key:
                return "Ready" if check.passed else check.message
        return "Unknown"

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
            self.root.after(0, lambda: self._apply_health(report))
        threading.Thread(target=worker, name="orion-health", daemon=True).start()

    def _apply_health(self, report: StartupHealthReport) -> None:
        self.health = report
        if self.current_page in {"home", "fly", "diagnostics", "logs"}:
            self.show_page(self.current_page)

    def _check_updates_async(self, silent: bool) -> None:
        self.update_status_var.set("Checking for updates…")
        def worker() -> None:
            result = check_for_updates()
            self.root.after(0, lambda: self._apply_update_result(result, silent))
        threading.Thread(target=worker, name="orion-update-check", daemon=True).start()

    def _apply_update_result(self, result: UpdateCheckResult, silent: bool) -> None:
        self.update_result = result
        self.update_status_var.set(result.message)
        if self.current_page in {"home", "updates", "logs"}:
            self.show_page(self.current_page)
        if not silent and result.status == "error":
            messagebox.showwarning("ORION Update Center", result.message)

    def _install_update_async(self) -> None:
        result = self.update_result
        if result is None or result.latest is None or not result.update_available:
            return
        release = result.latest
        if not messagebox.askyesno("ORION Update Center", f"Download ORION {release.version} and launch its installer?\n\nYour current installation will not be modified until the installer starts."):
            return
        self.update_status_var.set(f"Downloading ORION {release.version}…")
        def worker() -> None:
            try:
                installer = download_update(release, self.runtime_dir / "updates")
                launch_installer(installer)
            except Exception as exc:
                self.root.after(0, lambda: messagebox.showerror("ORION Update Center", str(exc)))
                self.root.after(0, lambda: self.update_status_var.set("Update failed"))
                return
            self.root.after(0, lambda: messagebox.showinfo("ORION Update Center", "Installer launched. Close ORION when the installer asks to replace the current version."))
            self.root.after(0, lambda: self.update_status_var.set("Installer launched"))
        threading.Thread(target=worker, name="orion-update-download", daemon=True).start()

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

    def _select_miz(self) -> None:
        path = filedialog.askopenfilename(title="Open DCS mission", filetypes=(("DCS Mission", "*.miz"), ("All files", "*.*")))
        if path:
            messagebox.showinfo("Mission Studio", f"Selected:\n{path}\n\nMission Studio parser/editor is scheduled in #70.")

    def _save_update_setting(self, enabled: bool) -> None:
        self.config.check_updates_on_start = enabled
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
