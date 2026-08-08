from uuid import uuid4

from orion.jtac_runtime import JtacDesignationMethod, JtacSession, JtacSessionState
from orion.jtac_voice import jtac_session_text


def _session(state: JtacSessionState, method: JtacDesignationMethod, laser_code: int | None = None):
    return JtacSession(session_id=uuid4(), target_id="target-1", method=method, state=state, assigned_asset_id="jtac-1", laser_code=laser_code, smoke_color="red", marker_active=state is JtacSessionState.MARKING)


def test_russian_assigned_laser_response_reports_code():
    text = jtac_session_text(_session(JtacSessionState.ASSIGNED, JtacDesignationMethod.LASER, 1688), "ru")
    assert "1688" in text
    assert "код" in text.casefold()


def test_russian_marking_laser_response_reports_code():
    text = jtac_session_text(_session(JtacSessionState.MARKING, JtacDesignationMethod.LASER, 1688), "ru")
    assert text == "Лазер включён. Код 1688."


def test_english_marking_laser_response_reports_code():
    text = jtac_session_text(_session(JtacSessionState.MARKING, JtacDesignationMethod.LASER, 1688), "en")
    assert text == "Laser on. Code 1688."


def test_smoke_response_does_not_report_laser_code():
    text = jtac_session_text(_session(JtacSessionState.MARKING, JtacDesignationMethod.SMOKE), "ru")
    assert "код" not in text.casefold()
