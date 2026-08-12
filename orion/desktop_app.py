from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, BooleanVar, StringVar, Tk, Toplevel, messagebox
from tkinter import ttk

from orion import __version__
from orion.alpha_smoke_diagnostics import write_alpha_diagnostics_bundle
from orion.first_run_actions import (
    SelectActiveRequest,
    detect_installations,
    install_active_integration,
    select_active_installation,
    test_live_connection,
)
from orion.launcher_i18n import normalize_language, translate
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
from orion.windows_autostart import set_autostart


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
        config = LauncherConfig(**{key: value for key, value in payload.items() if key in allowed})
        config.language = normalize_language(config.language)
        return config

    def save(self, config: LauncherConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False), encoding="utf-8")


class CoreServer:
    """Launcher-side lifecycle client for the independent ORION Core process.

    The launcher never hosts ``orion.app`` in-process. In a frozen deployment it
    starts the sibling ``ORION-Core.exe``. During source development it starts
    ``python -m orion.core_main``. If a healthy Core already exists at the
    configured endpoint, the launcher attaches to it and does not own/terminate
    that process.
    """

    def __init__(self, host: str, port: int, runtime_dir: Path | None = None) -> None:
        self.host = host
        self.port = port
        self.runtime_dir = runtime_dir
        self._process: subprocess.Popen[bytes] | None = None
        self._owns_process = False

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def owns_process(self) -> bool:
        return self._owns_process

    def _command(self) -> list[str]:
        override = os.environ.get("ORION_CORE_EXECUTABLE")
        if override:
            return [override, "--host", self.host, "--port", str(self.port)]

        if getattr(sys, "frozen", False):
            sibling = Path(sys.executable).resolve().with_name("ORION-Core.exe")
            if not sibling.is_file():
                raise FileNotFoundError(
                    f"ORION Core is not installed: expected {sibling}. "
                    "Repair or reinstall ORION."
                )
            return [str(sibling), "--host", self.host, "--port", str(self.port)]

        return [sys.executable, "-m", "orion.core_main", "--host", self.host, "--port", str(self.port)]

    def start(self) -> None:
        if self.healthy():
            self._owns_process = False
            return
        if self._process is not None and self._process.poll() is None:
            return

        env = os.environ.copy()
        if self.runtime_dir is not None:
            self.runtime_dir.mkdir(parents=True, exist_ok=True)
            env["ORION_RUNTIME_DIR"] = str(self.runtime_dir)

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        self._process = subprocess.Popen(  # noqa: S603
            self._command(),
            cwd=str(self.runtime_dir.parent if self.runtime_dir is not None else Path.cwd()),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        self._owns_process = True

    def stop(self) -> None:
        process = self._process
        if not self._owns_process or process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        self._process = None
        self._owns_process = False

    def healthy(self, timeout: float = 0.5) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/health", timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8")).get("status") == "ok"
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return False


class OrionDesktopLauncher:
    NAV_KEYS = ("home", "fly", "mission", "diagnostics", "providers", "updates", "settings", "logs", "about")

    def __init__(self, root: Tk, runtime_dir: Path, core: CoreServer) -> None:
        self.root = root
        self.runtime_dir = runtime_dir
        self.core = core
        self.config_store = LauncherConfigStore(runtime_dir)
        self.config = self.config_store.load()
        self.health: StartupHealthReport | None = None
        self.update_result: UpdateCheckResult | None = None
        self.current_page = "home"
        self.status_var = StringVar(value=self.t("status.core_starting"))
        self.page_title = StringVar(value=self.nav_label("home"))
        self.update_progress = 0.0
        self.update_progress_text = StringVar(value="")

        self.root.title(f"ORION {__version__}")
        self.root.geometry("1200x780")
        self.root.minsize(1000, 650)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._style()
        self._build_shell()
        self.show_page("home")
        self._refresh_health_async()
        self._check_updates_async(silent=True)
        self._poll_core()
        self.root.after(900, self._maybe_first_run)

    def t(self, key: str) -> str:
        return translate(key, self.config.language)

    def nav_label(self, key: str) -> str:
        return self.t(f"nav.{key}")

    def _style(self) -> None:
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
        style.configure("Panel.TLabel", background=panel, foreground=fg)
        style.configure("PanelMuted.TLabel", background=panel, foreground=muted)
        style.configure("Title.TLabel", background=bg, foreground=fg, font=("Segoe UI Semibold", 22))
        style.configure("Section.TLabel", background=bg, foreground=fg, font=("Segoe UI Semibold", 14))
        style.configure("CardTitle.TLabel", background=card, foreground=fg, font=("Segoe UI Semibold", 11))
        style.configure("CardText.TLabel", background=card, foreground=muted)
        style.configure("Nav.TButton", anchor="w", padding=(14, 10))
        style.configure("Primary.TButton", padding=(16, 10), foreground="white", background=accent)

    def _build_shell(self) -> None:
        outer = ttk.Frame(self.root, style="Orion.TFrame")
        outer.pack(fill=BOTH, expand=True)
        sidebar = ttk.Frame(outer, style="Panel.TFrame", width=225)
        sidebar.pack(side=LEFT, fill=Y)
        sidebar.pack_propagate(False)
        ttk.Label(sidebar, text="✦ ORION", style="Panel.TLabel", font=("Segoe UI Semibold", 24)).pack(anchor="w", padx=20, pady=(22, 18))
        for key in self.NAV_KEYS:
            ttk.Button(sidebar, text=self.nav_label(key), style="Nav.TButton", command=lambda page=key: self.show_page(page)).pack(fill=X, padx=10, pady=2)
        ttk.Label(sidebar, textvariable=self.status_var, style="PanelMuted.TLabel", wraplength=185).pack(anchor="w", padx=18, pady=14)
        ttk.Label(sidebar, text=f"ORION {__version__}", style="PanelMuted.TLabel").pack(side="bottom", anchor="w", padx=18, pady=18)

        main = ttk.Frame(outer, style="Orion.TFrame")
        main.pack(side=RIGHT, fill=BOTH, expand=True)
        header = ttk.Frame(main, style="Orion.TFrame")
        header.pack(fill=X, padx=28, pady=(22, 12))
        ttk.Label(header, textvariable=self.page_title, style="Title.TLabel").pack(side=LEFT)
        ttk.Button(header, text=self.t("action.refresh"), command=self._refresh_page).pack(side=RIGHT)
        self.content = ttk.Frame(main, style="Orion.TFrame")
        self.content.pack(fill=BOTH, expand=True, padx=28, pady=(0, 20))

    def _clear(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()

    def show_page(self, page: str) -> None:
        self.current_page = page
        self._clear()
        self.page_title.set(self.nav_label(page))
        getattr(self, f"_page_{page}")()

    def _card(self, parent: ttk.Frame, title: str, text: str, wrap: int = 280) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Card.TFrame", padding=16)
        ttk.Label(frame, text=title, style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(frame, text=text, style="CardText.TLabel", wraplength=wrap, justify="left").pack(anchor="w", pady=(6, 0))
        return frame

    def _health_text(self, key: str) -> str:
        if self.health is None:
            return self.t("status.checking")
        for check in self.health.checks:
            if check.key == key:
                return self.t("status.ready") if check.passed else check.message
        return "—"

    def _page_home(self) -> None:
        ttk.Label(self.content, text=f"ORION {__version__}", style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
        row = ttk.Frame(self.content, style="Orion.TFrame")
        row.pack(fill=X)
        for title, value in (("Core API", "Connected" if self.core.healthy() else "Starting"), ("DCS World", self._health_text("active_dcs")), ("Export.lua", self._health_text("export_integration")), ("Telemetry", self._health_text("telemetry"))):
            self._card(row, title, value).pack(side=LEFT, fill=X, expand=True, padx=(0, 10))
        actions = ttk.Frame(self.content, style="Orion.TFrame")
        actions.pack(fill=X, pady=(24, 0))
        fly = self._card(actions, self.nav_label("fly"), "DCS + ORION live telemetry")
        fly.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
        ttk.Button(fly, text=self.t("action.launch_dcs"), style="Primary.TButton", command=self._launch_dcs_async).pack(anchor="w", pady=(14, 0))
        setup = self._card(actions, self.t("setup.title"), "DCS detection, Export.lua integration and telemetry test")
        setup.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
        ttk.Button(setup, text=self.t("action.run_setup"), command=self._open_setup).pack(anchor="w", pady=(14, 0))
        updates = self._card(actions, self.nav_label("updates"), self.update_result.message if self.update_result else self.t("status.checking"))
        updates.pack(side=LEFT, fill=BOTH, expand=True)
        ttk.Button(updates, text=self.t("action.check_updates"), command=lambda: self.show_page("updates")).pack(anchor="w", pady=(14, 0))

    def _page_fly(self) -> None:
        self._card(self.content, self.nav_label("fly"), "Start DCS and keep ORION attached to live telemetry.", 680).pack(fill=X)
        ttk.Button(self.content, text=self.t("action.launch_dcs"), style="Primary.TButton", command=self._launch_dcs_async).pack(anchor="w", pady=(16, 0))

    def _page_mission(self) -> None:
        self._card(self.content, self.nav_label("mission"), "Mission Studio foundation is installed. Mission editor screens remain gated until their backend is complete.", 700).pack(fill=X)

    def _page_diagnostics(self) -> None:
        self._card(self.content, self.nav_label("diagnostics"), "Generate the Alpha diagnostics ZIP with startup, DCS, Export.lua, telemetry and audio readiness.", 700).pack(fill=X)
        ttk.Button(self.content, text=self.t("action.generate_diagnostics"), style="Primary.TButton", command=self._diagnostics_async).pack(anchor="w", pady=(16, 0))

    def _page_providers(self) -> None:
        self._card(self.content, self.nav_label("providers"), "Provider selection configures the desired backend. A provider is not reported connected unless its adapter is available.", 700).pack(fill=X)
        provider = StringVar(value=self.config.ai_provider)
        for key in ("auto", "openai", "yandex", "gigachat", "local"):
            ttk.Radiobutton(self.content, text=key, value=key, variable=provider).pack(anchor="w", pady=3)
        ttk.Button(self.content, text=self.t("action.save"), command=lambda: self._save_provider(provider.get())).pack(anchor="w", pady=(12, 0))

    def _page_updates(self) -> None:
        feature = current_feature_status()
        text = f"Installed: {feature.version}\nChannel: {self.config.update_channel}\n{self.update_result.message if self.update_result else self.t('status.checking')}"
        self._card(self.content, self.nav_label("updates"), text, 760).pack(fill=X)
        controls = ttk.Frame(self.content, style="Orion.TFrame")
        controls.pack(fill=X, pady=(16, 0))
        ttk.Button(controls, text=self.t("action.check_updates"), command=lambda: self._check_updates_async(silent=False)).pack(side=LEFT)
        if self.update_result and self.update_result.update_available and self.update_result.asset:
            ttk.Button(controls, text=self.t("action.install_update"), style="Primary.TButton", command=self._download_update_async).pack(side=LEFT, padx=(8, 0))
        if self.update_progress_text.get():
            ttk.Label(self.content, textvariable=self.update_progress_text, style="Muted.TLabel").pack(anchor="w", pady=(12, 0))

    def _page_settings(self) -> None:
        language = StringVar(value=self.config.language)
        channel = StringVar(value=self.config.update_channel)
        autostart = BooleanVar(value=self.config.start_with_windows)
        minimize = BooleanVar(value=self.config.minimize_to_tray)
        frame = ttk.Frame(self.content, style="Orion.TFrame")
        frame.pack(fill=X)
        ttk.Label(frame, text=self.t("settings.language"), style="Section.TLabel").pack(anchor="w")
        ttk.Combobox(frame, textvariable=language, values=("en", "ru"), state="readonly", width=12).pack(anchor="w", pady=(6, 14))
        ttk.Label(frame, text=self.t("settings.channel"), style="Section.TLabel").pack(anchor="w")
        ttk.Combobox(frame, textvariable=channel, values=("stable", "beta", "alpha"), state="readonly", width=12).pack(anchor="w", pady=(6, 14))
        ttk.Checkbutton(frame, text=self.t("settings.autostart"), variable=autostart).pack(anchor="w", pady=4)
        ttk.Checkbutton(frame, text=self.t("settings.tray"), variable=minimize).pack(anchor="w", pady=4)
        ttk.Button(frame, text=self.t("action.save"), style="Primary.TButton", command=lambda: self._save_settings(language.get(), channel.get(), autostart.get(), minimize.get())).pack(anchor="w", pady=(16, 0))

    def _page_logs(self) -> None:
        text = ttk.Treeview(self.content, columns=("value",), show="tree headings")
        text.heading("#0", text="Path")
        text.heading("value", text="Value")
        text.column("#0", width=260)
        text.column("value", width=600)
        text.insert("", END, text="Runtime", values=(str(self.runtime_dir),))
        text.pack(fill=BOTH, expand=True)

    def _page_about(self) -> None:
        self._card(self.content, "ORION", f"AI mission control and virtual ATC for DCS World\nVersion {__version__}", 700).pack(fill=X)

    def _refresh_page(self) -> None:
        self._refresh_health_async()
        if self.current_page == "updates":
            self._check_updates_async(silent=True)
        self.show_page(self.current_page)

    def _poll_core(self) -> None:
        self.status_var.set(self.t("status.core_ready") if self.core.healthy() else self.t("status.core_starting"))
        self.root.after(1000, self._poll_core)

    def _refresh_health_async(self) -> None:
        def worker() -> None:
            health = inspect_startup_health()
            self.root.after(0, lambda: self._set_health(health))

        threading.Thread(target=worker, name="orion-health", daemon=True).start()

    def _set_health(self, health: StartupHealthReport) -> None:
        self.health = health
        if self.current_page in {"home", "diagnostics"}:
            self.show_page(self.current_page)

    def _launch_dcs_async(self) -> None:
        def worker() -> None:
            result = start_dcs_for_recovery()
            self.root.after(0, lambda: messagebox.showinfo("ORION", result.message))

        threading.Thread(target=worker, name="orion-launch-dcs", daemon=True).start()

    def _diagnostics_async(self) -> None:
        def worker() -> None:
            try:
                bundle = write_alpha_diagnostics_bundle()
                self.root.after(0, lambda: messagebox.showinfo(self.t("diagnostics.title"), str(bundle)))
            except Exception as exc:
                self.root.after(0, lambda: messagebox.showerror(self.t("diagnostics.title"), str(exc)))

        threading.Thread(target=worker, name="orion-diagnostics", daemon=True).start()

    def _check_updates_async(self, silent: bool) -> None:
        def worker() -> None:
            try:
                result = check_for_updates(ReleaseChannel(self.config.update_channel))
            except Exception as exc:
                result = UpdateCheckResult(update_available=False, message=str(exc), release=None, asset=None)
            self.root.after(0, lambda: self._set_update(result, silent))

        threading.Thread(target=worker, name="orion-updates", daemon=True).start()

    def _set_update(self, result: UpdateCheckResult, silent: bool) -> None:
        self.update_result = result
        if self.current_page == "updates":
            self.show_page("updates")
        if not silent and not result.update_available:
            messagebox.showinfo(self.nav_label("updates"), result.message)

    def _download_update_async(self) -> None:
        if not self.update_result or not self.update_result.asset:
            return
        self.update_progress_text.set(self.t("updates.downloading"))
        asset = self.update_result.asset

        def progress(done: int, total: int) -> None:
            pct = 0 if total <= 0 else done * 100 / total
            self.root.after(0, lambda: self.update_progress_text.set(f"{pct:.0f}%"))

        def worker() -> None:
            try:
                path = download_update(asset, self.runtime_dir / "updates", progress=progress)
            except Exception as exc:
                self.root.after(0, lambda: messagebox.showerror(self.nav_label("updates"), str(exc)))
                return
            self.root.after(0, lambda: self._confirm_install(path))

        threading.Thread(target=worker, name="orion-update-download", daemon=True).start()

    def _confirm_install(self, path: Path) -> None:
        if messagebox.askyesno(self.nav_label("updates"), self.t("updates.confirm_install")):
            launch_installer(path)

    def _save_provider(self, provider: str) -> None:
        self.config.ai_provider = provider
        self.config_store.save(self.config)
        messagebox.showinfo("ORION", self.t("settings.saved"))

    def _save_settings(self, language: str, channel: str, autostart: bool, minimize: bool) -> None:
        self.config.language = normalize_language(language)
        self.config.update_channel = channel
        self.config.start_with_windows = autostart
        self.config.minimize_to_tray = minimize
        self.config_store.save(self.config)
        try:
            set_autostart(autostart)
        except OSError as exc:
            messagebox.showwarning("ORION", str(exc))
        messagebox.showinfo("ORION", self.t("settings.saved"))
        self.show_page(self.current_page)

    def _open_setup(self) -> None:
        window = Toplevel(self.root)
        window.title(self.t("setup.title"))
        window.geometry("720x420")
        body = ttk.Frame(window, padding=18)
        body.pack(fill=BOTH, expand=True)
        status = StringVar(value=self.t("setup.detecting"))
        ttk.Label(body, textvariable=status, wraplength=650, justify="left").pack(anchor="w", pady=(0, 12))

        def detect() -> None:
            found = detect_installations()
            if found.discovery and found.discovery.candidates:
                candidate = found.discovery.candidates[0]
                status.set(f"{found.message}\n{candidate.name}: {candidate.executable_path}")
            else:
                status.set(found.message)

        def select() -> None:
            found = detect_installations()
            if not found.discovery or not found.discovery.candidates:
                status.set(found.message)
                return
            candidate = found.discovery.candidates[0]
            selected = select_active_installation(
                SelectActiveRequest(
                    installation_type=candidate.installation_type,
                    install_root=candidate.install_root,
                    executable_path=candidate.executable_path,
                    saved_games_path=candidate.saved_games_candidates[0] if candidate.saved_games_candidates else None,
                )
            )
            status.set(selected.message)

        def install() -> None:
            result = install_active_integration()
            status.set(result.message)
            self._refresh_health_async()

        def test() -> None:
            result = test_live_connection()
            status.set(result.message)
            self._refresh_health_async()

        buttons = ttk.Frame(body)
        buttons.pack(fill=X, pady=(8, 0))
        for label, command in ((self.t("setup.detect"), detect), (self.t("setup.select"), select), (self.t("setup.install"), install), (self.t("setup.test"), test)):
            ttk.Button(buttons, text=label, command=command).pack(side=LEFT, padx=(0, 8))
        ttk.Button(buttons, text=self.t("action.close"), command=window.destroy).pack(side=RIGHT)
        detect()

    def _maybe_first_run(self) -> None:
        if self.health is not None and not self.health.ready:
            self._open_setup()

    def close(self) -> None:
        self.core.stop()
        self.root.destroy()
