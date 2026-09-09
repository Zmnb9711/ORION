"""The baseline exception must not permit current frozen-boundary changes."""
import pytest

from level0_scope_guard import ADDED_AT_BASELINE, CURRENT_SCOPE, assert_deltas


def test_baseline_additions_are_not_current_permissions():
    assert_deltas(ADDED_AT_BASELINE | {"orion/hybrid_aircraft_core.py"}, CURRENT_SCOPE, set(),
                  {"orion/hybrid_aircraft_core.py"})
    for frozen in ADDED_AT_BASELINE - CURRENT_SCOPE | {"orion/launcher.py", "orion/interaction_router.py", "orion/yandex_srs_live_core.py"}:
        with pytest.raises(AssertionError, match="Unauthorized current"):
            assert_deltas(ADDED_AT_BASELINE, {frozen}, set(), set())


def test_unauthorized_historical_and_untracked_paths_still_fail():
    with pytest.raises(AssertionError):
        assert_deltas(ADDED_AT_BASELINE | {"orion/unknown.py"}, set(), set(), set())
    with pytest.raises(AssertionError, match="Untracked production"):
        assert_deltas(ADDED_AT_BASELINE, set(), {"orion/new_owner.py"}, set())
