from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Callable
from uuid import UUID

from orion.windows_audio_worker import AudioDevice, AudioPlaybackRequest, WindowsAudioWorker


class AudioBackend:
    """Small platform boundary used by the worker loop.

    A concrete Windows backend can replace these callables with SAPI/Media Foundation
    or another local implementation without changing ORION Core.
    """

    def __init__(self, play_wav: Callable[[Path, str, float], None], stop: Callable[[], None]) -> None:
        self._play_wav = play_wav
        self._stop = stop

    def play(self, path: Path, device_id: str, volume: float) -> None:
        self._play_wav(path, device_id, volume)

    def stop(self) -> None:
        self._stop()


class WindowsAudioWorkerProcess:
    def __init__(self, worker: WindowsAudioWorker, backend: AudioBackend) -> None:
        self._worker = worker
        self._backend = backend

    def handle(self, payload: dict[str, object]) -> dict[str, object]:
        action = str(payload.get("action", "")).casefold()
        if action == "select_device":
            device = AudioDevice(
                device_id=str(payload.get("device_id", "default")),
                name=str(payload.get("name", payload.get("device_id", "Windows audio output"))),
                is_default=bool(payload.get("is_default", False)),
            )
            return self._worker.select_device(device).model_dump(mode="json")

        if action == "play":
            request = AudioPlaybackRequest(
                command_id=UUID(str(payload["command_id"])),
                audio_path=str(payload["audio_path"]),
                output_device_id=str(payload.get("output_device_id", "default")),
                volume=float(payload.get("volume", 1.0)),
                duck_game_audio=bool(payload.get("duck_game_audio", True)),
            )
            status = self._worker.play(request)
            path = Path(request.audio_path)
            if not path.exists():
                self._worker.stop(request.command_id)
                raise FileNotFoundError(f"Audio file not found: {path}")
            try:
                self._backend.play(path, status.output_device_id, request.volume)
                return self._worker.complete(request.command_id).model_dump(mode="json")
            except Exception:
                self._worker.stop(request.command_id)
                raise

        if action == "stop":
            command_id = payload.get("command_id")
            self._backend.stop()
            parsed = UUID(str(command_id)) if command_id else None
            return self._worker.stop(parsed).model_dump(mode="json")

        if action == "status":
            return self._worker.status().model_dump(mode="json")

        raise ValueError(f"Unsupported worker action: {action or '<empty>'}")


def _dry_run_play(path: Path, device_id: str, volume: float) -> None:
    if not path.exists():
        raise FileNotFoundError(path)


def _dry_run_stop() -> None:
    return None


def run_stdio(process: WindowsAudioWorkerProcess, poll_interval_s: float = 0.05) -> int:
    """Process newline-delimited JSON commands from stdin and emit one JSON result per line."""
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            time.sleep(poll_interval_s)
            continue
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError("Worker command must be a JSON object")
            result = {"ok": True, "result": process.handle(payload)}
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ORION Windows audio worker")
    parser.add_argument("--stdio", action="store_true", help="Read newline-delimited JSON commands from stdin")
    parser.add_argument("--dry-run", action="store_true", help="Validate worker flow without opening a Windows audio device")
    args = parser.parse_args(argv)

    if not args.stdio:
        parser.error("--stdio is currently required")

    backend = AudioBackend(_dry_run_play, _dry_run_stop)
    process = WindowsAudioWorkerProcess(WindowsAudioWorker(), backend)
    return run_stdio(process)


if __name__ == "__main__":
    raise SystemExit(main())
