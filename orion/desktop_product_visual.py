from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, BooleanVar, StringVar, TclError, Tk
from tkinter import ttk

from orion import __version__
from orion.desktop_app import CoreServer
from orion.update_center import current_feature_status


class WindowsProductVisualMixin:
    """Shared visual behavior for the canonical Windows product launcher."""

    def __init__(self, root: Tk, runtime_dir: Path, core: CoreServer) -> None:
        self.nav_buttons: dict[str, ttk.Button] = {}
        super().__init__(root, runtime_dir, core)

    def _style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except TclError:
            pass
        bg = "#070b10"; panel = "#0d141d"; panel_alt = "#111b27"; card = "#111923"; card_alt = "#162230"
        fg = "#f0f5f8"; muted = "#82909d"; cyan = "#4ac6d7"; cyan_dim = "#173842"; amber = "#d6a64d"; green = "#5cc98a"
        self.root.configure(background=bg)
        for name, background in (("Orion.TFrame", bg), ("Panel.TFrame", panel), ("PanelAlt.TFrame", panel_alt), ("Card.TFrame", card), ("CardAlt.TFrame", card_alt), ("Status.TFrame", "#0b1118")):
            style.configure(name, background=background)
        style.configure("Orion.TLabel", background=bg, foreground=fg, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=bg, foreground=muted, font=("Segoe UI", 9))
        style.configure("Eyebrow.TLabel", background=bg, foreground=cyan, font=("Segoe UI Semibold", 9))
        style.configure("Title.TLabel", background=bg, foreground=fg, font=("Segoe UI Semibold", 24))
        style.configure("Hero.TLabel", background=card_alt, foreground=fg, font=("Segoe UI Semibold", 23))
        style.configure("HeroMuted.TLabel", background=card_alt, foreground=muted, font=("Segoe UI", 10))
        style.configure("Panel.TLabel", background=panel, foreground=fg)
        style.configure("PanelMuted.TLabel", background=panel, foreground=muted, font=("Segoe UI", 9))
        style.configure("Brand.TLabel", background=panel, foreground=fg, font=("Segoe UI Semibold", 25))
        style.configure("BrandSub.TLabel", background=panel, foreground=cyan, font=("Segoe UI Semibold", 8))
        style.configure("Section.TLabel", background=bg, foreground=fg, font=("Segoe UI Semibold", 14))
        style.configure("CardTitle.TLabel", background=card, foreground=fg, font=("Segoe UI Semibold", 10))
        style.configure("CardText.TLabel", background=card, foreground=muted, font=("Segoe UI", 9))
        style.configure("CardAltTitle.TLabel", background=card_alt, foreground=fg, font=("Segoe UI Semibold", 11))
        style.configure("CardAltText.TLabel", background=card_alt, foreground=muted, font=("Segoe UI", 9))
        style.configure("StatusName.TLabel", background="#0b1118", foreground=muted, font=("Segoe UI Semibold", 8))
        style.configure("StatusValue.TLabel", background="#0b1118", foreground=fg, font=("Segoe UI Semibold", 10))
        style.configure("StatusGood.TLabel", background="#0b1118", foreground=green, font=("Segoe UI Semibold", 10))
        style.configure("StatusWarn.TLabel", background="#0b1118", foreground=amber, font=("Segoe UI Semibold", 10))
        style.configure("Nav.TButton", anchor="w", padding=(18, 11), relief="flat", borderwidth=0, foreground="#a4b0ba", background=panel, font=("Segoe UI Semibold", 9))
        style.map("Nav.TButton", background=[("active", "#15212c")], foreground=[("active", fg)])
        style.configure("NavActive.TButton", anchor="w", padding=(18, 11), relief="flat", borderwidth=0, foreground=fg, background=cyan_dim, font=("Segoe UI Semibold", 9))
        style.map("NavActive.TButton", background=[("active", cyan_dim)])
        style.configure("Primary.TButton", padding=(18, 11), relief="flat", borderwidth=0, foreground="#031014", background=cyan, font=("Segoe UI Semibold", 9))
        style.map("Primary.TButton", background=[("active", "#6bd7e5"), ("disabled", "#26353b")])
        style.configure("Secondary.TButton", padding=(16, 10), relief="flat", borderwidth=1, foreground=fg, background="#18232e", font=("Segoe UI Semibold", 9))
        style.map("Secondary.TButton", background=[("active", "#223240")])
        style.configure("TButton", padding=(12, 8))
        style.configure("TCombobox", fieldbackground=panel_alt, background=panel_alt, foreground=fg)
        style.configure("TCheckbutton", background=card, foreground=fg)
        style.configure("TRadiobutton", background=card, foreground=fg)
        style.configure("TLabelframe", background=bg, foreground=fg)
        style.configure("TLabelframe.Label", background=bg, foreground=cyan)
        style.configure("TProgressbar", background=cyan, troughcolor="#15202b")
        style.configure("Main.Vertical.TScrollbar", background="#18232e", troughcolor=bg, arrowcolor=fg, borderwidth=0)

    def _build_shell(self) -> None:
        self.nav_buttons = {}
        outer = ttk.Frame(self.root, style="Orion.TFrame"); outer.pack(fill=BOTH, expand=True)
        sidebar = ttk.Frame(outer, style="Panel.TFrame", width=248); sidebar.pack(side=LEFT, fill=Y); sidebar.pack_propagate(False)
        brand = ttk.Frame(sidebar, style="Panel.TFrame"); brand.pack(fill=X, padx=20, pady=(22, 18))
        ttk.Label(brand, text="ORION", style="Brand.TLabel").pack(anchor="w")
        ttk.Label(brand, text="ATC & MISSION ASSISTANT", style="BrandSub.TLabel").pack(anchor="w", pady=(1, 0))
        ttk.Separator(sidebar, orient="horizontal").pack(fill=X, padx=16, pady=(0, 12))
        nav = ttk.Frame(sidebar, style="Panel.TFrame"); nav.pack(fill=X)
        nav_captions = {"home":"OVERVIEW","fly":"FLY / DCS","mission":"MISSION","diagnostics":"DIAGNOSTICS","providers":"AI PROVIDERS","updates":"UPDATES","settings":"SETTINGS","logs":"LOGS","about":"ABOUT"}
        for key in self.NAV_KEYS:
            button = ttk.Button(nav, text=nav_captions.get(key, self.nav_label(key)).upper(), style="Nav.TButton", command=lambda page=key: self.show_page(page)); button.pack(fill=X, padx=10, pady=2); self.nav_buttons[key] = button
        footer = ttk.Frame(sidebar, style="Panel.TFrame"); footer.pack(side="bottom", fill=X, padx=18, pady=18)
        ttk.Label(footer, text="CORE STATUS", style="BrandSub.TLabel").pack(anchor="w")
        ttk.Label(footer, textvariable=self.status_var, style="PanelMuted.TLabel", wraplength=200, justify="left").pack(anchor="w", pady=(4, 12))
        ttk.Label(footer, text=f"ORION {__version__}  •  ALPHA", style="PanelMuted.TLabel").pack(anchor="w")

        main = ttk.Frame(outer, style="Orion.TFrame"); main.pack(side=RIGHT, fill=BOTH, expand=True)
        header = ttk.Frame(main, style="Orion.TFrame"); header.pack(fill=X, padx=30, pady=(20, 10))
        title_box = ttk.Frame(header, style="Orion.TFrame"); title_box.pack(side=LEFT)
        ttk.Label(title_box, text="ORION COMMAND CONSOLE", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(title_box, textvariable=self.page_title, style="Title.TLabel").pack(anchor="w")
        ttk.Button(header, text="REFRESH", style="Secondary.TButton", command=self._refresh_page).pack(side=RIGHT, pady=(8, 0))
        self.status_strip = ttk.Frame(main, style="Status.TFrame", padding=(16, 10)); self.status_strip.pack(fill=X, padx=30, pady=(0, 14))

        # Only the page body scrolls. Header/status and the left navigation stay fixed.
        viewport = ttk.Frame(main, style="Orion.TFrame"); viewport.pack(fill=BOTH, expand=True, padx=(30, 12), pady=(0, 24))
        self._content_canvas = tk.Canvas(viewport, bg="#070b10", highlightthickness=0, borderwidth=0)
        self._content_scrollbar = ttk.Scrollbar(viewport, orient="vertical", style="Main.Vertical.TScrollbar", command=self._content_canvas.yview)
        self._content_canvas.configure(yscrollcommand=self._content_scrollbar.set)
        self._content_scrollbar.pack(side=RIGHT, fill=Y)
        self._content_canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self.content = ttk.Frame(self._content_canvas, style="Orion.TFrame")
        self._content_window = self._content_canvas.create_window((0, 0), window=self.content, anchor="nw")

        def sync_scroll_region(_event=None) -> None:  # noqa: ANN001
            self._content_canvas.configure(scrollregion=self._content_canvas.bbox("all"))

        def sync_width(event) -> None:  # noqa: ANN001
            self._content_canvas.itemconfigure(self._content_window, width=event.width)

        def wheel(event) -> str:  # noqa: ANN001
            delta = -1 if event.delta > 0 else 1
            self._content_canvas.yview_scroll(delta * 3, "units")
            return "break"

        self.content.bind("<Configure>", sync_scroll_region)
        self._content_canvas.bind("<Configure>", sync_width)
        self._content_canvas.bind("<Enter>", lambda _event: self._content_canvas.bind_all("<MouseWheel>", wheel))
        self._content_canvas.bind("<Leave>", lambda _event: self._content_canvas.unbind_all("<MouseWheel>"))

    def show_page(self, page: str) -> None:
        self.current_page = page
        for key, button in self.nav_buttons.items(): button.configure(style="NavActive.TButton" if key == page else "Nav.TButton")
        self._render_status_strip(); self._clear(); self.page_title.set(self.nav_label(page).upper()); getattr(self, f"_page_{page}")()
        if hasattr(self, "_content_canvas"):
            self._content_canvas.update_idletasks(); self._content_canvas.configure(scrollregion=self._content_canvas.bbox("all")); self._content_canvas.yview_moveto(0.0)

    def _render_status_strip(self) -> None:
        if not hasattr(self, "status_strip"): return
        for child in self.status_strip.winfo_children(): child.destroy()
        values=[("CORE","CONNECTED" if self.core.healthy() else "STARTING",self.core.healthy()),("DCS",self._compact_health("active_dcs"),self._health_passed("active_dcs")),("TELEMETRY",self._compact_health("telemetry"),self._health_passed("telemetry")),("AI",self.config.ai_provider.upper(),True)]
        for index,(name,value,good) in enumerate(values):
            cell=ttk.Frame(self.status_strip,style="Status.TFrame"); cell.pack(side=LEFT,fill=X,expand=True); ttk.Label(cell,text=name,style="StatusName.TLabel").pack(anchor="w"); ttk.Label(cell,text=value,style="StatusGood.TLabel" if good else "StatusWarn.TLabel").pack(anchor="w",pady=(1,0))
            if index < len(values)-1: ttk.Separator(self.status_strip,orient="vertical").pack(side=LEFT,fill=Y,padx=14)

    def _health_passed(self,key:str)->bool:
        if self.health is None:return False
        return any(check.key==key and check.passed for check in self.health.checks)
    def _compact_health(self,key:str)->str:
        if self.health is None:return "CHECKING"
        for check in self.health.checks:
            if check.key==key:return "READY" if check.passed else "ATTENTION"
        return "UNKNOWN"

    def _page_home(self) -> None:
        dcs_ready=self._health_passed("active_dcs"); export_ready=self._health_passed("export_integration"); telemetry_ready=self._health_passed("telemetry"); operational=self.core.healthy() and dcs_ready and export_ready and telemetry_ready
        hero=ttk.Frame(self.content,style="CardAlt.TFrame",padding=22); hero.pack(fill=X); ttk.Label(hero,text="SYSTEM STATUS",style="CardAltTitle.TLabel").pack(anchor="w"); ttk.Label(hero,text="MISSION READY" if operational else "SETUP REQUIRED",style="Hero.TLabel").pack(anchor="w",pady=(8,3)); message="DCS integration and live telemetry are ready. ORION is standing by as ATC & Mission Assistant." if operational else "Complete DCS setup and establish live telemetry before the first full flight test."; ttk.Label(hero,text=message,style="HeroMuted.TLabel",wraplength=760,justify="left").pack(anchor="w"); actions=ttk.Frame(hero,style="CardAlt.TFrame"); actions.pack(fill=X,pady=(18,0)); ttk.Button(actions,text="LAUNCH DCS",style="Primary.TButton",command=self._launch_dcs_async).pack(side=LEFT,padx=(0,9)); ttk.Button(actions,text="DCS SETUP",style="Secondary.TButton",command=self._open_setup).pack(side=LEFT,padx=(0,9)); ttk.Button(actions,text="CHECK UPDATES",style="Secondary.TButton",command=lambda:self.show_page("updates")).pack(side=LEFT)
        ttk.Label(self.content,text="OPERATIONAL READINESS",style="Section.TLabel").pack(anchor="w",pady=(22,10)); row=ttk.Frame(self.content,style="Orion.TFrame"); row.pack(fill=X); readiness=[("DCS WORLD","Detected and selected" if dcs_ready else self._health_text("active_dcs")),("EXPORT INTEGRATION","Installed" if export_ready else self._health_text("export_integration")),("LIVE TELEMETRY","Receiving data" if telemetry_ready else self._health_text("telemetry"))]
        for index,(title,text) in enumerate(readiness): self._card(row,title,text,wrap=260).pack(side=LEFT,fill=BOTH,expand=True,padx=(0,10 if index<len(readiness)-1 else 0))
        ttk.Label(self.content,text="CURRENT BUILD",style="Section.TLabel").pack(anchor="w",pady=(22,10)); build=ttk.Frame(self.content,style="Card.TFrame",padding=16); build.pack(fill=X); ttk.Label(build,text=f"ORION {__version__}",style="CardTitle.TLabel").pack(anchor="w"); update_text=self.update_result.message if self.update_result else "Checking release channel…"; ttk.Label(build,text=update_text,style="CardText.TLabel",wraplength=760,justify="left").pack(anchor="w",pady=(5,0))

    def _page_fly(self) -> None:
        ready=self._health_passed("active_dcs") and self._health_passed("telemetry"); hero=ttk.Frame(self.content,style="CardAlt.TFrame",padding=22); hero.pack(fill=X); ttk.Label(hero,text="LIVE FLIGHT LINK",style="CardAltTitle.TLabel").pack(anchor="w"); ttk.Label(hero,text="READY FOR DCS" if ready else "DCS LINK NOT READY",style="Hero.TLabel").pack(anchor="w",pady=(8,3)); ttk.Label(hero,text=self._health_text("active_dcs"),style="HeroMuted.TLabel",wraplength=780,justify="left").pack(anchor="w"); buttons=ttk.Frame(hero,style="CardAlt.TFrame"); buttons.pack(fill=X,pady=(18,0)); ttk.Button(buttons,text="LAUNCH DCS",style="Primary.TButton",command=self._launch_dcs_async).pack(side=LEFT,padx=(0,9)); ttk.Button(buttons,text="DCS SETUP",style="Secondary.TButton",command=self._open_setup).pack(side=LEFT)

    def _page_mission(self) -> None:
        hero=ttk.Frame(self.content,style="CardAlt.TFrame",padding=22); hero.pack(fill=X); ttk.Label(hero,text="MISSION WORKSPACE",style="CardAltTitle.TLabel").pack(anchor="w"); ttk.Label(hero,text="MISSION STUDIO",style="Hero.TLabel").pack(anchor="w",pady=(8,3)); ttk.Label(hero,text="Mission analysis, briefing and preparation will be surfaced here while the dedicated mission backend continues to evolve.",style="HeroMuted.TLabel",wraplength=780,justify="left").pack(anchor="w")

    def _page_diagnostics(self) -> None:
        ttk.Label(self.content,text="SYSTEM CHECKS",style="Section.TLabel").pack(anchor="w",pady=(0,10)); box=ttk.Frame(self.content,style="Card.TFrame",padding=18); box.pack(fill=X)
        if self.health is None: ttk.Label(box,text="Running diagnostics…",style="CardText.TLabel").pack(anchor="w")
        else:
            for check in self.health.checks: ttk.Label(box,text=f"{'PASS' if check.passed else 'WARN'}  {check.message}",style="CardText.TLabel").pack(anchor="w",pady=3)
        buttons=ttk.Frame(self.content,style="Orion.TFrame"); buttons.pack(fill=X,pady=(14,0)); ttk.Button(buttons,text="EXPORT DIAGNOSTICS",style="Primary.TButton",command=self._diagnostics_async).pack(side=LEFT,padx=(0,9)); ttk.Button(buttons,text="DCS SETUP",style="Secondary.TButton",command=self._open_setup).pack(side=LEFT)

    def _page_providers(self) -> None:
        ttk.Label(self.content,text="AI ROUTING",style="Section.TLabel").pack(anchor="w",pady=(0,10)); choice=StringVar(value=self.config.ai_provider)
        for label,value,description in (("AUTO","auto","Let ORION choose the configured provider."),("OPENAI","openai","OpenAI cloud provider."),("YANDEX CLOUD","yandex","Yandex Cloud provider."),("GIGACHAT","gigachat","GigaChat provider."),("LOCAL AI","local","Local inference provider.")):
            row=ttk.Frame(self.content,style="Card.TFrame",padding=14); row.pack(fill=X,pady=4); ttk.Radiobutton(row,text=label,value=value,variable=choice).pack(side=LEFT); ttk.Label(row,text=description,style="CardText.TLabel").pack(side=LEFT,padx=(16,0))
        ttk.Button(self.content,text="SAVE PROVIDER",style="Primary.TButton",command=lambda:self._save_provider(choice.get())).pack(anchor="w",pady=14)

    def _page_updates(self) -> None:
        ttk.Label(self.content,text="UPDATE CENTER",style="Section.TLabel").pack(anchor="w",pady=(0,10)); status=self.update_result.message if self.update_result else "Checking for updates…"; self._card(self.content,"CHANNEL",f"{self.config.update_channel.upper()} — {status}",wrap=760).pack(fill=X); ttk.Button(self.content,text="CHECK NOW",style="Primary.TButton",command=lambda:self._check_updates_async(silent=False)).pack(anchor="w",pady=14)

    def _page_settings(self) -> None:
        language=StringVar(value=self.config.language); channel=StringVar(value=self.config.update_channel); autostart=BooleanVar(value=self.config.start_with_windows); minimize=BooleanVar(value=self.config.minimize_to_tray); ttk.Label(self.content,text="LAUNCHER SETTINGS",style="Section.TLabel").pack(anchor="w",pady=(0,10)); form=ttk.Frame(self.content,style="Card.TFrame",padding=18); form.pack(fill=X); ttk.Label(form,text=self.t("settings.language"),style="CardText.TLabel").grid(row=0,column=0,sticky="w",pady=8); ttk.Combobox(form,values=("en","ru"),state="readonly",textvariable=language,width=18).grid(row=0,column=1,padx=16,sticky="w"); ttk.Label(form,text=self.t("settings.update_channel"),style="CardText.TLabel").grid(row=1,column=0,sticky="w",pady=8); ttk.Combobox(form,values=("stable","beta","alpha"),state="readonly",textvariable=channel,width=18).grid(row=1,column=1,padx=16,sticky="w"); ttk.Checkbutton(form,text=self.t("settings.start_windows"),variable=autostart).grid(row=2,column=0,columnspan=2,sticky="w",pady=8); ttk.Checkbutton(form,text=self.t("settings.minimize_tray"),variable=minimize).grid(row=3,column=0,columnspan=2,sticky="w",pady=8); ttk.Button(form,text="SAVE SETTINGS",style="Primary.TButton",command=lambda:self._save_settings(language.get(),channel.get(),autostart.get(),minimize.get())).grid(row=4,column=0,sticky="w",pady=(14,0))

    def _page_logs(self) -> None:
        ttk.Label(self.content,text="RUNTIME LOG",style="Section.TLabel").pack(anchor="w",pady=(0,10)); text=tk.Text(self.content,height=24,bg="#0b1118",fg="#c6d2dc",insertbackground="#f0f5f8",relief="flat",font=("Consolas",9)); text.pack(fill=BOTH,expand=True); log=self.runtime_dir/"orion.log"; text.insert(END,log.read_text(encoding="utf-8",errors="replace")[-18000:] if log.is_file() else "No runtime log has been written yet."); text.configure(state="disabled")

    def _page_about(self) -> None:
        hero=ttk.Frame(self.content,style="CardAlt.TFrame",padding=22); hero.pack(fill=X); ttk.Label(hero,text="ORION",style="Hero.TLabel").pack(anchor="w"); ttk.Label(hero,text="ATC & Mission Assistant for DCS World",style="HeroMuted.TLabel").pack(anchor="w",pady=(4,12)); ttk.Label(hero,text=f"Version {__version__}\nArchitecture: local Core + modular AI providers\nPlayer-aircraft control: disabled by design",style="CardAltText.TLabel",justify="left").pack(anchor="w")
