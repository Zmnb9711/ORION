from fastapi import APIRouter

from orion.dialogue import DialogueRequest
from orion.dialogue_runtime import DialogueRuntimeResult, run_dialogue


router = APIRouter(prefix="/v1/dialogue-runtime", tags=["Dialogue runtime"])


@router.post("", response_model=DialogueRuntimeResult)
def process_grounded_dialogue(payload: DialogueRequest) -> DialogueRuntimeResult:
    return run_dialogue(payload)
