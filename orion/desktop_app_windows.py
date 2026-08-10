from __future__ import annotations

from pathlib import Path
from tkinter import Tk, messagebox

from orion.desktop_app import CoreServer, OrionDesktopLauncher
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
            # Rebuild the shell so navigation and page labels switch language immediately.
            for child in self.root.winfo_children():
                child.destroy()
            self._build_shell()
            self.show_page(self.current_page)
        else:
            self.show_page(self.current_page)


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
