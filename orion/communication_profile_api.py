"""Launcher-to-Core API for communication profile selection and pack lifecycle."""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from orion.communication_contracts import CommunicationProfileId
from orion.communication_profile_packs import (
    CommunicationProfileService,
    CommunicationProfileStore,
    NoRegistryProvider,
    PackError,
    default_profile_data_root,
)


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileSelectionRequest(_Request):
    profile_id: CommunicationProfileId


router = APIRouter(
    prefix="/v1/communication-profiles",
    tags=["Communication Profiles"],
)
_lock = threading.RLock()
_service: CommunicationProfileService | None = None
_service_root: Path | None = None


def communication_profile_service() -> CommunicationProfileService:
    global _service, _service_root
    root = default_profile_data_root()
    with _lock:
        if _service is None or _service_root != root:
            _service = CommunicationProfileService(CommunicationProfileStore(root))
            _service_root = root
        return _service


def _cards() -> dict[str, object]:
    service = communication_profile_service()
    cards = service.cards()
    selected = service.get_selected_profile()
    effective = next(
        (item.effective_profile_id for item in cards if item.effective_profile_id is not None),
        None,
    )
    configured_card = next((item for item in cards if item.selected), None)
    return {
        "configured_profile_id": selected.value if selected else None,
        "effective_profile_id": effective.value if effective else None,
        "configured_pack_version": (
            configured_card.active_pack_version if configured_card is not None else None
        ),
        "effective_pack_version": (
            configured_card.active_pack_version
            if configured_card is not None and effective is not None
            else None
        ),
        "registry_configured": not isinstance(service.registry_provider, NoRegistryProvider),
        "registry_status": (
            "UPDATE SOURCE NOT CONFIGURED"
            if isinstance(service.registry_provider, NoRegistryProvider)
            else "UPDATE SOURCE CONFIGURED"
        ),
        "profiles": [item.model_dump(mode="json") for item in cards],
    }


def _http_error(exc: PackError) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)})


@router.get("")
def get_profiles() -> dict[str, object]:
    return _cards()


@router.put("/selection")
def select_profile(payload: ProfileSelectionRequest) -> dict[str, object]:
    communication_profile_service().select_profile(payload.profile_id)
    return _cards()


@router.get("/{profile_id}/details")
def profile_details(profile_id: CommunicationProfileId) -> dict[str, object]:
    return communication_profile_service().details(profile_id)


@router.post("/{profile_id}/check-updates")
def check_updates(profile_id: CommunicationProfileId) -> dict[str, object]:
    result = communication_profile_service().check_for_updates(profile_id)
    response = _cards()
    response["check"] = result.model_dump(mode="json")
    return response


@router.post("/{profile_id}/update")
def update_profile(profile_id: CommunicationProfileId) -> dict[str, object]:
    try:
        communication_profile_service().update(profile_id)
    except PackError as exc:
        raise _http_error(exc) from exc
    return _cards()


@router.post("/{profile_id}/rollback")
def rollback_profile(profile_id: CommunicationProfileId) -> dict[str, object]:
    try:
        communication_profile_service().rollback(profile_id)
    except PackError as exc:
        raise _http_error(exc) from exc
    return _cards()
