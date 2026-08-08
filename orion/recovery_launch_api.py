from uuid import UUID

from fastapi import APIRouter

from orion.recovery_launch import RecoveryLaunchStatus, recovery_launch_status, start_dcs_for_recovery


router = APIRouter(prefix="/v1/recovery-launch", tags=["Startup Recovery"])


@router.post("/start", response_model=RecoveryLaunchStatus)
def start() -> RecoveryLaunchStatus:
    return start_dcs_for_recovery()


@router.get("/status", response_model=RecoveryLaunchStatus)
def status(launch_id: UUID | None = None) -> RecoveryLaunchStatus:
    return recovery_launch_status(launch_id)
