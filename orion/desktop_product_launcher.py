from __future__ import annotations

import threading
from pathlib import Path
from tkinter import BOTH, LEFT, RIGHT, X, StringVar, TclError, Tk, Toplevel, filedialog
from tkinter import ttk

from orion.core_process import CoreProcessManager
from orion.desktop_app_windows import WindowsOrionDesktopLauncher
from orion.desktop_product_visual import WindowsProductVisualMixin
from orion.dcs_installations import DcsInstallationType
from orion.first_run_actions import (
    SelectActiveRequest,
    detect_installations,
    install_active_integration,
    select_active_installation,
    test_live_connection,
)
from orion.setup_wizard_model import SetupStep, SetupWizardState


class WindowsOrionProductLauncher(WindowsProductVisualMixin, WindowsOrionDesktopLauncher):
    """Canonical production Windows shell with the polished five-step DCS setup flow."""

    def _open_setup(self) -> None:
        window = Toplevel(self.root)
        self._apply_window_icon(window)
        window.title("ORION — DCS Integration Setup")
        window.geometry("920x670")
        window.minsize(840, 620)
        window.transient(self.root)
        window.configure(background="#070b10")

        state = SetupWizardState()
        status = StringVar(value="Detecting DCS World installations…")
        dcs_path = StringVar(value="Not selected")
        saved_games_path = StringVar(value="Not selected")

        shell = ttk.Frame(window, style="Orion.TFrame", padding=26)
        shell.pack(fill=BOTH, expand=True)

        eyebrow = ttk.Frame(shell, style="Orion.TFrame")
        eyebrow.pack(fill=X)
        ttk.Label(eyebrow, text="ORION", style="Eyebrow.TLabel").pack(side=LEFT)
        ttk.Label(eyebrow, text="DCS INTEGRATION SETUP", style="Muted.TLabel").pack(side=LEFT, padx=(10, 0))

        ttk.Label(shell, text="Connect ORION to DCS", style="Title.TLabel").pack(anchor="w", pady=(5, 2))
        ttk.Label(
            shell,
            text="ORION reads simulator state for ATC and Mission Assistant functions. It does not control the player aircraft.",
            style="Muted.TLabel",
            wraplength=820,
            justify="left",
        ).pack(anchor="w", pady=(0, 18))

        progress = ttk.Frame(shell, style="Status.TFrame", padding=(14, 10))
        progress.pack(fill=X, pady=(0, 18))

        step_names = {
            SetupStep.DCS: "DCS",
            SetupStep.SAVED_GAMES: "SAVED GAMES",
            SetupStep.INTEGRATION: "INTEGRATION",
            SetupStep.TELEMETRY: "TELEMETRY",
            SetupStep.READY: "READY",
        }
        ordered_steps = list(step_names)
        step_labels: dict[SetupStep, ttk.Label] = {}
        for index, step in enumerate(ordered_steps):
            cell = ttk.Frame(progress, style="Status.TFrame")
            cell.pack(side=LEFT, fill=X, expand=True)
            ttk.Label(cell, text=f"0{index + 1}", style="StatusName.TLabel").pack(anchor="w")
            label = ttk.Label(cell, text=step_names[step], style="StatusValue.TLabel")
            label.pack(anchor="w", pady=(1, 0))
            step_labels[step] = label
            if index < len(ordered_steps) - 1:
                ttk.Separator(progress, orient="vertical").pack(side=LEFT, fill="y", padx=10)

        workspace = ttk.Frame(shell, style="CardAlt.TFrame", padding=20)
        workspace.pack(fill=BOTH, expand=True)

        ttk.Label(workspace, text="DCS WORLD INSTALLATION", style="CardAltTitle.TLabel").pack(anchor="w")
        dcs_row = ttk.Frame(workspace, style="CardAlt.TFrame")
        dcs_row.pack(fill=X, pady=(8, 18))
        ttk.Label(dcs_row, textvariable=dcs_path, style="CardAltText.TLabel", wraplength=590, justify="left").pack(side=LEFT, fill=X, expand=True)

        ttk.Label(workspace, text="SAVED GAMES PROFILE", style="CardAltTitle.TLabel").pack(anchor="w")
        saved_row = ttk.Frame(workspace, style="CardAlt.TFrame")
        saved_row.pack(fill=X, pady=(8, 18))
        ttk.Label(saved_row, textvariable=saved_games_path, style="CardAltText.TLabel", wraplength=590, justify="left").pack(side=LEFT, fill=X, expand=True)

        ttk.Separator(workspace, orient="horizontal").pack(fill=X, pady=(2, 16))
        ttk.Label(workspace, text="OPERATIONAL STATUS", style="CardAltTitle.TLabel").pack(anchor="w")
        ttk.Label(workspace, textvariable=status, style="CardAltText.TLabel", wraplength=810, justify="left").pack(anchor="w", pady=(8, 0))

        footer = ttk.Frame(shell, style="Orion.TFrame")
        footer.pack(fill=X, pady=(16, 0))

        def alive() -> bool:
            try:
                return bool(window.winfo_exists())
            except TclError:
                return False

        def on_ui(callback) -> None:  # noqa: ANN001
            if alive():
                window.after(0, callback)

        def step_index(step: SetupStep) -> int:
            return ordered_steps.index(step)

        def render() -> None:
            current_index = step_index(state.step)
            for index, step in enumerate(ordered_steps):
                label = step_labels[step]
                if index < current_index or (step is SetupStep.READY and state.ready):
                    label.configure(style="StatusGood.TLabel")
                elif index == current_index:
                    label.configure(style="StatusValue.TLabel")
                else:
                    label.configure(style="StatusName.TLabel")

            if state.candidate is not None:
                dcs_path.set(str(state.candidate.install_root))
            if state.saved_games_path is not None:
                saved_games_path.set(state.saved_games_path)

            install_button.configure(state="normal" if state.can_install else "disabled")
            test_button.configure(state="normal" if state.can_test else "disabled")

            if state.ready:
                status.set("READY — ORION is receiving live DCS telemetry. Setup is complete.")
            elif state.error:
                status.set(state.error)

        def run_worker(name: str, operation, on_success, on_error=None) -> None:  # noqa: ANN001
            def worker() -> None:
                try:
                    value = operation()
                except Exception as exc:
                    # Worker boundary: setup operations span filesystem, process and
                    # DCS integration adapters with different exception contracts. A
                    # failed operation must surface in the wizard without killing the UI.
                    error = str(exc)

                    def apply_error() -> None:
                        if on_error is not None:
                            on_error(error)
                        else:
                            state.error = error
                            render()

                    on_ui(apply_error)
                    return
                on_ui(lambda: on_success(value))

            threading.Thread(target=worker, name=name, daemon=True).start()

        def choose_dcs_path(path: str, installation_type: DcsInstallationType = DcsInstallationType.STANDALONE) -> bool:
            if not state.select_dcs(path, installation_type):
                render()
                return False
            candidate = state.candidate
            saved_games_path.set("Not selected")
            if candidate and candidate.saved_games_candidates:
                status.set(f"DCS detected. Select the Saved Games profile. Suggested: {candidate.saved_games_candidates[0]}")
            else:
                status.set("DCS detected. Select the Saved Games profile used by this installation.")
            render()
            return True

        def browse_dcs() -> None:
            selected = filedialog.askdirectory(parent=window, title="Select DCS World installation folder")
            if selected:
                choose_dcs_path(selected)

        def browse_saved_games() -> None:
            selected = filedialog.askdirectory(parent=window, title="Select DCS Saved Games profile")
            if not selected:
                return
            if not state.select_saved_games(selected):
                render()
                return
            status.set("Saved Games profile selected. ORION integration is ready to install or repair.")
            render()

        def detect() -> None:
            status.set("Scanning standalone and Steam DCS installations…")
            detect_button.configure(state="disabled")

            def apply(found) -> None:  # noqa: ANN001
                detect_button.configure(state="normal")
                if not found.candidates:
                    state.error = "DCS World was not found automatically. Use SELECT DCS FOLDER to choose it manually."
                    if state.candidate is None:
                        state.step = SetupStep.DCS
                    render()
                    return
                candidate = found.candidates[0]
                state.select_candidate(candidate)
                dcs_path.set(str(candidate.install_root))
                saved_games_path.set("Not selected")
                if len(found.candidates) > 1:
                    status.set(f"Found {len(found.candidates)} DCS installations. Using {candidate.name}; choose another folder manually if needed.")
                elif candidate.saved_games_candidates:
                    status.set(f"DCS detected. Select Saved Games. Suggested: {candidate.saved_games_candidates[0]}")
                else:
                    status.set("DCS detected. Select its Saved Games profile.")
                render()

            def fail(error: str) -> None:
                detect_button.configure(state="normal")
                state.error = f"Automatic DCS detection failed: {error}"
                render()

            run_worker("orion-setup-detect", detect_installations, apply, fail)

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
            status.set("Installing or repairing the ORION Export integration…")
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

            def fail(error: str) -> None:
                state.mark_integration(False)
                state.error = f"Integration operation failed: {error}"
                render()

            run_worker("orion-setup-install", operation, apply, fail)

        def test() -> None:
            status.set("Waiting for live telemetry. Start DCS and enter the cockpit if necessary…")
            test_button.configure(state="disabled")

            def apply(result) -> None:  # noqa: ANN001
                state.mark_telemetry(bool(result.ok))
                status.set("Live telemetry confirmed." if result.ok else result.message)
                self._refresh_health_async()
                render()

            def fail(error: str) -> None:
                state.mark_telemetry(False)
                state.error = f"Telemetry test failed: {error}"
                render()

            run_worker("orion-setup-test", test_live_connection, apply, fail)

        detect_button = ttk.Button(dcs_row, text="AUTO DETECT", style="Secondary.TButton", command=detect)
        detect_button.pack(side=RIGHT, padx=(8, 0))
        ttk.Button(dcs_row, text="SELECT DCS FOLDER", style="Secondary.TButton", command=browse_dcs).pack(side=RIGHT, padx=(8, 0))
        ttk.Button(saved_row, text="SELECT SAVED GAMES", style="Secondary.TButton", command=browse_saved_games).pack(side=RIGHT, padx=(8, 0))

        install_button = ttk.Button(footer, text="INSTALL / REPAIR INTEGRATION", style="Primary.TButton", command=install, state="disabled")
        install_button.pack(side=LEFT, padx=(0, 8))
        test_button = ttk.Button(footer, text="TEST LIVE TELEMETRY", style="Secondary.TButton", command=test, state="disabled")
        test_button.pack(side=LEFT)
        ttk.Button(footer, text="CLOSE", style="Secondary.TButton", command=window.destroy).pack(side=RIGHT)

        render()
        detect()


def run_desktop_launcher(runtime_dir: Path, host: str = "127.0.0.1", port: int = 8000) -> int:
    core = CoreProcessManager(host, port, runtime_dir)
    core.start()
    try:
        root = Tk()
        WindowsOrionProductLauncher(root, runtime_dir=runtime_dir, core=core)
        root.mainloop()
    finally:
        # Closing the launcher detaches the UI; ORION Core intentionally keeps
        # running until an explicit product-level shutdown is requested.
        core.stop()
    return 0
