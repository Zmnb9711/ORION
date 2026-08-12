from __future__ import annotations

import threading
from pathlib import Path
from tkinter import BOTH, LEFT, RIGHT, X, StringVar, TclError, Tk, Toplevel, filedialog, messagebox
from tkinter import ttk

from orion.alpha_smoke_diagnostics import write_alpha_diagnostics_bundle
from orion.branding import packaged_icon_path
from orion.desktop_app import CoreServer, OrionDesktopLauncher
from orion.diagnostics_export import copy_diagnostics_bundle, reveal_in_file_manager
from orion.dcs_installations import DcsInstallationType
from orion.first_run_actions import (
    SelectActiveRequest,
    detect_installations,
    install_active_integration,
    select_active_installation,
    test_live_connection,
)
from orion.launcher_i18n import normalize_language
from orion.setup_wizard_model import SetupStep, SetupWizardState
from orion.windows_autostart import set_autostart
from orion.windows_tray import TrayUnavailable, WindowsTrayController


class WindowsOrionDesktopLauncher(OrionDesktopLauncher):
    def __init__(self, root: Tk, runtime_dir: Path, core: CoreServer) -> None:
        self._really_exiting = False
        self._tray = WindowsTrayController(self._request_restore, self._request_exit)
        super().__init__(root, runtime_dir, core)
        self._apply_window_icon(root)

    @staticmethod
    def _apply_window_icon(window: Tk | Toplevel) -> None:
        icon = packaged_icon_path()
        if icon is None:
            return
        try:
            window.iconbitmap(default=str(icon))
        except TclError:
            return

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
        except TclError:
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

    def _diagnostics_async(self) -> None:
        def worker() -> None:
            try:
                bundle = write_alpha_diagnostics_bundle()
            except Exception as exc:
                # Diagnostics are an optional UI boundary. Export failures may come from
                # multiple collectors; surface the failure without terminating Launcher.
                error = str(exc)
                self.root.after(0, lambda message=error: messagebox.showerror(self.t("diagnostics.title"), message))
                return
            self.root.after(0, lambda path=Path(bundle): self._show_diagnostics_result(path))

        threading.Thread(target=worker, name="orion-diagnostics", daemon=True).start()

    def _show_diagnostics_result(self, bundle: Path) -> None:
        window = Toplevel(self.root)
        self._apply_window_icon(window)
        window.title(self.t("diagnostics.title"))
        window.geometry("760x260")
        window.transient(self.root)
        body = ttk.Frame(window, padding=18)
        body.pack(fill=BOTH, expand=True)
        ttk.Label(body, text=self.t("diagnostics.created"), style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, text=str(bundle), wraplength=700, justify="left").pack(anchor="w", pady=(10, 18))
        buttons = ttk.Frame(body)
        buttons.pack(fill=X)
        ttk.Button(buttons, text=self.t("diagnostics.open_folder"), style="Primary.TButton", command=lambda: self._open_diagnostics_folder(bundle)).pack(side=LEFT, padx=(0, 8))
        ttk.Button(buttons, text=self.t("diagnostics.save_as"), command=lambda: self._save_diagnostics_as(bundle)).pack(side=LEFT, padx=(0, 8))
        ttk.Button(buttons, text=self.t("diagnostics.close"), command=window.destroy).pack(side=RIGHT)

    def _open_diagnostics_folder(self, bundle: Path) -> None:
        try:
            reveal_in_file_manager(bundle)
        except OSError as exc:
            messagebox.showerror(self.t("diagnostics.title"), str(exc))

    def _save_diagnostics_as(self, bundle: Path) -> None:
        destination = filedialog.asksaveasfilename(parent=self.root, title=self.t("diagnostics.save_as"), defaultextension=".zip", initialfile=bundle.name, filetypes=(("ZIP", "*.zip"), (self.t("diagnostics.all_files"), "*.*")))
        if not destination:
            return
        try:
            saved = copy_diagnostics_bundle(bundle, Path(destination))
        except OSError as exc:
            messagebox.showerror(self.t("diagnostics.title"), str(exc))
            return
        messagebox.showinfo(self.t("diagnostics.title"), self.t("diagnostics.saved").format(path=saved))

    def _open_setup(self) -> None:
        window = Toplevel(self.root)
        self._apply_window_icon(window)
        window.title(self.t("setup.title"))
        window.geometry("860x610")
        window.minsize(780, 560)
        window.transient(self.root)

        state = SetupWizardState()
        status = StringVar(value="Detecting DCS World…")
        dcs_path = StringVar(value="Not selected")
        saved_games_path = StringVar(value="Not selected")
        step_text = StringVar()

        body = ttk.Frame(window, padding=22)
        body.pack(fill=BOTH, expand=True)
        ttk.Label(body, text="ORION DCS Setup", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="Connect ORION to DCS without giving ORION control of the player aircraft.", wraplength=800, justify="left").pack(anchor="w", pady=(4, 16))
        ttk.Label(body, textvariable=step_text, style="Section.TLabel").pack(anchor="w", pady=(0, 12))

        dcs_box = ttk.LabelFrame(body, text="1. DCS World installation", padding=12)
        dcs_box.pack(fill=X, pady=(0, 10))
        ttk.Label(dcs_box, textvariable=dcs_path, wraplength=650, justify="left").pack(side=LEFT, fill=X, expand=True)

        saved_box = ttk.LabelFrame(body, text="2. Saved Games profile", padding=12)
        saved_box.pack(fill=X, pady=(0, 10))
        ttk.Label(saved_box, textvariable=saved_games_path, wraplength=650, justify="left").pack(side=LEFT, fill=X, expand=True)

        integration_box = ttk.LabelFrame(body, text="3–5. Integration and live telemetry", padding=12)
        integration_box.pack(fill=BOTH, expand=True, pady=(0, 10))
        ttk.Label(integration_box, textvariable=status, wraplength=780, justify="left").pack(anchor="w")

        controls = ttk.Frame(body)
        controls.pack(fill=X, pady=(8, 0))

        def alive() -> bool:
            try:
                return bool(window.winfo_exists())
            except TclError:
                return False

        def on_ui(callback) -> None:  # noqa: ANN001
            if alive():
                window.after(0, callback)

        def render() -> None:
            labels = {
                SetupStep.DCS: "Step 1 of 5 — DCS World",
                SetupStep.SAVED_GAMES: "Step 2 of 5 — Saved Games",
                SetupStep.INTEGRATION: "Step 3 of 5 — Export integration",
                SetupStep.TELEMETRY: "Step 4 of 5 — Live telemetry",
                SetupStep.READY: "Step 5 of 5 — Ready",
            }
            step_text.set(labels[state.step])
            if state.candidate is not None:
                dcs_path.set(str(state.candidate.install_root))
            if state.saved_games_path is not None:
                saved_games_path.set(state.saved_games_path)
            install_button.configure(state="normal" if state.can_install else "disabled")
            test_button.configure(state="normal" if state.can_test else "disabled")
            if state.ready:
                status.set("ORION is connected to DCS telemetry. Setup is complete.")
            elif state.error:
                status.set(state.error)

        def run_worker(name: str, operation, on_success) -> None:  # noqa: ANN001
            def worker() -> None:
                try:
                    value = operation()
                except Exception as exc:
                    # Setup is a UI/process/filesystem boundary. Preserve the Launcher
                    # session and report an adapter failure instead of crashing Tk.
                    error = str(exc)
                    on_ui(lambda: (status.set(error), render()))
                    return
                on_ui(lambda: on_success(value))
            threading.Thread(target=worker, name=name, daemon=True).start()

        def choose_dcs_path(path: str, installation_type: DcsInstallationType = DcsInstallationType.STANDALONE) -> bool:
            if not state.select_dcs(path, installation_type):
                render()
                return False
            candidate = state.candidate
            if candidate and candidate.saved_games_candidates:
                # Show a discovered profile as a suggestion, but keep Saved Games an explicit step.
                status.set(f"DCS found. Select the Saved Games profile. Suggested: {candidate.saved_games_candidates[0]}")
            else:
                status.set("DCS found. Select the Saved Games profile used by this DCS installation.")
            render()
            return True

        def browse_dcs() -> None:
            selected = filedialog.askdirectory(parent=window, title="Select DCS World installation folder")
            if selected:
                choose_dcs_path(selected)

        def browse_saved_games() -> None:
            selected = filedialog.askdirectory(parent=window, title="Select DCS Saved Games profile (for example Saved Games\\DCS)")
            if not selected:
                return
            state.select_saved_games(selected)
            render()

        def detect() -> None:
            status.set("Detecting DCS World installations…")
            detect_button.configure(state="disabled")

            def apply(found) -> None:  # noqa: ANN001
                detect_button.configure(state="normal")
                if not found.candidates:
                    state.error = "DCS World was not found automatically. Use Browse… to select the DCS World folder."
                    state.step = SetupStep.DCS
                    render()
                    return
                candidate = found.candidates[0]
                state.candidate = candidate
                state.error = None
                state.step = SetupStep.SAVED_GAMES
                dcs_path.set(str(candidate.install_root))
                if len(found.candidates) > 1:
                    status.set(f"Found {len(found.candidates)} installations. Using {candidate.name}; use Browse… to choose another one.")
                elif candidate.saved_games_candidates:
                    status.set(f"DCS found. Select Saved Games. Suggested: {candidate.saved_games_candidates[0]}")
                else:
                    status.set("DCS found. Select its Saved Games profile.")
                render()

            run_worker("orion-setup-detect", detect_installations, apply)

        def install() -> None:
            if state.candidate is None or state.saved_games_path is None:
                return
            candidate = state.candidate
            request = SelectActiveRequest(
                installation_type=candidate.installation_type,
                install_root=candidate.install_root,
                executable_path=candidate.executable_path,
                saved_games_path=state.saved_games_path,
            )
            status.set("Saving DCS selection and installing ORION Export integration…")
            install_button.configure(state="disabled")

            def operation():
                selected = select_active_installation(request)
                if not selected.ok:
                    return selected, None
                return selected, install_active_integration()

            def apply(result) -> None:  # noqa: ANN001
                selected, integrated = result
                ok = bool(selected.ok and integrated is not None and integrated.ok)
                state.mark_integration(ok)
                status.set(integrated.message if integrated is not None else selected.message)
                self._refresh_health_async()
                render()

            run_worker("orion-setup-install", operation, apply)

        def test() -> None:
            status.set("Waiting for live DCS telemetry… Start DCS and enter an aircraft if it is not already running.")
            test_button.configure(state="disabled")

            def apply(result) -> None:  # noqa: ANN001
                state.mark_telemetry(bool(result.ok))
                status.set(self.t("setup.ready") if result.ok else result.message)
                self._refresh_health_async()
                render()

            run_worker("orion-setup-test", test_live_connection, apply)

        detect_button = ttk.Button(dcs_box, text="Auto Detect", command=detect)
        detect_button.pack(side=RIGHT, padx=(8, 0))
        ttk.Button(dcs_box, text="Browse…", command=browse_dcs).pack(side=RIGHT, padx=(8, 0))
        ttk.Button(saved_box, text="Browse…", command=browse_saved_games).pack(side=RIGHT, padx=(8, 0))
        install_button = ttk.Button(controls, text="Install / Repair Integration", style="Primary.TButton", command=install, state="disabled")
        install_button.pack(side=LEFT, padx=(0, 8))
        test_button = ttk.Button(controls, text="Test Live Telemetry", command=test, state="disabled")
        test_button.pack(side=LEFT)
        ttk.Button(controls, text="Close", command=window.destroy).pack(side=RIGHT)

        render()
        detect()
