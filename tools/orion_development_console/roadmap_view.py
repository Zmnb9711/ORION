from __future__ import annotations

import json
import time
import tkinter as tk
from collections.abc import Callable
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, ttk

from tools.orion_development_console.roadmap import RoadmapService
from tools.orion_development_console.memory_models import PromptRecord
from tools.orion_development_console.roadmap_models import (
    BranchType,
    NodeType,
    RoadmapDifferential,
    RoadmapNode,
    RoadmapSnapshot,
)
from tools.orion_development_console.theme import PALETTE


FILTERS = (
    "ALL",
    "MAIN DEVELOPMENT",
    "TEST / EXPERIMENT",
    "FIELD_PROVEN",
    "FAILURES / FIXES",
    "UNFINISHED",
    "SUPERSEDED / REJECTED",
    "DECISIONS",
    "CHECKPOINTS",
    "HISTORICAL RECONNECT",
    "RECOVERED IDEAS",
    "CANONICAL",
)

BRANCH_X = {
    BranchType.MAIN: 190,
    BranchType.TEST_EXPERIMENT: 390,
    BranchType.HISTORICAL_ALTERNATIVE: 590,
    BranchType.GOVERNANCE: 790,
    BranchType.FUTURE: 990,
    BranchType.RECOVERED_FUTURE: 990,
}


def _overview_position(first: float | str, total: int) -> int:
    return max(1, int(float(first) * max(1, total)))


class RoadmapView(ttk.Frame):
    """Launcher-family Canvas renderer over a private derived snapshot."""

    def __init__(
        self,
        parent: ttk.Frame,
        service: RoadmapService,
        *,
        show_text: Callable[[str, str], None],
        show_prompt: Callable[[PromptRecord], None],
    ) -> None:
        super().__init__(parent, style="Orion.TFrame")
        self.service = service
        self.show_text = show_text
        self.show_prompt = show_prompt
        self.snapshot: RoadmapSnapshot | None = service.snapshots.latest()
        self.differential: RoadmapDifferential | None = None
        self.selected_id: str | None = None
        self.collapsed: set[str] = set()
        self.filter_var = tk.StringVar(value="ALL")
        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar(value="ROADMAP: REFRESH_REQUIRED")
        self.metrics_var = tk.StringVar(value="No derived snapshot")
        self.position_var = tk.StringVar(value="Overview: 0 / 0")
        self.render_duration_ms = 0.0
        self.search_duration_ms = 0.0
        self._node_items: dict[int, str] = {}
        self._node_y: dict[str, float] = {}
        self._build()
        if self.snapshot is None:
            self.refresh()
        else:
            self._render()

    def _build(self) -> None:
        header = ttk.Frame(self, style="CardAlt.TFrame", padding=14)
        header.pack(fill=X, pady=(0, 8))
        ttk.Label(header, textvariable=self.status_var, style="CardAltTitle.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            textvariable=self.metrics_var,
            style="HeroMuted.TLabel",
            justify="left",
            wraplength=1220,
        ).pack(anchor="w", pady=(4, 0))
        controls = ttk.Frame(self, style="Orion.TFrame")
        controls.pack(fill=X, pady=(0, 8))
        for caption, command, primary in (
            ("ОБНОВИТЬ", self.refresh, True),
            ("К ТЕКУЩЕЙ ТОЧКЕ", self.jump_current, False),
            ("К НАЧАЛУ", self.jump_top, False),
            ("ПОКАЗАТЬ ИЗМЕНЕНИЯ", self.show_changes, False),
            ("РАЗВЕРНУТЬ ВСЁ", self.expand_all, False),
            ("СВЕРНУТЬ ВЕТКИ", self.collapse_stages, False),
        ):
            ttk.Button(
                controls,
                text=caption,
                style="Primary.TButton" if primary else "Secondary.TButton",
                command=command,
            ).pack(side=LEFT, padx=(0, 6))
        tools = ttk.Frame(self, style="Orion.TFrame")
        tools.pack(fill=X, pady=(0, 8))
        self.search_entry = ttk.Entry(tools, textvariable=self.search_var, width=38)
        self.search_entry.pack(side=LEFT)
        self.search_entry.bind("<Return>", lambda _event: self.search())
        ttk.Button(tools, text="ПОИСК", style="Secondary.TButton", command=self.search).pack(side=LEFT, padx=6)
        ttk.Label(tools, text="ФИЛЬТРЫ", style="Muted.TLabel").pack(side=LEFT, padx=(12, 6))
        combo = ttk.Combobox(tools, textvariable=self.filter_var, values=FILTERS, state="readonly", width=28)
        combo.pack(side=LEFT)
        combo.bind("<<ComboboxSelected>>", lambda _event: self._render())
        ttk.Label(tools, textvariable=self.position_var, style="Muted.TLabel").pack(side=RIGHT)

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill=BOTH, expand=True)
        graph = ttk.Frame(body, style="PanelAlt.TFrame")
        detail = ttk.Frame(body, style="Card.TFrame", width=360)
        body.add(graph, weight=4)
        body.add(detail, weight=1)
        self.canvas = tk.Canvas(
            graph,
            bg=PALETTE["background"],
            highlightthickness=0,
            width=1120,
            height=560,
        )
        scrollbar = ttk.Scrollbar(graph, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._on_scroll(scrollbar.set))
        scrollbar.pack(side=RIGHT, fill=Y)
        self.canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-1>", self._click)

        ttk.Label(detail, text="NODE DETAIL / PROVENANCE", style="CardTitle.TLabel").pack(anchor="w", padx=12, pady=(12, 4))
        self.detail = tk.Text(
            detail,
            wrap="word",
            bg=PALETTE["card"],
            fg=PALETTE["foreground"],
            insertbackground=PALETTE["foreground"],
            relief="flat",
            font=("Segoe UI", 9),
            width=42,
        )
        self.detail.pack(fill=BOTH, expand=True, padx=8, pady=4)
        detail_buttons = ttk.Frame(detail, style="Card.TFrame")
        detail_buttons.pack(fill=X, padx=8, pady=(4, 10))
        ttk.Button(detail_buttons, text="ВСПОМНИТЬ ЭТО", style="Primary.TButton", command=self.recall_selected).pack(side=LEFT)
        ttk.Button(detail_buttons, text="OPEN / SHOW SOURCE", style="Secondary.TButton", command=self.open_selected).pack(side=LEFT, padx=6)
        legend = (
            "LEGEND\n"
            "GREEN · required proof completed\n"
            "GREY · unfinished / planned\n"
            "CYAN/BLUE LINE · test / experimental lineage\n"
            "PURPLE · recovered idea, not implemented\n"
            "Badges preserve FIELD_PROVEN, AUTOMATED_PROVEN, FAILED, SUPERSEDED and other proof states."
        )
        ttk.Label(detail, text=legend, style="CardText.TLabel", justify="left", wraplength=330).pack(fill=X, padx=12, pady=(0, 12))

    def _on_scroll(
        self, setter: Callable[[float, float], object]
    ) -> Callable[[float | str, float | str], None]:
        def update(first: float | str, last: float | str) -> None:
            start = float(first)
            end = float(last)
            setter(start, end)
            if self.snapshot:
                current = _overview_position(start, len(self.snapshot.nodes))
                self.position_var.set(f"Overview: {current} / {len(self.snapshot.nodes)}")
        return update

    def _wheel(self, event: tk.Event) -> str:
        self.canvas.yview_scroll((-1 if event.delta > 0 else 1) * 4, "units")
        return "break"

    def refresh(self) -> None:
        selected = self.selected_id
        at_current = bool(self.snapshot and selected == self.snapshot.current_node_id)
        try:
            self.snapshot, self.differential = self.service.refresh()
        except (OSError, ValueError, RuntimeError) as error:
            self.status_var.set("ROADMAP: ERROR")
            self.show_text("Roadmap refresh failed", f"{type(error).__name__}: {error}")
            return
        self.selected_id = selected if selected and any(node.node_id == selected for node in self.snapshot.nodes) else self.snapshot.current_node_id
        self._render()
        if at_current or selected is None:
            self.jump_current()

    def _render(self) -> None:
        started = time.perf_counter()
        self.canvas.delete("all")
        self._node_items.clear()
        self._node_y.clear()
        if self.snapshot is None:
            return
        freshness = self.service.freshness(self.snapshot)
        self.status_var.set(f"ROADMAP: {freshness.value}")
        stats = self.snapshot.statistics
        self.metrics_var.set(
            f"Last updated: {self.snapshot.generated_at}  ·  HEAD: {self.snapshot.repository_head[:12]}  ·  "
            f"Guard: {self.snapshot.guard_report_id} / {self.snapshot.guard_graph_signature[:12]}  ·  "
            f"Checkpoint: {self.snapshot.latest_checkpoint_id or 'NONE'}  ·  Evidence: {self.snapshot.latest_evidence_id or 'NONE'}  ·  "
            f"Nodes: {stats.nodes}  ·  Edges: {stats.edges}  ·  Current: {self.snapshot.current_node_id}"
        )
        nodes = self.service.filtered_nodes(
            self.snapshot,
            self.filter_var.get(),
            collapsed=self.collapsed,
        )
        previous_y: dict[BranchType, float] = {}
        y = 48.0
        for node in nodes:
            x = BRANCH_X[node.branch_type]
            if node.branch_type in previous_y:
                colour = PALETTE["cyan"] if node.branch_type is BranchType.TEST_EXPERIMENT else "#344654"
                self.canvas.create_line(x, previous_y[node.branch_type] + 28, x, y, fill=colour, width=3 if node.branch_type is BranchType.TEST_EXPERIMENT else 2)
            previous_y[node.branch_type] = y
            self._draw_node(node, x, y)
            y += 84
        self.canvas.configure(scrollregion=(0, 0, 1240, max(620, y + 40)))
        self.position_var.set(f"Overview: 1 / {len(nodes)} visible of {len(self.snapshot.nodes)}")
        self.render_duration_ms = round((time.perf_counter() - started) * 1000, 3)
        if self.selected_id:
            self.select(self.selected_id, jump=False)

    def _draw_node(self, node: RoadmapNode, x: float, y: float) -> None:
        width = 330
        fill = "#17372a" if node.completed else "#1b232c"
        outline = PALETTE["green"] if node.completed else PALETTE["unknown"]
        if node.node_type is NodeType.RECOVERED_IDEA:
            fill, outline = "#2d2340", "#a98bea"
        if node.current:
            outline = PALETTE["cyan"]
        rectangle = self.canvas.create_rectangle(
            x,
            y,
            x + width,
            y + 64,
            fill=fill,
            outline=outline,
            width=3 if node.current else 1,
        )
        prefix = "ТЕКУЩАЯ ТОЧКА · " if node.current else ""
        title = f"{prefix}{node.occurred_at[:10]} · {node.node_type.value} · {node.title}"
        title_item = self.canvas.create_text(
            x + 10,
            y + 10,
            text=title,
            fill=PALETTE["foreground"],
            font=("Segoe UI Semibold", 9),
            anchor="nw",
            width=width - 20,
        )
        badges = " · ".join(badge.value for badge in node.proof_badges) or node.status
        badge_item = self.canvas.create_text(
            x + 10,
            y + 43,
            text=badges,
            fill=PALETTE["cyan"] if node.branch_type is BranchType.TEST_EXPERIMENT else PALETTE["muted"],
            font=("Segoe UI", 8),
            anchor="nw",
            width=width - 20,
        )
        for item in (rectangle, title_item, badge_item):
            self._node_items[item] = node.node_id
        self._node_y[node.node_id] = y

    def _click(self, event: tk.Event) -> None:
        item = self.canvas.find_closest(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        if item and item[0] in self._node_items:
            self.select(self._node_items[item[0]], jump=False)

    def select(self, node_id: str, *, jump: bool = True) -> None:
        if self.snapshot is None:
            return
        node = next((item for item in self.snapshot.nodes if item.node_id == node_id), None)
        if node is None:
            return
        self.selected_id = node_id
        self.detail.configure(state="normal")
        self.detail.delete("1.0", END)
        self.detail.insert("1.0", json.dumps(node.model_dump(mode="json"), ensure_ascii=False, indent=2))
        self.detail.configure(state="disabled")
        if jump and node_id in self._node_y:
            region = self.canvas.bbox("all")
            if region and region[3] > 0:
                self.canvas.yview_moveto(max(0.0, self._node_y[node_id] / region[3] - 0.08))

    def search(self) -> None:
        if self.snapshot is None:
            return
        started = time.perf_counter()
        results = self.service.search(self.snapshot, self.search_var.get())
        self.search_duration_ms = round((time.perf_counter() - started) * 1000, 3)
        if not results:
            self.show_text("Roadmap search", "No matching verified Roadmap node.")
            return
        self.filter_var.set("ALL")
        self.collapsed.clear()
        self._render()
        self.select(results[0].node_id)
        if len(results) > 1:
            self.show_text(
                "Roadmap search results",
                "\n".join(f"{node.node_id} · {node.title}" for node in results[:200]),
            )

    def jump_current(self) -> None:
        if self.snapshot:
            self.filter_var.set("ALL")
            self.collapsed.clear()
            self._render()
            self.select(self.snapshot.current_node_id)

    def jump_top(self) -> None:
        self.canvas.yview_moveto(0.0)

    def expand_all(self) -> None:
        self.collapsed.clear()
        self._render()

    def collapse_stages(self) -> None:
        if self.snapshot:
            self.collapsed = {node.node_id for node in self.snapshot.nodes if node.node_type is NodeType.STAGE}
            self._render()

    def show_changes(self) -> None:
        if self.differential is None:
            self.show_text("Roadmap differential", "No refresh differential is available yet.")
            return
        self.show_text("Roadmap differential", json.dumps(self.differential.model_dump(mode="json"), ensure_ascii=False, indent=2))

    def recall_selected(self) -> None:
        if self.snapshot is None or not self.selected_id:
            return
        try:
            prompt = self.service.recall_node(self.snapshot, self.selected_id)
        except (OSError, ValueError) as error:
            self.show_text("Roadmap recall failed", str(error))
            return
        self.show_prompt(prompt)

    def open_selected(self) -> None:
        if self.snapshot is None or not self.selected_id:
            return
        node = next(item for item in self.snapshot.nodes if item.node_id == self.selected_id)
        self.show_text(node.title, json.dumps(node.model_dump(mode="json"), ensure_ascii=False, indent=2))
