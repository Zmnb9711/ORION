import asyncio

from orion.app import app
from orion.recovery_presentation import RecoveryPresentation, RecoveryUiState
from orion.startup_health import StartupHealthReport, StartupHealthState
import orion.recovery_stream_api as stream_api


class _ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


def _presentation(state: RecoveryUiState) -> RecoveryPresentation:
    return RecoveryPresentation(
        state=state,
        title="Ready",
        message="Connected",
        health=StartupHealthReport(state=StartupHealthState.HEALTHY),
    )


def test_recovery_stream_route_is_registered():
    assert "/v1/recovery-ui/stream" in app.openapi()["paths"]


def test_recovery_stream_emits_state_event_and_stops_on_ready(monkeypatch):
    monkeypatch.setattr(stream_api, "get_recovery_presentation", lambda **_: _presentation(RecoveryUiState.READY))

    async def collect_one():
        iterator = stream_api._recovery_stream(
            _ConnectedRequest(),
            launch_id=None,
            language="en",
            heartbeat_seconds=1.0,
            poll_seconds=0.1,
        )
        first = await anext(iterator)
        try:
            await anext(iterator)
        except StopAsyncIteration:
            stopped = True
        else:
            stopped = False
        return first, stopped

    event, stopped = asyncio.run(collect_one())
    assert "event: recovery_state" in event
    assert '"state":"ready"' in event
    assert stopped is True


def test_recovery_stream_stops_on_failed(monkeypatch):
    monkeypatch.setattr(stream_api, "get_recovery_presentation", lambda **_: _presentation(RecoveryUiState.FAILED))

    async def collect():
        iterator = stream_api._recovery_stream(
            _ConnectedRequest(),
            launch_id=None,
            language="ru",
            heartbeat_seconds=1.0,
            poll_seconds=0.1,
        )
        first = await anext(iterator)
        try:
            await anext(iterator)
        except StopAsyncIteration:
            return first, True
        return first, False

    event, stopped = asyncio.run(collect())
    assert '"state":"failed"' in event
    assert stopped is True
