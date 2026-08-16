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


def test_voice_worker_does_not_provision_whisper_implicitly() -> None:
    source = inspect.getsource(voice_runtime_worker)
    assert "ensure_runtime" not in source
    assert "DOWNLOAD & INSTALL STT" in source
    assert "runtime_ready" in source
