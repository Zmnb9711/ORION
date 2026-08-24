from __future__ import annotations

from pathlib import Path
from tkinter import Tk

from orion.core_process import CoreProcessManager
from orion.desktop_launcher import _install_tk_exception_boundary
from orion.desktop_launcher_audio import AudioAwareRuntimeLauncher
from orion.launcher_cloud_voice_sections import LauncherCloudVoiceSectionsMixin
from orion.launcher_dropdown_readability import LauncherDropdownReadabilityMixin
from orion.launcher_field_ui_fix import LauncherFieldUiFixMixin


class FieldFixedAudioLauncher(
    LauncherCloudVoiceSectionsMixin,
    LauncherDropdownReadabilityMixin,
    LauncherFieldUiFixMixin,
    AudioAwareRuntimeLauncher,
):
    """Canonical Launcher with field-tested UI stability/readability fixes."""

    def exit_application(self) -> None:
        """Fully exit ORION in the required child-before-parent order.

        Closing the window is handled by ``WindowsOrionDesktopLauncher.close``
        and only withdraws it to the tray.  This method is reserved for the
        explicit tray Exit action and therefore owns the full runtime shutdown:
        An active realtime provider is stopped through Core first, followed by Core
        and Launcher teardown.  If Core is unavailable, shutdown continues.
        """
        if getattr(self, "_really_exiting", False):
            return
        self._really_exiting = True
        self._tray.stop()
        self._stop_realtime_before_exit()
        self.core.shutdown()
        self.root.destroy()


def run_field_fixed_launcher(runtime_dir: Path, host: str = "127.0.0.1", port: int = 8000) -> int:
    core = CoreProcessManager(host, port, runtime_dir)
    core.start()
    try:
        root = Tk()
        _install_tk_exception_boundary(root, runtime_dir)
        FieldFixedAudioLauncher(root, runtime_dir=runtime_dir, core=core)  # type: ignore[arg-type]
        root.mainloop()
    finally:
        core.shutdown()
    return 0
