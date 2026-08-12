from __future__ import annotations

import argparse
import os
import sys
import traceback
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

import uvicorn

from orion import __version__
from orion.alpha_smoke_diagnostics import write_alpha_diagnostics_bundle

_NULL_STREAMS: list[TextIO] = []


def _ensure_stdio() -> None:
    """Provide sink streams when a PyInstaller windowed executable has none."""

    for name in ("stdout", "stderr"):
        if getattr(sys, name) is not None:
            continue
        stream = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
        _NULL_STREAMS.append(stream)
        setattr(sys, name, stream)


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def _configure_runtime() -> Path:
    root = _runtime_root()
    runtime = root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("ORION_RUNTIME_DIR", str(runtime))
    return runtime


def _startup_log_path(runtime: Path) -> Path:
    return runtime / "core-startup.log"


def _startup_stage(runtime: Path, stage: str, detail: str | None = None) -> None:
    """Persist launcher progress even when the frozen windowed build has no console."""

    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    line = f"{timestamp} stage={stage}"
    if detail:
        line += f" detail={detail}"
    with _startup_log_path(runtime).open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
        stream.flush()


def _startup_failure(runtime: Path, stage: str) -> None:
    try:
        _startup_stage(runtime, "fatal", f"during={stage}")
        with _startup_log_path(runtime).open("a", encoding="utf-8") as stream:
            traceback.print_exc(file=stream)
            stream.flush()
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    _ensure_stdio()
    runtime = _configure_runtime()
    _startup_stage(runtime, "boot", f"frozen={getattr(sys, 'frozen', False)} executable={sys.executable}")

    stage = "parse_args"
    try:
        parser = argparse.ArgumentParser(description="ORION DCS Alpha launcher")
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=8000)
        parser.add_argument("--no-browser", action="store_true")
        parser.add_argument(
            "--desktop",
            action="store_true",
            help="Launch the native ORION desktop shell",
        )
        parser.add_argument(
            "--diagnostics",
            action="store_true",
            help="Run one-shot Alpha smoke diagnostics, write a ZIP bundle, and exit",
        )
        args = parser.parse_args(argv)
        _startup_stage(runtime, "args_ready", f"desktop={args.desktop} diagnostics={args.diagnostics} host={args.host} port={args.port}")

        if args.diagnostics:
            stage = "diagnostics"
            _startup_stage(runtime, "diagnostics_start")
            bundle = write_alpha_diagnostics_bundle()
            _startup_stage(runtime, "diagnostics_ready", str(bundle))
            print(f"ORION Alpha {__version__} diagnostics")
            print(f"Bundle: {bundle}")
            return 0

        if args.desktop:
            stage = "desktop_import"
            _startup_stage(runtime, "desktop_import_start")
            from orion.desktop_launcher import run_desktop_launcher

            _startup_stage(runtime, "desktop_import_ready")
            stage = "desktop_run"
            return run_desktop_launcher(runtime, host=args.host, port=args.port)

        url = f"http://{args.host}:{args.port}"
        print(f"ORION Alpha {__version__}")
        print(f"Core API: {url}")
        print("Keep this window open while using ORION with DCS.")

        if not args.no_browser:
            try:
                webbrowser.open(f"{url}/docs")
            except webbrowser.Error:
                pass

        # Import the application explicitly. Apart from avoiding a second string-based
        # import inside a frozen bundle, the stage log now distinguishes application
        # import failures/hangs from Uvicorn server startup failures.
        stage = "app_import"
        _startup_stage(runtime, "app_import_start")
        from orion.app import app

        _startup_stage(runtime, "app_import_ready")
        stage = "uvicorn_run"
        _startup_stage(runtime, "uvicorn_start", f"url={url}")
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
        _startup_stage(runtime, "uvicorn_stopped")
        return 0
    except BaseException:
        _startup_failure(runtime, stage)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
