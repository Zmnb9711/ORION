from __future__ import annotations

from tkinter import ttk


class LauncherDropdownReadabilityMixin:
    """Apply the proven Audio combobox palette to all Launcher dropdowns."""

    def _style(self) -> None:
        super()._style()
        style = ttk.Style(self.root)
        style.configure(
            "TCombobox",
            fieldbackground="#0f1b26",
            background="#223746",
            foreground="#f7fbfd",
            arrowcolor="#f7fbfd",
            borderwidth=1,
            relief="solid",
            padding=(9, 7),
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#0f1b26"), ("disabled", "#18232e")],
            foreground=[("readonly", "#f7fbfd"), ("disabled", "#7d8b96")],
            selectbackground=[("readonly", "#0f1b26")],
            selectforeground=[("readonly", "#f7fbfd")],
        )
