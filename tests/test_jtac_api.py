from orion.app import app


def test_jtac_api_routes_are_registered():
    paths = {path for route in app.routes if (path := getattr(route, "path", None)) is not None}
    assert "/v1/jtac/sessions" in paths
    assert "/v1/jtac/sessions/{session_id}" in paths
    assert "/v1/jtac/sessions/{session_id}/mark" in paths
    assert "/v1/jtac/sessions/{session_id}/reconcile" in paths
