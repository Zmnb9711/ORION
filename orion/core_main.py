from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn


def _runtime_root() -> Path:
    configured = os.environ.get("ORION_RUNTIME_DIR")
    if configured:
        root = Path(configured).expanduser().resolve()
    else:
        root = Path.cwd() / "runtime"
    root.mkdir(parents=True, exist_ok=True)
    os.environ["ORION_RUNTIME_DIR"] = str(root)
    return root


def main(argv: list[str] | None = None) -> int:
    """Run ORION Core only.

    This entry point deliberately has no desktop/UI dispatch. Production
    packaging can freeze it as ORION-Core.exe while the launcher remains a
    separate client/process-lifecycle application.
    """

    parser = argparse.ArgumentParser(description="ORION Core")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    _runtime_root()
    uvicorn.run("orion.app:app", host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
