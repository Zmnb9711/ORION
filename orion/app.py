from fastapi import FastAPI, HTTPException

from orion import __version__
from orion.models import TelemetryEnvelope

app = FastAPI(title="ORION Core", version=__version__)
_latest: TelemetryEnvelope | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post("/v1/telemetry", status_code=202)
def ingest_telemetry(payload: TelemetryEnvelope) -> dict[str, str]:
    global _latest
    _latest = payload
    return {
        "status": "accepted",
        "aircraft_type": payload.state.aircraft_type,
    }


@app.get("/v1/telemetry/latest", response_model=TelemetryEnvelope)
def latest_telemetry() -> TelemetryEnvelope:
    if _latest is None:
        raise HTTPException(status_code=404, detail="No telemetry received")
    return _latest
