from fastapi import APIRouter

from orion.coalition_radio import (
    CallsignLookupQuery,
    CallsignLookupResult,
    CoalitionRadioUnit,
    MissionLandmark,
    NearbyCallsignQuery,
    NearbyCallsignResult,
    RadioLookupQuery,
    RadioLookupResult,
    coalition_radio,
)
from orion.dcs_command_translation import (
    SemanticCommandPlan,
    SemanticCommandRequest,
    build_command_plan,
)
from orion.mission_bridge_state import (
    MissionBridgeApplyResult,
    MissionBridgeSnapshot,
    MissionBridgeStatus,
    mission_bridge_state,
)

router = APIRouter(prefix="/v1/coalition-control", tags=["Coalition Control"])


@router.post("/translate", response_model=SemanticCommandPlan)
def translate_coalition_command(payload: SemanticCommandRequest) -> SemanticCommandPlan:
    return build_command_plan(payload)


@router.get("/radio-units", response_model=list[CoalitionRadioUnit])
def list_radio_units() -> list[CoalitionRadioUnit]:
    return coalition_radio.list()


@router.put("/radio-units", response_model=list[CoalitionRadioUnit])
def replace_radio_units(payload: list[CoalitionRadioUnit]) -> list[CoalitionRadioUnit]:
    return coalition_radio.replace(payload)


@router.post("/radio-units/upsert", response_model=CoalitionRadioUnit)
def upsert_radio_unit(payload: CoalitionRadioUnit) -> CoalitionRadioUnit:
    return coalition_radio.upsert(payload)


@router.post("/radio-units/lookup", response_model=RadioLookupResult)
def lookup_radio_unit(payload: RadioLookupQuery) -> RadioLookupResult:
    return coalition_radio.lookup(payload)


@router.post("/callsigns/lookup", response_model=CallsignLookupResult)
def lookup_callsigns(payload: CallsignLookupQuery) -> CallsignLookupResult:
    return coalition_radio.lookup_callsigns(payload)


@router.get("/landmarks", response_model=list[MissionLandmark])
def list_landmarks() -> list[MissionLandmark]:
    return coalition_radio.list_landmarks()


@router.put("/landmarks", response_model=list[MissionLandmark])
def replace_landmarks(payload: list[MissionLandmark]) -> list[MissionLandmark]:
    return coalition_radio.replace_landmarks(payload)


@router.post("/landmarks/upsert", response_model=MissionLandmark)
def upsert_landmark(payload: MissionLandmark) -> MissionLandmark:
    return coalition_radio.upsert_landmark(payload)


@router.post("/callsigns/near-landmark", response_model=NearbyCallsignResult)
def lookup_callsigns_near_landmark(payload: NearbyCallsignQuery) -> NearbyCallsignResult:
    return coalition_radio.lookup_near_landmark(payload)


@router.post("/mission-bridge/snapshot", response_model=MissionBridgeApplyResult)
def apply_mission_bridge_snapshot(payload: MissionBridgeSnapshot) -> MissionBridgeApplyResult:
    return mission_bridge_state.apply(payload)


@router.get("/mission-bridge/status", response_model=MissionBridgeStatus)
def get_mission_bridge_status() -> MissionBridgeStatus:
    return mission_bridge_state.status()


@router.post("/mission-bridge/disconnect", response_model=MissionBridgeStatus)
def disconnect_mission_bridge() -> MissionBridgeStatus:
    return mission_bridge_state.disconnect()


@router.delete("/mission-bridge/state", response_model=MissionBridgeStatus)
def reset_mission_bridge_state() -> MissionBridgeStatus:
    return mission_bridge_state.reset()
