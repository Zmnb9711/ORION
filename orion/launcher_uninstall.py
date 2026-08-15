from __future__ import annotations

import os
import subprocess
from tkinter import BOTH, LEFT, X, BooleanVar, Toplevel, messagebox
from tkinter import ttk

from orion.active_dcs_installation import active_dcs_installation
from orion.component_uninstall import UninstallComponent, UninstallRequest, uninstaller_command


class LauncherUninstallMixin:
    """Expose explicit component removal from the single user-facing Launcher."""

    def _page_settings(self) -> None:
        super()._page_settings()
        ttk.Separator(self.content, orient="horizontal").pack(fill=X, pady=(24, 18))
        ttk.Label(self.content, text="UNINSTALL", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            self.content,
            text="Remove ORION components independently or remove the complete product. DCS integration is modified safely without deleting other Export.lua integrations.",
            style="Muted.TLabel",
            wraplength=800,
            justify="left",
        ).pack(anchor="w", pady=(4, 10))
        ttk.Button(
            self.content,
            text="UNINSTALL / REMOVE COMPONENTS",
            style="Secondary.TButton",
            command=self._open_uninstall_components,
        ).pack(anchor="w")

    def _open_uninstall_components(self) -> None:
        active = active_dcs_installation.get()
        dcs_path = active.saved_games_path if active else None

        window = Toplevel(self.root)
        window.title("ORION — Uninstall Components")
        window.geometry("680x520")
        window.minsize(620, 480)
        window.transient(self.root)
        try:
            self._apply_window_icon(window)
        except (AttributeError, TypeError):
            pass

        body = ttk.Frame(window, style="Orion.TFrame", padding=22)
        body.pack(fill=BOTH, expand=True)
        ttk.Label(body, text="REMOVE ORION COMPONENTS", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            body,
            text="Choose exactly what should be removed. Components that are not selected will be preserved.",
            style="Muted.TLabel",
            wraplength=610,
            justify="left",
        ).pack(anchor="w", pady=(5, 16))

        remove_all = BooleanVar(value=False)
        launcher = BooleanVar(value=False)
        core = BooleanVar(value=False)
        whisper = BooleanVar(value=False)
        dcs = BooleanVar(value=False)
        component_vars = (launcher, core, whisper, dcs)

        def apply_remove_all() -> None:
            selected = remove_all.get()
            for var in component_vars:
                var.set(selected)
            if selected and not dcs_path:
                dcs.set(False)

        ttk.Checkbutton(
            body,
            text="Remove everything",
            variable=remove_all,
            command=apply_remove_all,
        ).pack(anchor="w", pady=(0, 12))

        box = ttk.Frame(body, style="Card.TFrame", padding=16)
        box.pack(fill=X)
        ttk.Checkbutton(box, text="Launcher", variable=launcher).pack(anchor="w", pady=4)
        ttk.Checkbutton(box, text="Core", variable=core).pack(anchor="w", pady=4)
        ttk.Checkbutton(box, text="Whisper runtime + medium model", variable=whisper).pack(anchor="w", pady=4)
        dcs_button = ttk.Checkbutton(box, text="DCS Integration", variable=dcs)
        dcs_button.pack(anchor="w", pady=4)
        if not dcs_path:
            dcs_button.configure(state="disabled")
            ttk.Label(
                box,
                text="DCS Integration cannot be located safely because no active Saved Games profile is recorded. Remove everything will still remove the complete local ORION installation.",
                style="CardText.TLabel",
                wraplength=570,
                justify="left",
            ).pack(anchor="w", pady=(2, 0))

        ttk.Label(
            body,
            text="Removing Launcher closes this window and starts the standalone ORION uninstall helper. Removing Core stops ORION-Core.exe first.",
            style="Muted.TLabel",
            wraplength=610,
            justify="left",
        ).pack(anchor="w", pady=(16, 12))

        actions = ttk.Frame(body, style="Orion.TFrame")
        actions.pack(fill=X, pady=(8, 0))

        def execute() -> None:
            components: set[UninstallComponent] = set()
            if launcher.get():
                components.add(UninstallComponent.LAUNCHER)
            if core.get():
                components.add(UninstallComponent.CORE)
            if whisper.get():
                components.add(UninstallComponent.WHISPER)
            if dcs.get() and dcs_path:
                components.add(UninstallComponent.DCS_INTEGRATION)

            try:
                request = UninstallRequest(
                    components=components,
                    remove_everything=bool(remove_all.get()),
                    dcs_saved_games_path=dcs_path if dcs.get() else None,
                    parent_pid=os.getpid(),
                )
            except ValueError as exc:
                messagebox.showwarning("ORION Uninstall", str(exc), parent=window)
                return

            summary = "\n".join(f"• {line}" for line in request.summary_lines())
            if request.remove_everything and not dcs_path:
                summary += "\n• DCS Integration: path unknown, will be left untouched"
            if not messagebox.askyesno(
                "ORION Uninstall",
                f"The following will be removed:\n\n{summary}\n\nContinue?",
                parent=window,
            ):
                return

            try:
                command = uninstaller_command(request)
                creationflags = 0
                if os.name == "nt":
                    creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                subprocess.Popen(
                    command,
                    cwd=str(self.runtime_dir),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
            except (OSError, RuntimeError) as exc:
                messagebox.showerror("ORION Uninstall", str(exc), parent=window)
                return

            window.destroy()
            if request.removes_launcher or request.remove_everything:
                self.exit_application()
            else:
                messagebox.showinfo(
                    "ORION Uninstall",
                    "Component removal has started. Launcher status will refresh automatically.",
                    parent=self.root,
                )

        ttk.Button(actions, text="REMOVE SELECTED", style="Primary.TButton", command=execute).pack(side=LEFT, padx=(0, 8))
        ttk.Button(actions, text="CANCEL", style="Secondary.TButton", command=window.destroy).pack(side=LEFT)
