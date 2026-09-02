from __future__ import annotations

from pathlib import Path
from tkinter import TclError, Tk, ttk


# Exact current Launcher-family tokens, intentionally kept in the dev-only tree.
PALETTE = {
    "background": "#070b10",
    "panel": "#0d141d",
    "panel_alt": "#111b27",
    "card": "#111923",
    "card_alt": "#162230",
    "status": "#0b1118",
    "foreground": "#f0f5f8",
    "muted": "#82909d",
    "cyan": "#4ac6d7",
    "cyan_dim": "#173842",
    "amber": "#d6a64d",
    "green": "#5cc98a",
    "red": "#e06b75",
    "unknown": "#a4b0ba",
}

STATUS_GROUPS = {
    "GOOD": {"VERIFIED", "ON", "PASS", "FIELD_PROVEN"},
    "WARN": {"REQUIRED", "PARTIAL", "STALE", "DEFERRED", "CHANGED"},
    "BAD": {"BLOCKED", "ERROR", "MISSING"},
    "UNKNOWN": {"UNKNOWN", "NOT_CHECKED"},
}


def status_group(value: str) -> str:
    normalized = value.upper()
    for group, values in STATUS_GROUPS.items():
        if normalized in values:
            return group
    return "UNKNOWN"


def apply_orion_development_theme(root: Tk, repository_root: Path) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except TclError:
        pass
    p = PALETTE
    root.configure(background=p["background"])
    for name, background in (
        ("Orion.TFrame", p["background"]),
        ("Panel.TFrame", p["panel"]),
        ("PanelAlt.TFrame", p["panel_alt"]),
        ("Card.TFrame", p["card"]),
        ("CardAlt.TFrame", p["card_alt"]),
        ("Status.TFrame", p["status"]),
    ):
        style.configure(name, background=background)
    style.configure("Orion.TLabel", background=p["background"], foreground=p["foreground"], font=("Segoe UI", 10))
    style.configure("Muted.TLabel", background=p["background"], foreground=p["muted"], font=("Segoe UI", 9))
    style.configure("Eyebrow.TLabel", background=p["background"], foreground=p["cyan"], font=("Segoe UI Semibold", 9))
    style.configure("Title.TLabel", background=p["background"], foreground=p["foreground"], font=("Segoe UI Semibold", 24))
    style.configure("Brand.TLabel", background=p["panel"], foreground=p["foreground"], font=("Segoe UI Semibold", 25))
    style.configure("BrandSub.TLabel", background=p["panel"], foreground=p["cyan"], font=("Segoe UI Semibold", 8))
    style.configure("PanelMuted.TLabel", background=p["panel"], foreground=p["muted"], font=("Segoe UI", 9))
    style.configure("CardTitle.TLabel", background=p["card"], foreground=p["foreground"], font=("Segoe UI Semibold", 10))
    style.configure("CardText.TLabel", background=p["card"], foreground=p["muted"], font=("Segoe UI", 9))
    style.configure("CardAltTitle.TLabel", background=p["card_alt"], foreground=p["foreground"], font=("Segoe UI Semibold", 11))
    style.configure("Hero.TLabel", background=p["card_alt"], foreground=p["foreground"], font=("Segoe UI Semibold", 23))
    style.configure("HeroMuted.TLabel", background=p["card_alt"], foreground=p["muted"], font=("Segoe UI", 10))
    style.configure("StatusName.TLabel", background=p["status"], foreground=p["muted"], font=("Segoe UI Semibold", 8))
    for group, colour in (("Good", p["green"]), ("Warn", p["amber"]), ("Bad", p["red"]), ("Unknown", p["unknown"])):
        style.configure(f"Status{group}.TLabel", background=p["status"], foreground=colour, font=("Segoe UI Semibold", 10))
    style.configure("Nav.TButton", anchor="w", padding=(18, 11), relief="flat", borderwidth=0, foreground="#a4b0ba", background=p["panel"], font=("Segoe UI Semibold", 9))
    style.map("Nav.TButton", background=[("active", "#15212c")], foreground=[("active", p["foreground"])])
    style.configure("NavActive.TButton", anchor="w", padding=(18, 11), relief="flat", borderwidth=0, foreground=p["foreground"], background=p["cyan_dim"], font=("Segoe UI Semibold", 9))
    style.configure("Primary.TButton", padding=(18, 11), relief="flat", borderwidth=0, foreground="#031014", background=p["cyan"], font=("Segoe UI Semibold", 9))
    style.map("Primary.TButton", background=[("active", "#6bd7e5"), ("disabled", "#26353b")])
    style.configure("Secondary.TButton", padding=(16, 10), relief="flat", borderwidth=1, foreground=p["foreground"], background="#18232e", font=("Segoe UI Semibold", 9))
    style.map("Secondary.TButton", background=[("active", "#223240")])
    style.configure("TCombobox", fieldbackground=p["panel_alt"], background=p["panel_alt"], foreground=p["foreground"], arrowcolor=p["foreground"])
    style.configure("Treeview", background=p["card"], fieldbackground=p["card"], foreground=p["foreground"], rowheight=28)
    style.configure("Treeview.Heading", background=p["panel_alt"], foreground=p["foreground"], font=("Segoe UI Semibold", 9))
    style.configure("Main.Vertical.TScrollbar", background="#18232e", troughcolor=p["background"], arrowcolor=p["foreground"], borderwidth=0)
    icon = repository_root / "branding" / "orion.ico"
    if icon.is_file():
        try:
            root.iconbitmap(default=str(icon))
        except TclError:
            pass
