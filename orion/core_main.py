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
    """Keep logging safe for legacy/windowed builds during the hardening migration."""

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


def _runtime_context(runtime: Path) -> str:
    executable = Path(sys.executable).resolve()
    return " ".join(
        (
            f"frozen={bool(getattr(sys, 'frozen', False))}",
            f"pid={os.getpid()}",
            f"cwd={Path.cwd()}",
            f"executable={executable}",
            f"runtime_dir={runtime}",
            f"process_role={os.environ.get('ORION_PROCESS_ROLE', '')}",
        )
    )


def _run_stt_smoke(audio_path: Path, language: str) -> int:
    """Run production Whisper recognition from the frozen Core process.

    This mode exists for CI and diagnostics. It deliberately calls the same
    ``recognize_wav`` function used by Audio Test, so PyInstaller DLL search
    behavior and the native whisper-cli child-process boundary are exercised.
    """
    from orion.whisper_cpp_stt import recognize_wav

    text = recognize_wav(audio_path, language=language)
    print(text, flush=True)
    return 0 if text.strip() else 2


def main(argv: list[str] | None = None) -> int:
    """Run ORION Core only."""

    _ensure_stdio()
    runtime = _runtime_root()
    os.environ["ORION_PROCESS_ROLE"] = "core"
    _startup_log(runtime, "boot", _runtime_context(runtime))

    try:
        parser = argparse.ArgumentParser(description="ORION Core")
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=8000)
        parser.add_argument("--stt-smoke", type=Path, default=None, metavar="WAV")
        parser.add_argument("--stt-language", default="auto")
        args = parser.parse_args(argv)
        _startup_log(runtime, "args_ready", f"host={args.host} port={args.port}")

        if args.stt_smoke is not None:
            _startup_log(runtime, "stt_smoke_start", str(args.stt_smoke))
            result = _run_stt_smoke(args.stt_smoke.resolve(), args.stt_language)
            _startup_log(runtime, "stt_smoke_exit", f"code={result}")
            return result

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
