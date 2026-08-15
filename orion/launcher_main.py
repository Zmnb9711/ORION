from __future__ import annotations

import argparse
import os
from pathlib import Path


def _runtime_root() -> Path:
    configured = os.environ.get("ORION_RUNTIME_DIR")
    if configured:
        runtime = Path(configured).expanduser().resolve()
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        runtime = base / "ORION" / "runtime"
    else:
        runtime = Path.home() / ".orion" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    os.environ["ORION_RUNTIME_DIR"] = str(runtime)
    return runtime


def main(argv: list[str] | None = None) -> int:
    """Run the single production ORION Launcher shell."""

    parser = argparse.ArgumentParser(description="ORION Launcher")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    os.environ["ORION_PROCESS_ROLE"] = "launcher"
    os.environ["ORION_CORE_BASE_URL"] = f"http://{args.host}:{args.port}"

    from orion.launcher_shell import run_launcher

    return run_launcher(_runtime_root(), host=args.host, port=args.port)


if __name__ == "__main__":
    raise SystemExit(main())
