# ORION

ORION is an AI-assisted mission control and virtual ATC platform for DCS World.

## Build 001 capabilities

- Local DCS telemetry ingestion over UDP
- FastAPI health, telemetry and command endpoints
- Mission snapshots and coalition-aware unit queries
- Threat assessment with distance, bearing, priority and movement prediction
- Structured AWACS, tanker, laser and smoke support requests
- Russian and English free-form dialogue intent routing
- Grounded dialogue runtime backed by live DCS and mission context
- Dialogue-driven AAR orchestration with guarded rendezvous and pre-contact transitions
- Sparse proactive AAR monitoring for closure, vertical state, tanker loss and pre-contact readiness
- Proactive AAR callouts published into the shared Voice Core priority queue
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

The dialogue prototype is available through `POST /v1/dialogue`. The grounded runtime is available through `POST /v1/dialogue-runtime`. AAR proactive monitoring is available through `GET /v1/aar/proactive`, while `POST /v1/aar/proactive/voice` publishes only significant callouts into Voice Core.

Laser and smoke intents remain confirmation-required and are not executed directly by the dialogue runtime.

Development work is proposed through pull requests before it reaches `main`.
