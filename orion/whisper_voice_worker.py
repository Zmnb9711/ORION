from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from orion.whisper_cpp_stt import (
    WHISPER_MODEL_SHA1,
    WHISPER_MODEL_URL,
    configured_threads,
    whisper_model_path,
)

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
CORE_URL = os.environ.get("ORION_CORE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
VOICE_ENDPOINT = "/v1/voice/text"

@dataclass(frozen=True)
class VoiceBridgeReply:
    heard: str
    reply: str
    matched: bool
    tts_requested: bool

def _state_path() -> Path:
    return Path(os.environ.get("ORION_RUNTIME_DIR", "runtime")) / "voice" / "state.json"

def _write_state(state: str, *, heard: str = "", reply: str = "", error: str = "") -> None:
    path = _state_path(); path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"state": state, "heard": heard, "reply": reply, "error": error, "updated_at": datetime.now(timezone.utc).isoformat()}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"); temporary.replace(path)

def _provision_progress(stage: str, completed: int, total: int | None) -> None:
    detail = f"{stage}: {completed * 100.0 / total:.1f}% ({completed}/{total} bytes)" if total else f"{stage}: {completed} bytes"
    _write_state("PROVISIONING", error=detail)

def whisper_stream_path() -> Path:
    override = os.environ.get("ORION_WHISPER_STREAM")
    if override: return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        bundled = Path(sys.executable).resolve().parent / "whisper" / "whisper-stream.exe"
        if bundled.is_file(): return bundled
    name = "whisper-stream.exe" if os.name == "nt" else "whisper-stream"
    return Path(os.environ.get("ORION_RUNTIME_DIR", "runtime")) / "stt" / "whisper.cpp" / name

def _file_hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()

def _model_ready() -> bool:
    model = whisper_model_path()
    # Avoid hashing the 1.5 GB model on every launch. Download is checksum-verified before atomic install.
    return model.is_file() and model.stat().st_size > 100_000_000

def ensure_voice_model() -> Path:
    """Provision only the model. The live whisper.cpp runtime is shipped by the installer."""
    model = whisper_model_path()
    if _model_ready(): return model
    model.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="orion-voice-model-") as tmp:
        temporary = Path(tmp) / model.name
        request = urllib.request.Request(WHISPER_MODEL_URL, headers={"User-Agent": "ORION-DCS/0.2"})
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            raw_total = response.headers.get("Content-Length")
            try: total = int(raw_total) if raw_total else None
            except ValueError: total = None
            downloaded = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk: break
                output.write(chunk); downloaded += len(chunk); _provision_progress("model", downloaded, total)
        _write_state("PROVISIONING", error="model_verify")
        actual = _file_hash(temporary, "sha1")
        if actual != WHISPER_MODEL_SHA1: raise RuntimeError(f"Whisper medium model checksum mismatch: {actual}")
        temporary.replace(model)
    return model

def _normalize_transcript_line(line: str) -> str:
    text = ANSI_RE.sub("", line).strip()
    if not text: return ""
    if text.casefold().startswith(("whisper_", "ggml_", "main:", "system_info:", "init:", "capture:", "processing", "[start speaking]")): return ""
    if text.startswith("[") and "]" in text and "-->" in text: text = text.split("]", 1)[-1].strip()
    return " ".join(text.split())

def _post_text(text: str, *, core_url: str = CORE_URL, timeout: float = 5.0) -> VoiceBridgeReply:
    body = json.dumps({"text": text, "source": "whisper", "language": "ru"}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(core_url + VOICE_ENDPOINT, data=body, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response: payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc: raise RuntimeError(f"ORION Core voice bridge unavailable: {exc}") from exc
    return VoiceBridgeReply(str(payload.get("heard", text)), str(payload.get("reply", "")), bool(payload.get("matched", False)), bool(payload.get("tts_requested", False)))

def _speak(reply: str) -> None:
    from orion.audio_device_config import audio_device_config
    from orion.native_wasapi_player import NativeWasapiPlayer
    from orion.tts_audio import AudioRenderRequest, TtsBackend, VoiceProfile
    from orion.voice_core import VoiceAgent
    from orion.windows_sapi_backend import WindowsSapiBackend
    output = audio_device_config.state().resolved_output
    if output is None: raise RuntimeError("ORION Voice has no resolved Windows output endpoint")
    spool = Path(os.environ.get("ORION_RUNTIME_DIR", "runtime")) / "voice" / "tts"
    backend = WindowsSapiBackend(spool_dir=str(spool))
    request = AudioRenderRequest(command_id=f"voice-{uuid4()}", text=reply, agent=VoiceAgent.SYSTEM, profile=VoiceProfile(profile_id="voice_v01_ru", locale="ru-RU", persona="orion"), backend=TtsBackend.WINDOWS_SAPI, output_device=output.device_id)
    rendered = backend.render(request)
    if not rendered.accepted or not rendered.output_path: raise RuntimeError(rendered.message)
    NativeWasapiPlayer().play(Path(rendered.output_path), output)

def build_stream_command() -> list[str]:
    stream, model = whisper_stream_path(), whisper_model_path()
    if not stream.is_file(): raise RuntimeError(f"Whisper live microphone component is missing: {stream}")
    if not model.is_file(): raise RuntimeError(f"Whisper model is missing: {model}")
    return [str(stream), "--model", str(model), "--threads", str(configured_threads()), "--language", "ru", "--step", "0", "--length", "8000", "--keep", "0", "--vad-thold", "0.60", "--freq-thold", "100.0", "--no-gpu"]

def startup_probe() -> int:
    try:
        _write_state("PROBING"); stream = whisper_stream_path()
        if not stream.is_file(): raise RuntimeError(f"Whisper live microphone component is missing: {stream}")
        completed = subprocess.run([str(stream), "--help"], cwd=str(stream.parent), capture_output=True, text=True, errors="replace", timeout=10, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if completed.returncode != 0: raise RuntimeError(f"whisper-stream startup probe failed: exit={completed.returncode}; {(completed.stderr or completed.stdout or 'no output').strip()}")
        _write_state("PROBE_PASS"); return 0
    except Exception as exc: _write_state("ERROR", error=f"{type(exc).__name__}: {exc}"); return 1

def run_forever(*, core_url: str = CORE_URL) -> int:
    try:
        stream = whisper_stream_path()
        if not stream.is_file(): raise RuntimeError(f"Whisper live microphone component is missing: {stream}")
        if not _model_ready():
            _write_state("PROVISIONING", error="Preparing local Whisper medium model")
            ensure_voice_model()
        command = build_stream_command(); _write_state("READY")
        process = subprocess.Popen(command, cwd=str(stream.parent), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if process.stdout is None: raise RuntimeError("Whisper stream stdout is unavailable")
        _write_state("LISTENING"); last = ""
        try:
            for raw in process.stdout:
                text = _normalize_transcript_line(raw)
                if not text or text.casefold() == last.casefold(): continue
                last = text; _write_state("HEARD", heard=text)
                bridge = _post_text(text, core_url=core_url); _write_state("CORE_REPLY", heard=bridge.heard, reply=bridge.reply)
                if bridge.tts_requested and bridge.reply:
                    _write_state("SPEAKING", heard=bridge.heard, reply=bridge.reply); _speak(bridge.reply)
                _write_state("LISTENING", heard=bridge.heard, reply=bridge.reply)
        finally:
            if process.poll() is None: process.terminate()
        return int(process.wait())
    except Exception as exc:
        _write_state("ERROR", error=f"{type(exc).__name__}: {exc}"); raise

def main() -> int:
    return startup_probe() if os.environ.get("ORION_VOICE_STARTUP_PROBE") == "1" else run_forever()

if __name__ == "__main__": raise SystemExit(main())
