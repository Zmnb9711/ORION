from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from orion import __version__
from orion.commands import CommandDispatcher, DcsCommand
from orion.config import settings
from orion.events import EventJournal
from orion.mission import Coalition, MissionSnapshot, MissionUnit
from orion.mission_store import mission_store
from orion.models import TelemetryEnvelope
from orion.support import SupportRequest, SupportRequestCreate, support_requests
from orion.udp_bridge import start_udp_bridge

_latest: TelemetryEnvelope | None = None
_journal = EventJournal(settings.event_log_path)
_dispatcher = CommandDispatcher()


def store_telemetry(payload: TelemetryEnvelope) -> None:
    global _latest
    _latest = payload
    _journal.append("telemetry", payload.model_dump(mode="json"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    transport, _ = await start_udp_bridge(store_telemetry)
    try:
        yield
    finally:
        transport.close()


app = FastAPI(title="ORION Core", version=__version__, lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post("/v1/telemetry", status_code=202)
def ingest_telemetry(payload: TelemetryEnvelope) -> dict[str, str]:
    store_telemetry(payload)
    return {
        "status": "accepted",
        "aircraft_type": payload.state.aircraft_type,
    }


@app.get("/v1/telemetry/latest", response_model=TelemetryEnvelope)
def latest_telemetry() -> TelemetryEnvelope:
    if _latest is None:
        raise HTTPException(status_code=404, detail="No telemetry received")
    return _latest


@app.post("/v1/commands", status_code=202)
def send_command(command: DcsCommand) -> dict[str, str]:
    _dispatcher.send(command)
    _journal.append("command", command.model_dump(mode="json", exclude_none=True))
    return {"status": "sent", "command": command.command.value}


@app.put("/v1/mission", response_model=MissionSnapshot)
def replace_mission(snapshot: MissionSnapshot) -> MissionSnapshot:
    mission_store.replace(snapshot)
    _journal.append("mission_snapshot", snapshot.model_dump(mode="json"))
    return snapshot


@app.get("/v1/mission", response_model=MissionSnapshot)
def get_mission() -> MissionSnapshot:
    snapshot = mission_store.get()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No mission snapshot received")
    return snapshot


@app.get("/v1/mission/units", response_model=list[MissionUnit])
def list_mission_units(
    coalition: Coalition | None = Query(default=None),
    alive_only: bool = Query(default=True),
) -> list[MissionUnit]:
    return mission_store.units(coalition=coalition, alive_only=alive_only)


@app.post("/v1/support-requests", response_model=SupportRequest, status_code=201)
def create_support_request(payload: SupportRequestCreate) -> SupportRequest:
    request = support_requests.create(payload)
    _journal.append("support_request", request.model_dump(mode="json"))
    return request


@app.get("/v1/support-requests", response_model=list[SupportRequest])
def list_support_requests() -> list[SupportRequest]:
    return support_requests.list()
