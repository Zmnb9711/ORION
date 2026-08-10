from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, BooleanVar, StringVar, Tk, Toplevel, messagebox
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
        cfg = uvicorn.Config("orion.app:app", host=self.host, port=self.port, log_level="warning", access_log=False)
        self._server = uvicorn.Server(cfg)
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
        card = self._card(self.content, self.nav_label("fly"), self._health_text("active_dcs"), 820)
        card.pack(fill=X)
        ttk.Button(card, text=self.t("action.launch_dcs"), style="Primary.TButton", command=self._launch_dcs_async).pack(anchor="w", pady=(14, 0))
        ttk.Button(card, text=self.t("action.run_setup"), command=self._open_setup).pack(anchor="w", pady=(8, 0))

    def _page_mission(self) -> None:
        self._card(self.content, "Mission Studio #70", ".miz analyzer/editor/compiler backend is tracked separately; launcher entry is reserved.", 820).pack(fill=X)

    def _page_diagnostics(self) -> None:
        box = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        box.pack(fill=X)
        if self.health is not None:
            for check in self.health.checks:
                ttk.Label(box, text=f"{'PASS' if check.passed else 'WARN'}  {check.message}", style="CardText.TLabel").pack(anchor="w", pady=3)
        ttk.Button(self.content, text=self.nav_label("diagnostics"), style="Primary.TButton", command=self._diagnostics_async).pack(anchor="w", pady=14)
        ttk.Button(self.content, text=self.t("action.run_setup"), command=self._open_setup).pack(anchor="w")

    def _page_providers(self) -> None:
        choice = StringVar(value=self.config.ai_provider)
        for label, value in (("Auto", "auto"), ("OpenAI", "openai"), ("Yandex Cloud", "yandex"), ("GigaChat", "gigachat"), ("Local AI", "local")):
            row = ttk.Frame(self.content, style="Card.TFrame", padding=14)
            row.pack(fill=X, pady=4)
            ttk.Radiobutton(row, text=label, value=value, variable=choice).pack(side=LEFT)
        ttk.Button(self.content, text="Save", command=lambda: self._save_provider(choice.get())).pack(anchor="w", pady=12)

    def _page_updates(self) -> None:
        ttk.Label(self.content, text=f"{self.t('updates.installed')}: ORION {__version__}", style="Section.TLabel").pack(anchor="w")
        channel = StringVar(value=self.config.update_channel)
        ttk.Combobox(self.content, values=("stable", "beta", "alpha"), state="readonly", textvariable=channel, width=16).pack(anchor="w", pady=8)
        ttk.Button(self.content, text=self.t("action.check_updates"), style="Primary.TButton", command=lambda: self._set_channel_and_check(channel.get())).pack(anchor="w")
        if self.update_progress_text.get():
            ttk.Label(self.content, textvariable=self.update_progress_text, style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
            ttk.Progressbar(self.content, maximum=100, value=self.update_progress).pack(fill=X, pady=4)
        result = self.update_result
        if result and result.latest:
            release = result.latest
            card = self._card(self.content, f"ORION {release.version} — {release.title}", release.notes.strip() or "No release notes supplied.", 850)
            card.pack(fill=X, pady=(14, 8))
            if result.update_available:
                ttk.Button(card, text=f"{self.t('action.install_update')} {release.version}", style="Primary.TButton", command=self._install_update_async).pack(anchor="w", pady=(12, 0))
        ttk.Label(self.content, text=self.t("updates.current"), style="Section.TLabel").pack(anchor="w", pady=(18, 8))
        for feature in current_feature_status():
            self._card(self.content, f"{'✓' if feature.state == 'available' else '○'} {feature.name}", feature.description, 820).pack(fill=X, pady=3)

    def _page_settings(self) -> None:
        language = StringVar(value=self.config.language)
        channel = StringVar(value=self.config.update_channel)
        autostart = BooleanVar(value=self.config.start_with_windows)
        minimize = BooleanVar(value=self.config.minimize_to_tray)
        form = ttk.Frame(self.content, style="Card.TFrame", padding=18)
        form.pack(fill=X)
        ttk.Label(form, text=self.t("settings.language"), style="CardText.TLabel").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Combobox(form, values=("en", "ru"), state="readonly", textvariable=language, width=18).grid(row=0, column=1, padx=16)
        ttk.Label(form, text=self.t("settings.update_channel"), style="CardText.TLabel").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Combobox(form, values=("stable", "beta", "alpha"), state="readonly", textvariable=channel, width=18).grid(row=1, column=1, padx=16)
        ttk.Checkbutton(form, text=self.t("settings.start_windows"), variable=autostart).grid(row=2, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Checkbutton(form, text=self.t("settings.minimize_tray"), variable=minimize).grid(row=3, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Button(form, text="Save", style="Primary.TButton", command=lambda: self._save_settings(language.get(), channel.get(), autostart.get(), minimize.get())).grid(row=4, column=0, sticky="w", pady=(12, 0))

    def _page_logs(self) -> None:
        text = __import__("tkinter").Text(self.content, bg="#111b2b", fg="#c8d5e8", relief="flat")
        text.pack(fill=BOTH, expand=True)
        text.insert(END, f"ORION {__version__}\nCore API: {self.core.base_url}\nRuntime: {self.runtime_dir}\n")
        if self.health:
            for check in self.health.checks:
                text.insert(END, f"{'PASS' if check.passed else 'WARN'} {check.key}: {check.message}\n")
        text.configure(state="disabled")

    def _page_about(self) -> None:
        self._card(self.content, f"ORION {__version__}", "AI Mission Control and Virtual ATC for DCS World", 820).pack(fill=X)

    def _refresh_page(self) -> None:
        if self.current_page == "updates":
            self._check_updates_async(silent=False)
        else:
            self._refresh_health_async()

    def _poll_core(self) -> None:
        state = f"{self.t('status.core_running')}\n{self.core.base_url}" if self.core.healthy() else self.t("status.core_starting")
        self.status_var.set(state)
        self.root.after(1500, self._poll_core)

    def _refresh_health_async(self) -> None:
        def worker() -> None:
            try:
                report = inspect_startup_health()
            except Exception as exc:
                error = str(exc)
                self.root.after(0, lambda message=error: self.status_var.set(f"Health check failed: {message}"))
                return
            self.root.after(0, lambda value=report: self._apply_health(value))
        threading.Thread(target=worker, name="orion-health", daemon=True).start()

    def _apply_health(self, report: StartupHealthReport) -> None:
        self.health = report
        if self.current_page in {"home", "fly", "diagnostics", "logs"}:
            self.show_page(self.current_page)

    def _launch_dcs_async(self) -> None:
        def worker() -> None:
            status = start_dcs_for_recovery()
            self.root.after(0, lambda message=status.message: messagebox.showinfo("ORION", message))
            self.root.after(0, self._refresh_health_async)
        threading.Thread(target=worker, name="orion-launch-dcs", daemon=True).start()

    def _diagnostics_async(self) -> None:
        def worker() -> None:
            try:
                bundle = write_alpha_diagnostics_bundle()
            except Exception as exc:
                error = str(exc)
                self.root.after(0, lambda message=error: messagebox.showerror("Diagnostics", message))
                return
            self.root.after(0, lambda path=str(bundle): messagebox.showinfo("Diagnostics", f"Bundle created:\n{path}"))
        threading.Thread(target=worker, name="orion-diagnostics", daemon=True).start()

    def _channel(self) -> ReleaseChannel:
        try:
            return ReleaseChannel(self.config.update_channel)
        except ValueError:
            return ReleaseChannel.ALPHA

    def _check_updates_async(self, silent: bool) -> None:
        def worker() -> None:
            result = check_for_updates(channel=self._channel())
            self.root.after(0, lambda value=result: self._apply_update(value, silent))
        threading.Thread(target=worker, name="orion-update-check", daemon=True).start()

    def _apply_update(self, result: UpdateCheckResult, silent: bool) -> None:
        self.update_result = result
        if self.current_page in {"home", "updates"}:
            self.show_page(self.current_page)
        if result.update_available and not silent:
            messagebox.showinfo("ORION Update", result.message)

    def _set_channel_and_check(self, channel: str) -> None:
        self.config.update_channel = channel
        self.config_store.save(self.config)
        self._check_updates_async(silent=False)

    def _install_update_async(self) -> None:
        result = self.update_result
        if not result or not result.latest:
            return
        release = result.latest
        if not messagebox.askyesno("ORION Update", f"Install ORION {release.version}?\n\n{release.title}"):
            return
        self.update_progress = 0.0
        self.update_progress_text.set("Downloading update…")
        self.show_page("updates")

        def progress(done: int, total: int | None) -> None:
            percent = min(100.0, done * 100.0 / total) if total else 0.0
            self.root.after(0, lambda value=percent: self._apply_progress(value))

        def worker() -> None:
            try:
                installer = download_update(release, progress=progress)
                launch_installer(installer)
            except Exception as exc:
                error = str(exc)
                self.root.after(0, lambda message=error: messagebox.showerror("ORION Update", message))
        threading.Thread(target=worker, name="orion-update-download", daemon=True).start()

    def _apply_progress(self, percent: float) -> None:
        self.update_progress = percent
        self.update_progress_text.set(f"Downloading… {percent:.0f}%")
        if self.current_page == "updates":
            self.show_page("updates")

    def _save_provider(self, provider: str) -> None:
        self.config.ai_provider = provider
        self.config_store.save(self.config)

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
        self.root.destroy()

    def _maybe_first_run(self) -> None:
        if self.health is None:
            self.root.after(600, self._maybe_first_run)
            return
        if self.health.active_dcs is None and messagebox.askyesno("ORION", "DCS World is not configured. Run setup now?"):
            self._open_setup()

    def _open_setup(self) -> None:
        window = Toplevel(self.root)
        window.title(self.t("setup.title"))
        window.geometry("760x520")
        body = ttk.Frame(window, padding=18)
        body.pack(fill=BOTH, expand=True)
        status = StringVar(value=self.t("setup.detect"))
        ttk.Label(body, textvariable=status, style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        results = ttk.Frame(body)
        results.pack(fill=BOTH, expand=True)

        def detect() -> None:
            for child in results.winfo_children():
                child.destroy()
            found = detect_installations()
            valid = [item for item in (found.discovery.candidates if found.discovery else []) if item.exists]
            status.set(found.message)
            for item in valid:
                card = ttk.Frame(results, padding=10)
                card.pack(fill=X, pady=4)
                ttk.Label(card, text=f"{item.name}: {item.executable_path}").pack(anchor="w")
                ttk.Button(card, text="Select", command=lambda candidate=item: select(candidate)).pack(anchor="w", pady=(6, 0))

        def select(candidate) -> None:
            saved = candidate.saved_games_candidates[0] if candidate.saved_games_candidates else None
            result = select_active_installation(SelectActiveRequest(installation_type=candidate.installation_type, executable_path=candidate.executable_path, install_root=candidate.install_root, saved_games_path=saved, display_name=candidate.name))
            status.set(result.message)

        def install() -> None:
            status.set(install_active_integration().message)
            self._refresh_health_async()

        def test() -> None:
            result = test_live_connection()
            status.set(result.message if not result.ok else self.t("setup.ready"))
            self._refresh_health_async()

        buttons = ttk.Frame(body)
        buttons.pack(fill=X, pady=(12, 0))
        ttk.Button(buttons, text=self.t("setup.detect"), command=detect).pack(side=LEFT, padx=(0, 8))
        ttk.Button(buttons, text=self.t("setup.install"), command=install).pack(side=LEFT, padx=(0, 8))
        ttk.Button(buttons, text=self.t("setup.test"), command=test).pack(side=LEFT)
        detect()

    def close(self) -> None:
        self.core.stop()
        self.root.destroy()


def run_desktop_launcher(runtime_dir: Path, host: str = "127.0.0.1", port: int = 8000) -> int:
    core = CoreServer(host, port)
    core.start()
    root = Tk()
    OrionDesktopLauncher(root, runtime_dir, core)
    root.mainloop()
    return 0
