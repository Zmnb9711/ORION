# ORION

ORION is an AI-assisted mission control and virtual ATC platform for DCS World.

## Build 001

The first development build provides:

- a FastAPI-based ORION Core service;
- validated aircraft telemetry models;
- a localhost UDP telemetry bridge;
- a prototype DCS `Export.lua` sender;
- health and latest-aircraft-state API endpoints;
- basic automated tests;
- initial architecture documentation.

## Local development

Requirements: Python 3.11 or newer.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pytest
uvicorn orion.app:app --host 127.0.0.1 --port 8000
```

Health check:

```text
GET http://127.0.0.1:8000/health
```

Latest telemetry:

```text
GET http://127.0.0.1:8000/v1/telemetry/latest
```

## DCS integration

The prototype exporter is located at `dcs-export/Export.lua`. It sends versioned JSON telemetry to `127.0.0.1:45100`.

Do not overwrite an existing DCS export configuration blindly. The final installer will merge ORION into the user's existing `Saved Games/DCS/Scripts/Export.lua` safely.

See [docs/architecture.md](docs/architecture.md) for the current architecture and roadmap.
