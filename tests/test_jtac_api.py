from orion.app import app


def test_jtac_api_routes_are_registered():
    paths = {route.path for route in app.routes}
    assert "/v1/jtac/sessions" in paths
    assert "/v1/jtac/sessions/{session_id}" in paths
    assert "/v1/jtac/sessions/{session_id}/mark" in paths
    assert "/v1/jtac/sessions/{session_id}/reconcile" in paths
