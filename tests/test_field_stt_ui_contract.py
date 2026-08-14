from __future__ import annotations

import inspect

from orion.desktop_launcher_field_fixed import FieldFixedConversationalAudioLauncher
from orion.launcher_field_ui_fix import LauncherFieldUiFixMixin


def test_field_launcher_owns_test_page_with_explicit_stt_controls() -> None:
    assert FieldFixedConversationalAudioLauncher._page_test is LauncherFieldUiFixMixin._page_test
    source = inspect.getsource(LauncherFieldUiFixMixin._page_test)
    assert "LOCAL SPEECH RECOGNITION" in source
    assert "DOWNLOAD & INSTALL STT" in source
    assert "_stt_prepare_button" in source
    assert "_stt_progress" in source
    assert "_poll_stt_status" in source


def test_field_launcher_keeps_conversation_disabled_until_stt_status_is_polled() -> None:
    source = inspect.getsource(LauncherFieldUiFixMixin._page_test)
    assert 'enabled=False' in source
    assert "self.root.after(50, self._poll_stt_status)" in source
