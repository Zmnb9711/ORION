from __future__ import annotations

from orion.launcher_field_ui_fix import LauncherFieldUiFixMixin


class _FakeLauncher:
    def __init__(self) -> None:
        self.health = None
        self.rendered = 0
        self.show_calls = 0

    def _render_status_strip(self) -> None:
        self.rendered += 1

    def show_page(self, _page: str) -> None:
        self.show_calls += 1


def test_background_health_update_does_not_rebuild_page() -> None:
    fake = _FakeLauncher()
    report = object()
    LauncherFieldUiFixMixin._apply_health(fake, report)
    assert fake.health is report
    assert fake.rendered == 1
    assert fake.show_calls == 0
