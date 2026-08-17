from __future__ import annotations

import inspect

from orion.desktop_launcher_field_fixed import FieldFixedConversationalAudioLauncher
from orion.launcher_stt_install import LauncherSttInstallMixin
from orion import voice_runtime_worker


def test_canonical_launcher_composes_explicit_stt_installer() -> None:
    assert LauncherSttInstallMixin in FieldFixedConversationalAudioLauncher.__mro__


def test_stt_ui_keeps_explicit_install_action_and_locked_baseline() -> None:
    source = inspect.getsource(LauncherSttInstallMixin)
    assert "DOWNLOAD & INSTALL STT" in source
    assert "NOT INSTALLED" in source
    assert "DOWNLOADING / INSTALLING" in source
    assert "READY" in source
    assert "ERROR" in source
    assert "never downloaded silently" in source


def test_stt_ui_hides_download_progress_after_ready() -> None:
    source = inspect.getsource(LauncherSttInstallMixin._install_stt_async)
    assert 'detail_var.set("")' in source
    assert "detail_label.pack_forget()" in source
    assert "progress.pack_forget()" in source
    assert "progress.configure(value=100)" not in source
    assert "Whisper STT installation verified" not in source


def test_voice_worker_does_not_provision_whisper_implicitly() -> None:
    source = inspect.getsource(voice_runtime_worker)
    assert "ensure_runtime" not in source
    assert "DOWNLOAD & INSTALL STT" in source
    assert "runtime_ready" in source
