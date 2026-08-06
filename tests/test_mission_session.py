from uuid import uuid4

from orion.mission_session import MissionSession, MissionSessionManager


def test_mission_session_lifecycle() -> None:
    manager = MissionSessionManager()
    session = manager.start(MissionSession(mission_id="caucasus-demo"))

    assert manager.get() == session
    assert session.active is True

    heartbeat = manager.heartbeat(session.session_id)
    assert heartbeat is not None
    assert heartbeat.session_id == session.session_id

    ended = manager.end(session.session_id)
    assert ended is not None
    assert ended.active is False


def test_unknown_session_is_rejected() -> None:
    manager = MissionSessionManager()
    manager.start(MissionSession(mission_id="mission-a"))

    assert manager.heartbeat(uuid4()) is None
    assert manager.end(uuid4()) is None


def test_starting_new_session_deactivates_previous() -> None:
    manager = MissionSessionManager()
    first = manager.start(MissionSession(mission_id="mission-a"))
    second = manager.start(MissionSession(mission_id="mission-b"))

    assert first.active is False
    assert second.active is True
    assert manager.get() == second
