from __future__ import annotations

import threading
from pathlib import Path
from tkinter import BOTH, LEFT, RIGHT, X, StringVar, Tk, Toplevel, messagebox
from tkinter import ttk

from orion.desktop_app import CoreServer, OrionDesktopLauncher
from orion.first_run_actions import (
    SelectActiveRequest,
    detect_installations,
    install_active_integration,
    select_active_installation,
    test_live_connection,
)
from orion.launcher_i18n import normalize_language
from orion.windows_autostart import set_autostart
from orion.windows_tray import TrayUnavailable, WindowsTrayController


class WindowsOrionDesktopLauncher(OrionDesktopLauncher):
    def __init__(self, root: Tk, runtime_dir: Path, core: CoreServer) -> None:
        self._really_exiting = False
        self._tray = WindowsTrayController(self._request_restore, self._request_exit)
        super().__init__(root, runtime_dir, core)

    def _request_restore(self) -> None:
        self.root.after(0, self._restore_from_tray)

    def _request_exit(self) -> None:
        self.root.after(0, self.exit_application)

    def _restore_from_tray(self) -> None:
        self._tray.stop()
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except Exception:
            pass

    def close(self) -> None:
        if self._really_exiting:
            self.exit_application()
            return
        if self.config.minimize_to_tray:
            try:
                self._tray.start()
            except TrayUnavailable:
                self.exit_application()
                return
            self.root.withdraw()
            return
        self.exit_application()

    def exit_application(self) -> None:
        if self._really_exiting:
            return
        self._really_exiting = True
        self._tray.stop()
        self.core.stop()
        self.root.destroy()

    def _save_settings(self, language: str, channel: str, autostart: bool, minimize: bool) -> None:
        previous_language = self.config.language
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
        if self.config.language != previous_language:
            for child in self.root.winfo_children():
                child.destroy()
            self._build_shell()
            self.show_page(self.current_page)
        else:
            self.show_page(self.current_page)

    def _open_setup(self) -> None:
        """Open the Windows first-run/repair flow without blocking Tk's UI thread."""

        window = Toplevel(self.root)
        window.title(self.t("setup.title"))
        window.geometry("760x520")
        body = ttk.Frame(window, padding=18)
        body.pack(fill=BOTH, expand=True)
        status = StringVar(value=self.t("setup.detect"))
        ttk.Label(body, textvariable=status, style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        results = ttk.Frame(body)
        results.pack(fill=BOTH, expand=True)
        controls: list[ttk.Button] = []

        def alive() -> bool:
            try:
                return bool(window.winfo_exists())
            except Exception:
                return False

        def on_ui(callback) -> None:  # noqa: ANN001
            if alive():
                window.after(0, callback)

        def set_busy(message: str | None = None) -> None:
            if message is not None:
                status.set(message)
            for control in controls:
                control.configure(state="disabled")

        def set_idle() -> None:
            for control in controls:
                control.configure(state="normal")

        def show_error(message: str) -> None:
            if not alive():
                return
            status.set(message)
            set_idle()

        def run_worker(name: str, operation, on_success) -> None:  # noqa: ANN001
            def worker() -> None:
                try:
                    value = operation()
                except Exception as exc:
                    error = str(exc)
                    on_ui(lambda message=error: show_error(message))
                    return

                def complete(result=value) -> None:  # noqa: ANN001
                    if not alive():
                        return
                    on_success(result)
                    set_idle()

                on_ui(complete)

            threading.Thread(target=worker, name=name, daemon=True).start()

        def render_candidates(found) -> None:  # noqa: ANN001
            for child in results.winfo_children():
                child.destroy()
            if not found.candidates:
                status.set("DCS World not found")
                return
            status.set(f"Found {len(found.candidates)} DCS installation(s)")
            for candidate in found.candidates:
                frame = ttk.Frame(results, padding=8)
                frame.pack(fill=X, pady=3)
                ttk.Label(frame, text=f"{candidate.name} — {candidate.executable_path}").pack(side=LEFT)
                ttk.Button(
                    frame,
                    text=self.t("setup.select"),
                    command=lambda item=candidate: select(item),
                ).pack(side=RIGHT)

        def detect() -> None:
            set_busy(self.t("setup.detect"))
            run_worker("orion-setup-detect", detect_installations, render_candidates)

        def select(candidate) -> None:  # noqa: ANN001
            request = SelectActiveRequest(
                installation_type=candidate.installation_type,
                install_root=candidate.install_root,
                executable_path=candidate.executable_path,
                saved_games_path=(candidate.saved_games_candidates[0] if candidate.saved_games_candidates else None),
            )

            def apply(result) -> None:  # noqa: ANN001
                status.set(result.message)
                self._refresh_health_async()

            set_busy("Selecting DCS installation…")
            run_worker("orion-setup-select", lambda: select_active_installation(request), apply)

        def install() -> None:
            def apply(result) -> None:  # noqa: ANN001
                status.set(result.message)
                self._refresh_health_async()

            set_busy(self.t("setup.install"))
            run_worker("orion-setup-install", install_active_integration, apply)

        def test() -> None:
            def apply(result) -> None:  # noqa: ANN001
                status.set(result.message if not result.ok else self.t("setup.ready"))
                self._refresh_health_async()

            set_busy(self.t("setup.test"))
            run_worker("orion-setup-test", test_live_connection, apply)

        buttons = ttk.Frame(body)
        buttons.pack(fill=X, pady=(12, 0))
        detect_button = ttk.Button(buttons, text=self.t("setup.detect"), command=detect)
        detect_button.pack(side=LEFT, padx=(0, 8))
        install_button = ttk.Button(buttons, text=self.t("setup.install"), command=install)
        install_button.pack(side=LEFT, padx=(0, 8))
        test_button = ttk.Button(buttons, text=self.t("setup.test"), command=test)
        test_button.pack(side=LEFT)
        controls.extend((detect_button, install_button, test_button))
        detect()


def run_desktop_launcher(runtime_dir: Path, host: str = "127.0.0.1", port: int = 8000) -> int:
    core = CoreServer(host, port)
    core.start()
    try:
        root = Tk()
        WindowsOrionDesktopLauncher(root, runtime_dir=runtime_dir, core=core)
        root.mainloop()
    finally:
        # Tk creation or the main loop can fail before the normal Exit path.
        # Always release Core/UDP resources on every Windows launcher exit.
        core.stop()
    return 0
