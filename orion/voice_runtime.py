from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from typing import Any

from pydantic import BaseModel


class VoiceRuntimeStatus(BaseModel):
    state: str
    worker_alive: bool
    whisper_ready: bool
    pid: int | None = None
    message: str = ""


class VoiceRuntimeSupervisor:
    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.RLock()

    def _command(self) -> list[str]:
        override = os.environ.get("ORION_VOICE_EXECUTABLE")
        if override:
            return [override]
        if getattr(sys, "frozen", False):
            return [sys.executable, "--voice-worker"]
        return [sys.executable, "-m", "orion.voice_runtime_worker"]

    def _alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def ensure_ready(self) -> VoiceRuntimeStatus:
        with self._lock:
            if self._alive():
                reply = self._request_unlocked({"action": "ping"})
                return self._status_from_reply(reply)

            env = os.environ.copy()
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            self._process = subprocess.Popen(
                self._command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=env,
                creationflags=creationflags,
            )
            assert self._process.stdout is not None
            startup = self._process.stdout.readline()
            if not startup:
                code = self._process.poll()
                self._process = None
                raise RuntimeError(f"Voice worker exited during startup (code={code})")
            payload = json.loads(startup)
            if not payload.get("ok") or payload.get("event") != "ready":
                error = str(payload.get("error", "Voice worker failed to become ready"))
                self._terminate_unlocked()
                raise RuntimeError(error)
            return VoiceRuntimeStatus(
                state="ready",
                worker_alive=True,
                whisper_ready=bool(payload.get("whisper_ready")),
                pid=self._process.pid,
                message="Voice/Whisper READY",
            )

    def status(self) -> VoiceRuntimeStatus:
        with self._lock:
            if not self._alive():
                return VoiceRuntimeStatus(state="stopped", worker_alive=False, whisper_ready=False)
            try:
                return self._status_from_reply(self._request_unlocked({"action": "ping"}))
            except Exception as exc:
                return VoiceRuntimeStatus(
                    state="error",
                    worker_alive=self._alive(),
                    whisper_ready=False,
                    pid=self._process.pid if self._process is not None else None,
                    message=str(exc),
                )

    def conversation_test(self) -> dict[str, Any]:
        with self._lock:
            ready = self.ensure_ready()
            if not ready.worker_alive or not ready.whisper_ready:
                raise RuntimeError("Voice/Whisper is not ready")
            reply = self._request_unlocked({"action": "conversation_test"})
            if not reply.get("ok"):
                raise RuntimeError(str(reply.get("error", "Voice worker audio test failed")))
            result = reply.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("Voice worker returned an invalid audio test result")
            after = self._request_unlocked({"action": "ping"})
            if not after.get("ok") or not after.get("whisper_ready"):
                raise RuntimeError("Voice worker did not remain ready after audio test")
            return result

    def shutdown(self) -> VoiceRuntimeStatus:
        with self._lock:
            process = self._process
            if process is None:
                return VoiceRuntimeStatus(state="stopped", worker_alive=False, whisper_ready=False)
            if process.poll() is None:
                try:
                    self._request_unlocked({"action": "shutdown"})
                    process.wait(timeout=5.0)
                except Exception:
                    self._terminate_unlocked()
            self._process = None
            return VoiceRuntimeStatus(state="stopped", worker_alive=False, whisper_ready=False, message="Voice worker stopped")

    def _request_unlocked(self, payload: dict[str, Any]) -> dict[str, Any]:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None or process.stdout is None:
            raise RuntimeError("Voice worker is not running")
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.flush()
        line = process.stdout.readline()
        if not line:
            raise RuntimeError("Voice worker closed its control channel")
        result = json.loads(line)
        if not isinstance(result, dict):
            raise RuntimeError("Voice worker returned invalid JSON")
        return result

    def _status_from_reply(self, reply: dict[str, Any]) -> VoiceRuntimeStatus:
        if not reply.get("ok"):
            raise RuntimeError(str(reply.get("error", "Voice worker ping failed")))
        return VoiceRuntimeStatus(
            state=str(reply.get("state", "ready")),
            worker_alive=self._alive(),
            whisper_ready=bool(reply.get("whisper_ready")),
            pid=self._process.pid if self._process is not None else None,
            message="Voice/Whisper READY" if reply.get("whisper_ready") else "Whisper is not ready",
        )

    def _terminate_unlocked(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        self._process = None


voice_runtime = VoiceRuntimeSupervisor()
