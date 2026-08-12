from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _runtime_root() -> Path:
    configured = os.environ.get("ORION_RUNTIME_DIR")
    if configured:
        runtime = Path(configured).expanduser().resolve()
    elif getattr(sys, "frozen", False):
        runtime = Path(sys.executable).resolve().parent / "runtime"
    else:
        runtime = Path.cwd() / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    os.environ["ORION_RUNTIME_DIR"] = str(runtime)
    return runtime


def main(argv: list[str] | None = None) -> int:
    """Run the ORION Launcher UI only.

    The launcher is a client/lifecycle controller. It starts or attaches to the
    independent ORION Core process through ``CoreServer``; it never embeds the
    FastAPI application in its own process.
    """

    parser = argparse.ArgumentParser(description="ORION Launcher")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    from orion.desktop_launcher import run_desktop_launcher

    return run_desktop_launcher(_runtime_root(), host=args.host, port=args.port)


if __name__ == "__main__":
    raise SystemExit(main())
