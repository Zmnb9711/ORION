from __future__ import annotations

import os
import threading
from collections.abc import Callable

from orion.branding import packaged_icon_path


class TrayUnavailable(RuntimeError):
    pass


class WindowsTrayController:
    def __init__(self, on_open: Callable[[], None], on_exit: Callable[[], None]) -> None:
        self.on_open = on_open
        self.on_exit = on_exit
        self._icon = None
        self._thread: threading.Thread | None = None

    @property
    def supported(self) -> bool:
        return os.name == "nt"

    def start(self) -> None:
        if not self.supported:
            raise TrayUnavailable("System tray is only available on Windows")
        if self._thread is not None and self._thread.is_alive():
            return
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError as exc:
            raise TrayUnavailable("Windows tray backend is not installed") from exc

        icon_path = packaged_icon_path()
        if icon_path is not None:
            image = Image.open(icon_path).convert("RGBA")
        else:
            image = Image.new("RGBA", (64, 64), (11, 18, 32, 255))
            draw = ImageDraw.Draw(image)
            draw.ellipse((10, 10, 54, 54), outline=(40, 120, 255, 255), width=6)
            draw.line((22, 42, 42, 22), fill=(238, 245, 255, 255), width=6)

        def open_action(icon, item) -> None:  # noqa: ANN001
            self.on_open()

        def exit_action(icon, item) -> None:  # noqa: ANN001
            self.on_exit()

        self._icon = pystray.Icon(
            "ORION",
            image,
            "ORION",
            pystray.Menu(
                pystray.MenuItem("Open ORION", open_action, default=True),
                pystray.MenuItem("Exit", exit_action),
            ),
        )
        self._thread = threading.Thread(target=self._icon.run, name="orion-tray", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        icon = self._icon
        self._icon = None
        if icon is not None:
            icon.stop()
