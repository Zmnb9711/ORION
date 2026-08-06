from fastapi import FastAPI

from orion.coalition_control_api import router as coalition_control_router
from orion.voice_core_api import router as voice_core_router

app = FastAPI(
    title="ORION",
    version="0.1.0",
    description="ORION AI Flight Assistant API",
)

app.include_router(coalition_control_router)
app.include_router(voice_core_router)


@app.get("/health", tags=["System"])
def health() -> dict[str, str]:
    return {"status": "ok"}
