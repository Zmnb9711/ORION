from fastapi import APIRouter

from orion.dcs_capabilities import (
    CapabilityDecision,
    CapabilityQuery,
    DcsCapability,
    dcs_capabilities,
)

router = APIRouter(prefix="/v1/dcs-capabilities", tags=["DCS Capabilities"])


@router.get("", response_model=list[DcsCapability])
def list_dcs_capabilities() -> list[DcsCapability]:
    return dcs_capabilities.list()


@router.post("/decide", response_model=CapabilityDecision)
def decide_dcs_capability(payload: CapabilityQuery) -> CapabilityDecision:
    return dcs_capabilities.decide(payload)
