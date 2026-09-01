"""First-class Launcher surface for Core-owned Communication Profiles."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Mapping
from tkinter import LEFT, X, StringVar, TclError, messagebox
from tkinter import ttk
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from orion.communication_profile_packs import (
    PROFILE_DISPLAY_NAMES,
    ProfileCard,
    RegistryCheckResult,
    UpdateState,
)


PROFILE_ORDER = tuple(profile_id.value for profile_id in PROFILE_DISPLAY_NAMES)
PROFILE_LABELS = tuple(PROFILE_DISPLAY_NAMES.values())
COMMUNICATION_PROFILE_COLUMNS = (
    "Profile",
    "Pack",
    "Source registry",
    "Content / readiness",
    "Coverage",
    "Languages",
    "Update",
)
COMMUNICATION_PROFILE_WIDTHS = (14, 7, 10, 16, 18, 9, 11)


class CommunicationProfileViewState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    configured_profile_id: str | None
    effective_profile_id: str | None
    configured_pack_version: str | None
    effective_pack_version: str | None
    registry_configured: bool
    registry_status: str
    profiles: tuple[ProfileCard, ...]
    check: RegistryCheckResult | None = None


def parse_profile_view_state(payload: Mapping[str, object]) -> CommunicationProfileViewState:
    state = CommunicationProfileViewState.model_validate(payload)
    ids = tuple(card.profile_id.value for card in state.profiles)
    if ids != PROFILE_ORDER:
        raise ValueError("Core returned an incomplete or reordered profile registry")
    selected = [card for card in state.profiles if card.selected]
    if state.configured_profile_id is None:
        if selected:
            raise ValueError("Core profile selection state is inconsistent")
    elif len(selected) != 1 or selected[0].profile_id.value != state.configured_profile_id:
        raise ValueError("Core must expose exactly one configured profile")
    return state


def profile_row_text(card: ProfileCard) -> tuple[str, ...]:
    coverage = ", ".join(f"{item.domain}: {item.status.value}" for item in card.coverage)
    languages = ", ".join(card.operational_languages) or "Not installed"
    verification = card.verification.value if card.verification else "NOT INSTALLED"
    return (
        card.display_name,
        card.active_pack_version or "Not installed",
        card.source_registry_status.value,
        f"{verification} / {card.readiness.value}",
        coverage or "Not declared",
        languages,
        card.update_state.value.replace("_", " "),
    )


def format_profile_details(payload: Mapping[str, object]) -> str:
    profile = str(payload.get("display_name") or payload.get("profile_id") or "Profile")
    source_status = str(payload.get("source_registry_status") or "UNKNOWN")
    limitation = str(payload.get("source_limitation") or "None declared")
    pack = payload.get("pack")
    if isinstance(pack, Mapping):
        verification = str(pack.get("verification") or "UNKNOWN")
        readiness = str(pack.get("readiness") or "UNKNOWN")
        version = str(pack.get("pack_version") or "UNKNOWN")
    else:
        verification = "NOT INSTALLED"
        readiness = "NOT INSTALLED"
        version = "NOT INSTALLED"
    sources = payload.get("sources")
    titles: list[str] = []
    if isinstance(sources, list):
        for item in sources[:8]:
            if isinstance(item, Mapping):
                titles.append(str(item.get("title") or item.get("source_id") or "Source"))
    source_lines = "\n".join(f"• {title}" for title in titles) or "• No source metadata"
    return (
        f"{profile}\n\n"
        f"SOURCE REGISTRY STATUS\n{source_status}\n{limitation}\n\n"
        f"PACK CONTENT VERIFICATION\n{verification}\n\n"
        f"RUNTIME READINESS\n{readiness}\n\n"
        f"ACTIVE PACK VERSION\n{version}\n\n"
        f"SOURCE FAMILIES\n{source_lines}\n\n"
        "Bootstrap packs contain metadata only. No production phraseology is bundled."
    )


class LauncherCommunicationProfilesMixin:
    """Append the approved table/radio profile UI to Settings."""

    root: Any
    core: Any
    content: Any

    def _page_settings(self) -> None:
        super()._page_settings()  # type: ignore[misc]
        self._build_communication_profile_section()

    def _build_communication_profile_section(self) -> None:
        ttk.Separator(self.content, orient="horizontal").pack(fill=X, pady=(24, 18))
        ttk.Label(
            self.content,
            text="COMMUNICATION PROFILE",
            style="Section.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            self.content,
            text=(
                "Choose one aviation communication rules profile. The profile controls future "
                "verified operational wording only; it does not change operational truth, AI "
                "provider, mission state, or the language used for ordinary conversation."
            ),
            style="Muted.TLabel",
            wraplength=820,
            justify="left",
        ).pack(anchor="w", pady=(4, 12))

        card = ttk.Frame(self.content, style="Card.TFrame", padding=14)
        card.pack(fill=X)
        configured = StringVar(value="")
        activity = StringVar(value="Loading communication profiles…")
        row_values: dict[str, tuple[StringVar, ...]] = {}

        header = ttk.Frame(card, style="Card.TFrame")
        header.pack(fill=X, pady=(0, 5))
        widths = COMMUNICATION_PROFILE_WIDTHS
        for index, (title, width) in enumerate(zip(COMMUNICATION_PROFILE_COLUMNS, widths, strict=True)):
            ttk.Label(
                header,
                text=title.upper(),
                style="CardTitle.TLabel",
                width=width,
                wraplength=145,
                justify="left",
            ).grid(
                row=0, column=index, sticky="w", padx=(0, 5)
            )
        header.columnconfigure(4, weight=1)

        rows = ttk.Frame(card, style="Card.TFrame")
        rows.pack(fill=X)
        for row_index, profile_id in enumerate(PROFILE_ORDER):
            values = tuple(StringVar(value="Loading…") for _ in range(6))
            row_values[profile_id] = values
            row = ttk.Frame(rows, style="Card.TFrame")
            row.grid(row=row_index, column=0, sticky="ew", pady=2)
            row.columnconfigure(4, weight=1)
            ttk.Radiobutton(
                row,
                text=PROFILE_LABELS[row_index],
                variable=configured,
                value=profile_id,
                command=lambda selected=profile_id: self._select_communication_profile(
                    selected, activity, apply_state
                ),
                width=18,
            ).grid(row=0, column=0, sticky="w", padx=(0, 5))
            for column, (variable, width) in enumerate(zip(values, widths[1:], strict=True), start=1):
                ttk.Label(
                    row,
                    textvariable=variable,
                    style="CardText.TLabel",
                    width=width,
                    wraplength=230 if column == 4 else 150,
                    justify="left",
                ).grid(row=0, column=column, sticky="w", padx=(0, 5))
        rows.columnconfigure(0, weight=1)

        ttk.Label(
            card,
            textvariable=activity,
            style="CardText.TLabel",
            wraplength=800,
            justify="left",
        ).pack(anchor="w", pady=(10, 8))
        buttons = ttk.Frame(card, style="Card.TFrame")
        buttons.pack(fill=X)

        check_button = ttk.Button(buttons, text="CHECK FOR UPDATES", style="Secondary.TButton")
        update_button = ttk.Button(buttons, text="UPDATE", style="Secondary.TButton")
        details_button = ttk.Button(buttons, text="DETAILS", style="Secondary.TButton")
        rollback_button = ttk.Button(buttons, text="ROLL BACK", style="Secondary.TButton")
        for button in (check_button, update_button, details_button, rollback_button):
            button.pack(side=LEFT, padx=(0, 8))
        ttk.Label(
            card,
            text=(
                "UPDATE acquires into staging, validates compatibility, hashes and trusted "
                "signature, then activates atomically. The current pack remains active on failure."
            ),
            style="CardText.TLabel",
            wraplength=800,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        current_state: CommunicationProfileViewState | None = None

        def apply_state(state: CommunicationProfileViewState) -> None:
            nonlocal current_state
            current_state = state
            configured.set(state.configured_profile_id or "")
            for item in state.profiles:
                rendered = profile_row_text(item)
                values = row_values[item.profile_id.value]
                for variable, text in zip(values, rendered[1:], strict=True):
                    variable.set(text)
            chosen = next((item for item in state.profiles if item.selected), None)
            if chosen is None:
                activity.set(
                    "PROFILE SETUP REQUIRED — select one profile. Existing voice and Golden "
                    "compatibility paths remain unchanged."
                )
            elif chosen.readiness.value == "RESEARCH_ONLY":
                activity.set(
                    f"{chosen.display_name} selected | metadata pack {chosen.active_pack_version} | "
                    "operational content not installed"
                )
            else:
                activity.set(f"{chosen.display_name} selected | {state.registry_status}")
            check_button.configure(
                state="normal" if chosen is not None and state.registry_configured else "disabled"
            )
            update_button.configure(
                state=(
                    "normal"
                    if chosen is not None and chosen.update_state is UpdateState.UPDATE_AVAILABLE
                    else "disabled"
                )
            )
            details_button.configure(state="normal" if chosen is not None else "disabled")
            rollback_button.configure(
                state="normal" if chosen is not None and chosen.rollback_version else "disabled"
            )
            if not state.registry_configured:
                activity.set(f"{activity.get()} | UPDATE SOURCE NOT CONFIGURED")

        def selected_id() -> str | None:
            value = configured.get().strip()
            return value if value in PROFILE_ORDER else None

        check_button.configure(
            command=lambda: self._communication_profile_action(
                selected_id(), "check-updates", activity, apply_state
            )
        )
        update_button.configure(
            command=lambda: self._communication_profile_action(
                selected_id(), "update", activity, apply_state
            )
        )
        def rollback_selected() -> None:
            profile_id = selected_id()
            chosen = (
                next((item for item in current_state.profiles if item.selected), None)
                if current_state is not None
                else None
            )
            if profile_id is None or chosen is None or not chosen.rollback_version:
                return
            if not messagebox.askyesno(
                "ORION Communication Profile",
                (
                    f"Roll back {chosen.display_name} from "
                    f"{chosen.active_pack_version or 'unknown'} to "
                    f"{chosen.rollback_version}?"
                ),
                parent=self.root,
            ):
                return
            self._communication_profile_action(
                profile_id, "rollback", activity, apply_state
            )

        rollback_button.configure(command=rollback_selected)

        def show_details() -> None:
            profile_id = selected_id()
            if profile_id is None:
                return

            def done(payload: Mapping[str, object]) -> None:
                messagebox.showinfo(
                    "ORION Communication Profile",
                    format_profile_details(payload),
                    parent=self.root,
                )

            self._communication_request_async(
                f"/v1/communication-profiles/{profile_id}/details",
                activity,
                done,
            )

        details_button.configure(command=show_details)
        self._communication_request_async(
            "/v1/communication-profiles",
            activity,
            lambda payload: apply_state(parse_profile_view_state(payload)),
        )
        self._communication_profile_controls = {
            "configured": configured,
            "activity": activity,
            "rows": row_values,
            "check": check_button,
            "update": update_button,
            "details": details_button,
            "rollback": rollback_button,
            "state": lambda: current_state,
        }

    def _select_communication_profile(
        self,
        profile_id: str,
        activity: StringVar,
        apply_state: Any,
    ) -> None:
        activity.set(f"Saving {profile_id} selection…")
        self._communication_request_async(
            "/v1/communication-profiles/selection",
            activity,
            lambda payload: apply_state(parse_profile_view_state(payload)),
            method="PUT",
            payload={"profile_id": profile_id},
        )

    def _communication_profile_action(
        self,
        profile_id: str | None,
        action: str,
        activity: StringVar,
        apply_state: Any,
    ) -> None:
        if profile_id is None:
            return
        activity.set(f"{action.replace('-', ' ').title()} in progress…")
        self._communication_request_async(
            f"/v1/communication-profiles/{profile_id}/{action}",
            activity,
            lambda payload: apply_state(parse_profile_view_state(payload)),
            method="POST",
        )

    def _communication_request_async(
        self,
        path: str,
        activity: StringVar,
        on_success: Any,
        *,
        method: str = "GET",
        payload: Mapping[str, object] | None = None,
    ) -> None:
        def worker() -> None:
            try:
                result = self._communication_core_json(path, method=method, payload=payload)
            except (OSError, RuntimeError, ValueError, ValidationError) as exc:
                error_message = f"Communication Profile error: {exc}"
                self._communication_on_ui(
                    lambda message=error_message: activity.set(message)
                )
                return
            self._communication_on_ui(lambda: on_success(result))

        threading.Thread(target=worker, name="orion-profile-ui", daemon=True).start()

    def _communication_on_ui(self, callback: Any) -> None:
        try:
            self.root.after(0, callback)
        except TclError:
            return

    def _communication_core_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.core.base_url.rstrip('/')}{path}",
            data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=4.0) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("detail", {})
                message = detail.get("message") if isinstance(detail, Mapping) else str(detail)
            except (UnicodeDecodeError, json.JSONDecodeError):
                message = f"Core returned HTTP {exc.code}"
            raise RuntimeError(str(message)[:300]) from exc
        if not isinstance(result, dict):
            raise RuntimeError("ORION Core returned an invalid Communication Profile response")
        return result
