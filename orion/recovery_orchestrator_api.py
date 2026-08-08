from fastapi import APIRouter

from orion.recovery_orchestrator import RecoveryResult, run_recovery
from orion.startup_health import RecoveryAction


router = APIRouter(prefix="/v1/recovery", tags=["Startup Recovery"])


@router.post("/{action}", response_model=RecoveryResult)
def recover(action: RecoveryAction) -> RecoveryResult:
    return run_recovery(action)
