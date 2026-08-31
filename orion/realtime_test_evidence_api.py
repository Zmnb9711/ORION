"""Core API for explicit privacy-bounded realtime test evidence sessions."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from orion.build_identity import load_build_identity
from orion.realtime_test_evidence import realtime_test_evidence


router = APIRouter(prefix="/v1/realtime/test-evidence", tags=["Realtime Test Evidence"])

_RADIO_STT_EVIDENCE_VALUES = {
    "yandex_realtime": "yandex_realtime_legacy",
    "speechkit_v3": "speechkit_v3_external_eou",
}


class RealtimeTestEvidenceStart(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    transport: str = Field(min_length=1, max_length=40)
    capture_speechkit_stt_input_audio: bool = False


@router.post("/start")
def start_test_evidence(request: RealtimeTestEvidenceStart) -> dict[str, object]:
    try:
        identity = load_build_identity()
        radio_stt_provider: str | None = None
        tts_output_mode: str | None = None
        if request.provider == "yandex" and request.transport == "srs":
            from orion.yandex_srs_live_core import yandex_srs_live

            status = yandex_srs_live.status()
            selected = status.radio_stt_provider.value
            radio_stt_provider = _RADIO_STT_EVIDENCE_VALUES[selected]
            selected_tts = getattr(status, "tts_output_mode", None)
            tts_output_mode = (
                selected_tts.value if selected_tts is not None else "speechkit_rest"
            )
        return asdict(
            realtime_test_evidence.start(
                provider=request.provider,
                transport=request.transport,
                radio_stt_provider=radio_stt_provider,
                tts_output_mode=tts_output_mode,
                capture_speechkit_stt_input_audio=(
                    request.capture_speechkit_stt_input_audio
                ),
                build_sha=identity.sha,
                build_branch=identity.branch,
                build_version=identity.version,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/status")
def test_evidence_status() -> dict[str, object]:
    return asdict(realtime_test_evidence.status())


@router.post("/stop-export")
def stop_and_export_test_evidence() -> dict[str, object]:
    try:
        output = realtime_test_evidence.stop_and_export()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"active": False, "export_path": str(output)}
