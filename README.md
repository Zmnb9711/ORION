# ORION

ORION is an AI-assisted mission control and virtual ATC platform for DCS World.

## Build 001 capabilities

- Local DCS telemetry ingestion over UDP
- FastAPI health, telemetry and command endpoints
- Mission snapshots and coalition-aware unit queries
- Threat assessment with distance, bearing, priority and movement prediction
- Structured AWACS, tanker, laser and smoke support requests
- Russian and English free-form dialogue intent routing
- Append-only mission event journal
- Safe command allowlist for the DCS export environment
- CI on Python 3.11 and 3.12

## Local development

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
pytest -q
uvicorn orion.app:app --reload
```

The service listens on `http://127.0.0.1:8000` by default. Interactive API documentation is available at `/docs`.

The dialogue prototype is available through `POST /v1/dialogue`. It classifies Russian and English free-form requests but does not directly execute dangerous actions. Laser and smoke intents are marked as requiring confirmation.

Development work is proposed through pull requests before it reaches `main`.
