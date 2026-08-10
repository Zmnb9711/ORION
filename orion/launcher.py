from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

import uvicorn

from orion import __version__
from orion.alpha_smoke_diagnostics import write_alpha_diagnostics_bundle


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def _configure_runtime() -> None:
    root = _runtime_root()
    runtime = root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("ORION_RUNTIME_DIR", str(runtime))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ORION DCS Alpha launcher")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Run one-shot Alpha smoke diagnostics, write a ZIP bundle, and exit",
    )
    args = parser.parse_args(argv)

    _configure_runtime()
    if args.diagnostics:
        bundle = write_alpha_diagnostics_bundle()
        print(f"ORION Alpha {__version__} diagnostics")
        print(f"Bundle: {bundle}")
        return 0

    url = f"http://{args.host}:{args.port}"
    print(f"ORION Alpha {__version__}")
    print(f"Core API: {url}")
    print("Keep this window open while using ORION with DCS.")

    if not args.no_browser:
        try:
            webbrowser.open(f"{url}/docs")
        except webbrowser.Error:
            pass

    uvicorn.run("orion.app:app", host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
