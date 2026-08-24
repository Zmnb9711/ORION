from __future__ import annotations

import argparse
import json
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
    """Run the ORION Launcher UI only.

    The launcher is a client/lifecycle controller. It starts or attaches to the
    independent ORION Core process through ``CoreProcessManager``; it never
    embeds the FastAPI application in its own process.
    """

    parser = argparse.ArgumentParser(description="ORION Launcher")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--srs-control-smoke", metavar="RESULT_JSON")
    args = parser.parse_args(argv)

    if args.srs_control_smoke:
        from orion.srs_process_control import launcher_srs_offline_smoke

        Path(args.srs_control_smoke).write_text(
            json.dumps(launcher_srs_offline_smoke(), sort_keys=True),
            encoding="utf-8",
        )
        return 0

    os.environ["ORION_PROCESS_ROLE"] = "launcher"
    os.environ["ORION_CORE_BASE_URL"] = f"http://{args.host}:{args.port}"

    from orion.desktop_launcher_field_fixed import run_field_fixed_launcher

    return run_field_fixed_launcher(_runtime_root(), host=args.host, port=args.port)


if __name__ == "__main__":
    raise SystemExit(main())
