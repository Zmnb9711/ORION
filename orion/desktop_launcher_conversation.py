from __future__ import annotations

from pathlib import Path
from tkinter import Tk
from typing import Any

from orion.core_process import CoreProcessManager
from orion.desktop_launcher import _install_tk_exception_boundary
from orion.desktop_launcher_audio import AudioAwareRuntimeLauncher
from orion.launcher_audio_sections import LauncherAudioSectionsMixin
from orion.launcher_conversation_test import LauncherConversationTestMixin


class ConversationalAudioRuntimeLauncher(LauncherConversationTestMixin, AudioAwareRuntimeLauncher):
    """Canonical Launcher plus the approved conversational Audio Test."""

    def _core_json(
        self,
        *args: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Bridge the two legacy Core JSON calling conventions in the Launcher MRO.

        LauncherAudioSectionsMixin calls ``_core_json(path, method=..., payload=...)``
        while LauncherConversationTestMixin calls ``_core_json(method, path,
        timeout=...)``.  The conversational mixin is first in the MRO, so without
        this adapter the base Test page resolves the wrong signature while it is
        building its audio snapshot.
        """
        if len(args) == 1:
            path = args[0]
            return LauncherAudioSectionsMixin._core_json(self, path, method=method, payload=payload)
        if len(args) == 2:
            request_method, path = args
            if payload is not None:
                raise TypeError("conversation Core JSON calls do not accept payload")
            return LauncherConversationTestMixin._core_json(
                self,
                request_method,
                path,
                timeout=5.0 if timeout is None else timeout,
            )
        raise TypeError("_core_json expects path or method, path")


def run_conversational_audio_launcher(runtime_dir: Path, host: str = "127.0.0.1", port: int = 8000) -> int:
    core = CoreProcessManager(host, port, runtime_dir)
    core.start()
    try:
        root = Tk()
        _install_tk_exception_boundary(root, runtime_dir)
        ConversationalAudioRuntimeLauncher(root, runtime_dir=runtime_dir, core=core)  # type: ignore[arg-type]
        root.mainloop()
    finally:
        core.stop()
    return 0
