from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

import uvicorn

_NULL_STREAMS: list[TextIO] = []


def _ensure_stdio() -> None:
    """Provide sink streams for a PyInstaller ``--windowed`` Core executable."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is not None:
            continue
        stream = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
        _NULL_STREAMS.append(stream)
        setattr(sys, name, stream)


def _runtime_root() -> Path:
    configured = os.environ.get("ORION_RUNTIME_DIR")
    if configured:
        root = Path(configured).expanduser().resolve()
    else:
        root = Path.cwd() / "runtime"
    root.mkdir(parents=True, exist_ok=True)
    os.environ["ORION_RUNTIME_DIR"] = str(root)
    return root


def _startup_log(runtime: Path, stage: str, detail: str | None = None) -> None:
    line = f"{datetime.now(UTC).isoformat()} {stage}"
    if detail:
        line += f" | {detail}"
    with (runtime / "core-startup.log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def main(argv: list[str] | None = None) -> int:
    """Run ORION Core, or the long-lived Voice worker hosted by the frozen Core binary."""
    _ensure_stdio()
    runtime = _runtime_root()

    try:
        parser = argparse.ArgumentParser(description="ORION Core")
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=8000)
        parser.add_argument("--voice-worker", action="store_true")
        args = parser.parse_args(argv)

        if args.voice_worker:
            os.environ["ORION_PROCESS_ROLE"] = "voice"
            from orion.voice_runtime_worker import main as voice_worker_main

            return voice_worker_main()

        os.environ["ORION_PROCESS_ROLE"] = "core"
        _startup_log(runtime, "boot", f"frozen={bool(getattr(sys, 'frozen', False))}")
        _startup_log(runtime, "args_ready", f"host={args.host} port={args.port}")
        _startup_log(runtime, "app_import_start")
        from orion.app import app

        _startup_log(runtime, "app_import_ready")
        _startup_log(runtime, "uvicorn_start")
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
        _startup_log(runtime, "uvicorn_exit")
        return 0
    except Exception as exc:
        _startup_log(runtime, "fatal", f"{type(exc).__name__}: {exc}")
        with (runtime / "core-startup.log").open("a", encoding="utf-8") as handle:
            traceback.print_exc(file=handle)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
